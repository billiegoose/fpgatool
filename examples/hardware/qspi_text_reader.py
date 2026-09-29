# pyright: reportInvalidTypeForm=none
"""Read-only four-character window into a text image in Basys 3 QSPI flash."""

from pypeline import *

_HALF_PERIOD_CYCLES = 10
_POWERUP_CYCLES = 2_000_000
_STARTUP_PRIME_CYCLES = 8
_RECOVERY_CS_HIGH_CYCLES = 20
_RES_CYCLES = 10_000

_TEXT_SECTOR_ADDRESS = 0x3E0000
_TEXT_DATA_ADDRESS = _TEXT_SECTOR_ADDRESS + 6
_TEXT_MAX_LENGTH = 65530
_MAGIC = 0x45524452  # ASCII ERDR

_ST_POWERUP = 0
_ST_PRIME = 1
_ST_WAKE_FF = 2
_ST_WAKE_GAP = 3
_ST_WAKE_CMD = 4
_ST_WAKE_RES_WAIT = 5
_ST_HEADER = 6
_ST_HEADER_DONE = 7
_ST_READY = 8
_ST_WINDOW = 9
_ST_WINDOW_DONE = 10
_ST_BUS = 11
_ST_BUS_RX_FINISH = 12
_ST_BUS_TX_FINISH = 13
_ST_BUS_CS_HIGH = 14


@struct
class qspi_text_window_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    char0: uint8_t
    char1: uint8_t
    char2: uint8_t
    char3: uint8_t
    position: uint16_t
    length: uint16_t
    valid: uint1_t
    busy: uint1_t
    error: uint1_t


