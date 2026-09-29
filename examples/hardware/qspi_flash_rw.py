# pyright: reportInvalidTypeForm=none
"""Persistent one-value store in the unused tail of Basys 3 configuration flash.

The Basys 3 may contain either a Spansion S25FL032 or Macronix MX25L3233F.
This controller intentionally uses only the common single-bit SPI command set:
READ 0x03, RDSR 0x05, WREN 0x06, PP 0x02, and 64 KiB erase 0xD8.

The final 64 KiB block (0x3F0000..0x3FFFFF) is reserved for user data.  A
four-byte record is stored at its first address: magic, BCD high byte, BCD low
byte, checksum.  Writes always erase that reserved block first, then program
and read back the record.  No configuration-image addresses are modified.
"""

from pypeline import *


_HALF_PERIOD_CYCLES = 10  # 5 MHz SPI from a 100 MHz design clock.
_CS_HIGH_CYCLES = 10  # 100 ns between normal commands; program/erase needs >= 50 ns.
_POWERUP_CYCLES = 2_000_000  # Conservative 20 ms write-safe power-up delay.
_STARTUP_PRIME_CYCLES = 8  # STARTUPE2 consumes the first three USRCCLKO cycles.
_RECOVERY_CS_HIGH_CYCLES = 20  # 200 ns between flash recovery commands.
_RES_CYCLES = 10_000  # 100 us after 0xAB; comfortably beyond tRES.
_USER_BLOCK_ADDRESS = 0x3F0000
_READ_USER_COMMAND = ((0x03 << 24) | _USER_BLOCK_ADDRESS) << 32
_ERASE_USER_COMMAND = ((0xD8 << 24) | _USER_BLOCK_ADDRESS) << 32
_PROGRAM_USER_COMMAND = ((0x02 << 24) | _USER_BLOCK_ADDRESS) << 32
_WREN_COMMAND = 0x0600000000000000
_RDSR_COMMAND = 0x0500000000000000
_MAGIC = 0xA5
_CHECK_SALT = 0x5A

_ST_POWERUP = 0
_ST_BOOT_READ = 1
_ST_BOOT_DONE = 2
_ST_READY = 3
_ST_ERASE_WREN = 4
_ST_ERASE = 5
_ST_ERASE_POLL = 6
_ST_ERASE_POLL_DONE = 7
_ST_PROGRAM_WREN = 8
_ST_PROGRAM = 9
_ST_PROGRAM_POLL = 10
_ST_PROGRAM_POLL_DONE = 11
_ST_VERIFY_READ = 12
_ST_VERIFY_DONE = 13
_ST_BUS = 14
_ST_BUS_RX_FINISH = 15
_ST_BUS_TX_FINISH = 16
_ST_BUS_CS_HIGH = 17
_ST_PRIME = 18
_ST_WAKE_FF = 19
_ST_WAKE_GAP = 20
_ST_WAKE_CMD = 21
_ST_WAKE_RES_WAIT = 22


@struct
class qspi_flash_store_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    value_bcd: uint16_t
    valid: uint1_t
    busy: uint1_t
    save_done: uint1_t
    save_error: uint1_t