@hw_func
def read_text_window(dq1: uint1_t, move_left: uint1_t, move_right: uint1_t) -> qspi_text_window_t:
    state: Reg[uint4_t] = _ST_POWERUP
    return_state: Reg[uint4_t] = _ST_READY
    timer: Reg[uint32_t] = 0

    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1
    tx_shift: Reg[uint64_t] = 0
    tx_remaining: Reg[uint7_t] = 0
    rx_remaining: Reg[uint7_t] = 0
    rx_shift: Reg[uint64_t] = 0

    prime_cycle: Reg[uint4_t] = 0
    wake_ff_byte: Reg[uint4_t] = 0
    wake_bit: Reg[uint4_t] = 0
    wake_step: Reg[uint2_t] = 0
    wake_shift: Reg[uint8_t] = 0

    position: Reg[uint16_t] = 0
    length: Reg[uint16_t] = 0
    char0: Reg[uint8_t] = 32
    char1: Reg[uint8_t] = 32
    char2: Reg[uint8_t] = 32
    char3: Reg[uint8_t] = 32
    valid: Reg[uint1_t] = 0
    error: Reg[uint1_t] = 0

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
        cs_n = 1
        if timer == 0:
            cclk = 1
            timer = 1
        else:
            cclk = 0
            timer = 0
            if prime_cycle >= (_STARTUP_PRIME_CYCLES - 1):
                wake_ff_byte = 0
                wake_bit = 0
                wake_shift = 255
                cs_n = 0
                state = _ST_WAKE_FF
            else:
                prime_cycle = prime_cycle + 1

    elif state == _ST_WAKE_FF:
        cs_n = 0
        if timer < (_HALF_PERIOD_CYCLES - 1):
            timer = timer + 1
        else:
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                wake_shift = uint8_t((wake_shift << 1) | 1)
                if wake_bit >= 7:
                    wake_bit = 0
                    if wake_ff_byte >= 8:
                        cs_n = 1
                        wake_step = 0
                        timer = 0
                        state = _ST_WAKE_GAP
                    else:
                        wake_ff_byte = wake_ff_byte + 1
                        wake_shift = 255
                else:
                    wake_bit = wake_bit + 1

    elif state == _ST_WAKE_GAP:
        cclk = 0
        cs_n = 1
        if timer >= (_RECOVERY_CS_HIGH_CYCLES - 1):
            timer = 0
            wake_bit = 0
            if wake_step == 0:
                wake_shift = 102
            elif wake_step == 1:
                wake_shift = 153
            else:
                wake_shift = 171
            cs_n = 0
            state = _ST_WAKE_CMD
        else:
            timer = timer + 1

    elif state == _ST_WAKE_CMD:
        cs_n = 0
        if timer < (_HALF_PERIOD_CYCLES - 1):
            timer = timer + 1
        else:
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                wake_shift = uint8_t(wake_shift << 1)
                if wake_bit >= 7:
                    wake_bit = 0
                    cs_n = 1
                    timer = 0
                    if wake_step >= 2:
                        state = _ST_WAKE_RES_WAIT
                    else:
                        wake_step = wake_step + 1
                        state = _ST_WAKE_GAP
                else:
                    wake_bit = wake_bit + 1

    elif state == _ST_WAKE_RES_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_RES_CYCLES - 1):
            timer = 0
            state = _ST_HEADER
        else:
            timer = timer + 1

    elif state == _ST_HEADER:
        # Build the 32-bit SPI command directly in the high half of the 64-bit
        # shift register. Keeping both fields explicitly uint64_t avoids
        # PipelineC expression-width inference across shifts and bitwise ORs.
        tx_shift = (uint64_t(0x03) << 56) | (uint64_t(_TEXT_SECTOR_ADDRESS) << 32)
        tx_remaining = 32
        rx_remaining = 48
        rx_shift = 0
        return_state = _ST_HEADER_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_HEADER_DONE:
        header_magic: uint32_t = uint32_t(rx_shift >> 16)
        header_length: uint16_t = uint16_t(rx_shift)
        if header_magic == _MAGIC and header_length > 0 and header_length <= _TEXT_MAX_LENGTH:
            length = header_length
            position = 0
            valid = 1
            error = 0
            state = _ST_WINDOW
        else:
            valid = 0
            error = 1
            state = _ST_READY

    elif state == _ST_READY:
        cclk = 0
        cs_n = 1
        if valid:
            max_position: uint16_t = 0
            if length > 4:
                max_position = length - 4
            if move_left and position > 0:
                position = position - 1
                state = _ST_WINDOW
            elif move_right and position < max_position:
                position = position + 1
                state = _ST_WINDOW

    elif state == _ST_WINDOW:
        address: uint32_t = _TEXT_DATA_ADDRESS + position
        # As above, form the command from two explicit 64-bit fields. This
        # avoids both shift-before-widen truncation and a PipelineC lowering
        # where uint26_t OR uint32_t was inferred to return uint26_t.
        tx_shift = (uint64_t(0x03) << 56) | (uint64_t(address) << 32)
        tx_remaining = 32
        rx_remaining = 32
        rx_shift = 0
        return_state = _ST_WINDOW_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_WINDOW_DONE:
        char0 = uint8_t(rx_shift >> 24)
        char1 = uint8_t(rx_shift >> 16)
        char2 = uint8_t(rx_shift >> 8)
        char3 = uint8_t(rx_shift)
        state = _ST_READY

    elif state == _ST_BUS:
        cs_n = 0
        if timer < (_HALF_PERIOD_CYCLES - 1):
            timer = timer + 1
        else:
            timer = 0
            if cclk == 0:
                cclk = 1
                if tx_remaining == 0 and rx_remaining > 0:
                    rx_shift = uint64_t((rx_shift << 1) | dq1)
                    rx_remaining = rx_remaining - 1
            else:
                cclk = 0
                if tx_remaining > 0:
                    tx_shift = uint64_t(tx_shift << 1)
                    tx_remaining = tx_remaining - 1
                    if tx_remaining == 1:
                        state = _ST_BUS_TX_FINISH
                elif rx_remaining == 0:
                    state = _ST_BUS_RX_FINISH

    elif state == _ST_BUS_TX_FINISH:
        cs_n = 0
        if rx_remaining == 0:
            timer = 0
            state = _ST_BUS_RX_FINISH
        else:
            state = _ST_BUS

    elif state == _ST_BUS_RX_FINISH:
        cclk = 0
        cs_n = 1
        timer = 0
        state = _ST_BUS_CS_HIGH

    elif state == _ST_BUS_CS_HIGH:
        cclk = 0
        cs_n = 1
        if timer >= 9:
            timer = 0
            state = return_state
        else:
            timer = timer + 1

    dq0: uint1_t = 0
    if state == _ST_BUS and tx_remaining > 0:
        dq0 = tx_shift[63]
    elif state == _ST_WAKE_FF or state == _ST_WAKE_CMD:
        dq0 = wake_shift[7]

    busy: uint1_t = state != _ST_READY
    return qspi_text_window_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        char0=char0,
        char1=char1,
        char2=char2,
        char3=char3,
        position=position,
        length=length,
        valid=valid,
        busy=busy,
        error=error,
    )