@hw_func
def persistent_bcd_store(
    dq1: uint1_t, save: uint1_t, value_to_save: uint16_t
) -> qspi_flash_store_t:
    state: Reg[uint5_t] = _ST_POWERUP
    return_state: Reg[uint5_t] = _ST_READY
    timer: Reg[uint32_t] = 0

    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1
    tx_shift: Reg[uint64_t] = 0
    tx_remaining: Reg[uint7_t] = 0
    rx_remaining: Reg[uint7_t] = 0
    rx_shift: Reg[uint64_t] = 0

    # Cold-boot flash recovery follows the sequence already proven by the
    # read-only JEDEC diagnostic and used by openFPGALoader: prime STARTUPE2
    # CCLK ownership, send all-ones clocks, reset-enable/reset, then release
    # from deep power-down before issuing the first ordinary READ command.
    prime_cycle: Reg[uint4_t] = 0
    wake_ff_byte: Reg[uint4_t] = 0
    wake_bit: Reg[uint4_t] = 0
    wake_step: Reg[uint2_t] = 0
    wake_shift: Reg[uint8_t] = 0

    stored_value: Reg[uint16_t] = 0
    stored_valid: Reg[uint1_t] = 0
    requested_value: Reg[uint16_t] = 0
    save_done: Reg[uint1_t] = 0
    save_error: Reg[uint1_t] = 0

    save_done = 0

    if state == _ST_POWERUP:
        cclk = 0
        cs_n = 1
        if timer >= (_POWERUP_CYCLES - 1):
            timer = 0
            prime_cycle = 0
            state = _ST_PRIME
        else:
            timer = timer + 1

    elif state == _ST_PRIME:
        # UG470: STARTUPE2 consumes the first few user-clock transitions while
        # CCLK ownership transfers to fabric. Keep CS# high and emit several
        # complete clocks before attempting a flash command.
        cs_n = 1
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if prime_cycle >= (_STARTUP_PRIME_CYCLES - 1):
                    cs_n = 0
                    wake_shift = 255
                    wake_bit = 0
                    wake_ff_byte = 0
                    wake_step = 0
                    state = _ST_WAKE_FF
                else:
                    prime_cycle = prime_cycle + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_FF:
        # Nine bytes of all ones mirror openFPGALoader's recovery preamble and
        # help return devices left in an alternate serial mode to a known state.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if wake_bit == 7:
                    wake_bit = 0
                    wake_shift = 255
                    if wake_ff_byte >= 8:
                        cs_n = 1
                        wake_step = 0
                        state = _ST_WAKE_GAP
                    else:
                        wake_ff_byte = wake_ff_byte + 1
                else:
                    wake_shift = wake_shift << 1
                    wake_bit = wake_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_GAP:
        cclk = 0
        cs_n = 1
        if timer >= (_RECOVERY_CS_HIGH_CYCLES - 1):
            timer = 0
            cs_n = 0
            wake_bit = 0
            if wake_step == 0:
                wake_shift = 102  # 0x66, Reset Enable.
            elif wake_step == 1:
                wake_shift = 153  # 0x99, Reset.
            else:
                wake_shift = 171  # 0xAB, Release from Deep Power-Down.
            state = _ST_WAKE_CMD
        else:
            timer = timer + 1

    elif state == _ST_WAKE_CMD:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if wake_bit == 7:
                    cs_n = 1
                    if wake_step == 2:
                        state = _ST_WAKE_RES_WAIT
                    else:
                        wake_step = wake_step + 1
                        state = _ST_WAKE_GAP
                else:
                    wake_shift = wake_shift << 1
                    wake_bit = wake_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_RES_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_RES_CYCLES - 1):
            timer = 0
            state = _ST_BOOT_READ
        else:
            timer = timer + 1

    elif state == _ST_BOOT_READ:
        # 0x03 + 24-bit address, followed by four returned bytes.
        tx_shift = uint64_t(_READ_USER_COMMAND)
        tx_remaining = 32
        rx_remaining = 32
        rx_shift = 0
        return_state = _ST_BOOT_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_BOOT_DONE:
        magic: uint8_t = rx_shift[31:24]
        value_hi: uint8_t = rx_shift[23:16]
        value_lo: uint8_t = rx_shift[15:8]
        check: uint8_t = rx_shift[7:0]
        expected: uint8_t = uint8_t(_MAGIC) ^ value_hi ^ value_lo ^ uint8_t(_CHECK_SALT)
        value: uint16_t = concat(value_hi, value_lo)
        bcd_valid: uint1_t = 1
        if value_hi[7:4] > 9:
            bcd_valid = 0
        elif value_hi[3:0] > 9:
            bcd_valid = 0
        elif value_lo[7:4] > 9:
            bcd_valid = 0
        elif value_lo[3:0] > 9:
            bcd_valid = 0
        if magic == _MAGIC and check == expected and bcd_valid:
            stored_value = value
            stored_valid = 1
        else:
            stored_value = 0
            stored_valid = 0
        state = _ST_READY

    elif state == _ST_READY:
        cclk = 0
        cs_n = 1
        if save:
            requested_value = value_to_save
            save_error = 0
            state = _ST_ERASE_WREN

    elif state == _ST_ERASE_WREN:
        tx_shift = uint64_t(_WREN_COMMAND)
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _ST_ERASE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_ERASE:
        # 0xD8 erases one 64 KiB block on both supported Basys 3 flash parts.
        tx_shift = uint64_t(_ERASE_USER_COMMAND)
        tx_remaining = 32
        rx_remaining = 0
        rx_shift = 0
        return_state = _ST_ERASE_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_ERASE_POLL:
        tx_shift = uint64_t(_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _ST_ERASE_POLL_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_ERASE_POLL_DONE:
        status: uint8_t = rx_shift[7:0]
        if status[0]:
            state = _ST_ERASE_POLL
        else:
            state = _ST_PROGRAM_WREN

    elif state == _ST_PROGRAM_WREN:
        tx_shift = uint64_t(_WREN_COMMAND)
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _ST_PROGRAM
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_PROGRAM:
        value_hi: uint8_t = requested_value[15:8]
        value_lo: uint8_t = requested_value[7:0]
        check: uint8_t = uint8_t(_MAGIC) ^ value_hi ^ value_lo ^ uint8_t(_CHECK_SALT)
        record_word: uint32_t = concat(uint8_t(_MAGIC), value_hi, value_lo, check)
        tx_shift = uint64_t(_PROGRAM_USER_COMMAND) | uint64_t(record_word)
        tx_remaining = 64
        rx_remaining = 0
        rx_shift = 0
        return_state = _ST_PROGRAM_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_PROGRAM_POLL:
        tx_shift = uint64_t(_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _ST_PROGRAM_POLL_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_PROGRAM_POLL_DONE:
        status: uint8_t = rx_shift[7:0]
        if status[0]:
            state = _ST_PROGRAM_POLL
        else:
            state = _ST_VERIFY_READ

    elif state == _ST_VERIFY_READ:
        tx_shift = uint64_t(_READ_USER_COMMAND)
        tx_remaining = 32
        rx_remaining = 32
        rx_shift = 0
        return_state = _ST_VERIFY_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_VERIFY_DONE:
        magic: uint8_t = rx_shift[31:24]
        value_hi: uint8_t = rx_shift[23:16]
        value_lo: uint8_t = rx_shift[15:8]
        check: uint8_t = rx_shift[7:0]
        expected: uint8_t = uint8_t(_MAGIC) ^ value_hi ^ value_lo ^ uint8_t(_CHECK_SALT)
        read_value: uint16_t = concat(value_hi, value_lo)
        if magic == _MAGIC and check == expected and read_value == requested_value:
            stored_value = read_value
            stored_valid = 1
            save_error = 0
        else:
            save_error = 1
        save_done = 1
        state = _ST_READY

    elif state == _ST_BUS:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
                if tx_remaining == 0 and rx_remaining > 0:
                    rx_shift = (rx_shift << 1) | dq1
                    if rx_remaining == 1:
                        rx_remaining = 0
                        state = _ST_BUS_RX_FINISH
                    else:
                        rx_remaining = rx_remaining - 1
            else:
                cclk = 0
                if tx_remaining > 0:
                    tx_shift = tx_shift << 1
                    if tx_remaining == 1:
                        tx_remaining = 0
                        if rx_remaining == 0:
                            state = _ST_BUS_TX_FINISH
                    else:
                        tx_remaining = tx_remaining - 1
        else:
            timer = timer + 1

    elif state == _ST_BUS_RX_FINISH:
        # Preserve the final mode-0 high half-cycle before CS# rises.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            state = _ST_BUS_CS_HIGH
        else:
            timer = timer + 1

    elif state == _ST_BUS_TX_FINISH:
        # CS# rising commits WREN, erase, and page-program transactions.
        # Hold it high in a dedicated state before allowing the next command.
        cs_n = 1
        cclk = 0
        timer = 0
        state = _ST_BUS_CS_HIGH

    elif state == _ST_BUS_CS_HIGH:
        cs_n = 1
        cclk = 0
        if timer >= (_CS_HIGH_CYCLES - 1):
            timer = 0
            state = return_state
        else:
            timer = timer + 1

    dq0: uint1_t = 0
    if state == _ST_BUS and tx_remaining > 0:
        dq0 = tx_shift[63]
    elif state == _ST_WAKE_FF or state == _ST_WAKE_CMD:
        dq0 = wake_shift[7]

    busy: uint1_t = 1
    if state == _ST_READY:
        busy = 0

    return qspi_flash_store_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        value_bcd=stored_value,
        valid=stored_valid,
        busy=busy,
        save_done=save_done,
        save_error=save_error,
    )
