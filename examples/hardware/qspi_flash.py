# pyright: reportInvalidTypeForm=none
"""Board-agnostic single-SPI helpers for configuration flash.

``read_jedec_id`` is the original read-only hardware diagnostic. ``flash_byte_io``
adds reusable arbitrary-address byte reads, verified byte programming, and
explicit 64 KiB block erase using the common Basys 3 flash command subset.
DQ2 (WP#) and DQ3 (HOLD#/RESET#) are held high.
"""

from pypeline import *


_HALF_PERIOD_CYCLES = 10  # 100 MHz / (2 * 10) = 5 MHz SCK.
_POWERUP_CYCLES = 100_000  # 1 ms after FPGA user logic starts.
_STARTUP_PRIME_CYCLES = 8  # STARTUPE2 suppresses the first three USRCCLKO cycles.
_CS_HIGH_CYCLES = 20  # 200 ns deselect gap between recovery commands.
_RES_CYCLES = 10_000  # 100 us after 0xAB; comfortably beyond tRES.

_ST_WAIT = 0
_ST_PRIME = 1
_ST_WAKE_FF = 2
_ST_WAKE_CMD = 3
_ST_WAKE_GAP = 4
_ST_WAKE_RES_WAIT = 5
_ST_COMMAND = 6
_ST_READ = 7
_ST_FINISH = 8
_ST_DONE = 9


@struct
class qspi_flash_id_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    manufacturer_id: uint8_t
    memory_type: uint8_t
    capacity: uint8_t
    ready: uint1_t


@hw_func
def read_jedec_id(dq1: uint1_t) -> qspi_flash_id_t:
    """Read the flash's three-byte JEDEC ID once after power-up.

    SPI mode 0 is used: command bits are presented while CCLK is low and the
    flash samples them on rising edges; returned DQ1 bits are sampled on rising
    edges after the command's final falling edge.
    """

    state: Reg[uint4_t] = _ST_WAIT
    timer: Reg[uint32_t] = 0
    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1

    tx_shift: Reg[uint8_t] = 159  # 0x9F, Read JEDEC ID.
    tx_bit: Reg[uint4_t] = 0

    rx_shift: Reg[uint32_t] = 0
    rx_bit: Reg[uint6_t] = 0
    prime_cycle: Reg[uint4_t] = 0
    wake_ff_byte: Reg[uint4_t] = 0
    wake_step: Reg[uint2_t] = 0

    manufacturer_id: Reg[uint8_t] = 0
    memory_type: Reg[uint8_t] = 0
    capacity: Reg[uint8_t] = 0
    ready: Reg[uint1_t] = 0

    if state == _ST_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_POWERUP_CYCLES - 1):
            timer = 0
            prime_cycle = 0
            state = _ST_PRIME
        else:
            timer = timer + 1

    elif state == _ST_PRIME:
        # UG470: the first three USRCCLKO cycles after End Of Startup are consumed
        # while STARTUPE2 switches CCLK to the user source.  Keep CS# high and emit
        # several complete clocks before placing a real flash command on the bus.
        cs_n = 1
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if prime_cycle >= (_STARTUP_PRIME_CYCLES - 1):
                    # Mirror the recovery preamble used by openFPGALoader before
                    # probing the flash: a run of 1s, reset-enable/reset, then
                    # Release from Deep Power-Down.  This returns configuration
                    # flash devices to a known single-SPI command state.
                    cs_n = 0
                    tx_shift = 255
                    tx_bit = 0
                    wake_ff_byte = 0
                    state = _ST_WAKE_FF
                else:
                    prime_cycle = prime_cycle + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_FF:
        # Send nine bytes of 0xFF under one CS# assertion, matching the initial
        # all-ones transaction used by openFPGALoader's flash reset path.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if tx_bit == 7:
                    tx_bit = 0
                    tx_shift = 255
                    if wake_ff_byte >= 8:
                        cs_n = 1
                        wake_step = 0
                        state = _ST_WAKE_GAP
                    else:
                        wake_ff_byte = wake_ff_byte + 1
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_GAP:
        cclk = 0
        cs_n = 1
        if timer >= (_CS_HIGH_CYCLES - 1):
            timer = 0
            cs_n = 0
            tx_bit = 0
            if wake_step == 0:
                tx_shift = 102  # 0x66, Reset Enable.
            elif wake_step == 1:
                tx_shift = 153  # 0x99, Reset.
            else:
                tx_shift = 171  # 0xAB, Release from Deep Power-Down.
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
                if tx_bit == 7:
                    cs_n = 1
                    if wake_step == 2:
                        state = _ST_WAKE_RES_WAIT
                    else:
                        wake_step = wake_step + 1
                        state = _ST_WAKE_GAP
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_RES_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_RES_CYCLES - 1):
            timer = 0
            cs_n = 0
            tx_shift = 159
            tx_bit = 0
            state = _ST_COMMAND
        else:
            timer = timer + 1

    elif state == _ST_COMMAND:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                # Rising edge: flash samples the currently presented MOSI bit.
                cclk = 1
            else:
                # Falling edge: advance MOSI.  After bit 7, the flash begins
                # driving the JEDEC response and we switch to receive mode.
                cclk = 0
                if tx_bit == 7:
                    rx_shift = 0
                    rx_bit = 0
                    state = _ST_READ
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_READ:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                # Mode-0 sample edge.  Oldest received bit ends up at bit 23.
                cclk = 1
                rx_shift = (rx_shift << 1) | dq1
                if rx_bit == 23:
                    state = _ST_FINISH
                else:
                    rx_bit = rx_bit + 1
            else:
                cclk = 0
        else:
            timer = timer + 1

    elif state == _ST_FINISH:
        # Complete the final high half-cycle before releasing chip-select.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            manufacturer_id = rx_shift[23:16]
            memory_type = rx_shift[15:8]
            capacity = rx_shift[7:0]
            ready = 1
            state = _ST_DONE
        else:
            timer = timer + 1

    else:
        cclk = 0
        cs_n = 1

    dq0: uint1_t = 0
    if state == _ST_WAKE_FF or state == _ST_WAKE_CMD or state == _ST_COMMAND:
        dq0 = tx_shift[7]

    return qspi_flash_id_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        manufacturer_id=manufacturer_id,
        memory_type=memory_type,
        capacity=capacity,
        ready=ready,
    )


# Generic single-SPI byte/block access -------------------------------------------------
#
# NOR flash cannot change a programmed 0 bit back to 1 without erasing its whole
# erase block.  `flash_byte_io` therefore exposes that reality rather than hiding a
# destructive read/modify/erase cycle: arbitrary addresses may be read; `program`
# programs one byte (normally into erased storage, or otherwise only clears 1 bits);
# and `erase_block` explicitly erases the 64 KiB block containing `address`.

_BYTE_ST_POWERUP = 0
_BYTE_ST_PRIME = 1
_BYTE_ST_WAKE_FF = 2
_BYTE_ST_WAKE_GAP = 3
_BYTE_ST_WAKE_CMD = 4
_BYTE_ST_WAKE_RES_WAIT = 5
_BYTE_ST_READY = 6
_BYTE_ST_DISPATCH = 7
_BYTE_ST_READ = 8
_BYTE_ST_READ_DONE = 9
_BYTE_ST_PROGRAM_WREN = 10
_BYTE_ST_PROGRAM = 11
_BYTE_ST_PROGRAM_POLL = 12
_BYTE_ST_PROGRAM_POLL_DONE = 13
_BYTE_ST_PROGRAM_VERIFY = 14
_BYTE_ST_PROGRAM_VERIFY_DONE = 15
_BYTE_ST_ERASE_WREN = 16
_BYTE_ST_ERASE = 17
_BYTE_ST_ERASE_POLL = 18
_BYTE_ST_ERASE_POLL_DONE = 19
_BYTE_ST_BUS = 20
_BYTE_ST_BUS_RX_FINISH = 21
_BYTE_ST_BUS_TX_FINISH = 22
_BYTE_ST_BUS_CS_HIGH = 23

_BYTE_POWERUP_CYCLES = 2_000_000
_BYTE_NORMAL_CS_HIGH_CYCLES = 10
_BYTE_RECOVERY_CS_HIGH_CYCLES = 20
_BYTE_RES_CYCLES = 10_000


@struct
class qspi_flash_byte_io_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    read_data: uint8_t
    ready: uint1_t
    busy: uint1_t
    done: uint1_t
    error: uint1_t


FLASH_OP_NONE = 0
FLASH_OP_READ = 1
FLASH_OP_PROGRAM = 2
FLASH_OP_ERASE_BLOCK = 3


@hw_func
def flash_byte_io(
    dq1: uint1_t,
    op: uint2_t,
    address: uint32_t,
    write_data: uint8_t,
) -> qspi_flash_byte_io_t:
    """Generic single-SPI access to arbitrary flash byte addresses.

    A nonzero ``op`` is sampled only while ``ready`` is high and should normally
    be presented for one clock. ``FLASH_OP_READ`` returns one byte.
    ``FLASH_OP_PROGRAM`` performs WREN + one-byte page program + WIP polling +
    readback verification. ``FLASH_OP_ERASE_BLOCK`` performs WREN + 0xD8 erase +
    WIP polling on the 64 KiB block containing ``address``.
    """

    state: Reg[uint5_t] = _BYTE_ST_POWERUP
    return_state: Reg[uint5_t] = _BYTE_ST_READY
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

    requested_op: Reg[uint2_t] = FLASH_OP_NONE
    requested_address: Reg[uint32_t] = 0
    requested_data: Reg[uint8_t] = 0
    read_data: Reg[uint8_t] = 0
    done: Reg[uint1_t] = 0
    error: Reg[uint1_t] = 0

    done = 0

    if state == _BYTE_ST_POWERUP:
        cclk = 0
        cs_n = 1
        if timer >= (_BYTE_POWERUP_CYCLES - 1):
            timer = 0
            prime_cycle = 0
            state = _BYTE_ST_PRIME
        else:
            timer = timer + 1

    elif state == _BYTE_ST_PRIME:
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
                    state = _BYTE_ST_WAKE_FF
                else:
                    prime_cycle = prime_cycle + 1
        else:
            timer = timer + 1

    elif state == _BYTE_ST_WAKE_FF:
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
                        state = _BYTE_ST_WAKE_GAP
                    else:
                        wake_ff_byte = wake_ff_byte + 1
                else:
                    wake_shift = wake_shift << 1
                    wake_bit = wake_bit + 1
        else:
            timer = timer + 1

    elif state == _BYTE_ST_WAKE_GAP:
        cclk = 0
        cs_n = 1
        if timer >= (_BYTE_RECOVERY_CS_HIGH_CYCLES - 1):
            timer = 0
            cs_n = 0
            wake_bit = 0
            if wake_step == 0:
                wake_shift = 102  # 0x66 Reset Enable
            elif wake_step == 1:
                wake_shift = 153  # 0x99 Reset
            else:
                wake_shift = 171  # 0xAB Release from Deep Power-Down
            state = _BYTE_ST_WAKE_CMD
        else:
            timer = timer + 1

    elif state == _BYTE_ST_WAKE_CMD:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if wake_bit == 7:
                    cs_n = 1
                    if wake_step == 2:
                        state = _BYTE_ST_WAKE_RES_WAIT
                    else:
                        wake_step = wake_step + 1
                        state = _BYTE_ST_WAKE_GAP
                else:
                    wake_shift = wake_shift << 1
                    wake_bit = wake_bit + 1
        else:
            timer = timer + 1

    elif state == _BYTE_ST_WAKE_RES_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_BYTE_RES_CYCLES - 1):
            timer = 0
            state = _BYTE_ST_READY
        else:
            timer = timer + 1

    elif state == _BYTE_ST_READY:
        cclk = 0
        cs_n = 1
        if op != FLASH_OP_NONE:
            requested_op = op
            requested_address = address
            requested_data = write_data
            error = 0
            state = _BYTE_ST_DISPATCH

    elif state == _BYTE_ST_DISPATCH:
        # Register the request before branching into the operation-specific
        # sequence. Besides making the one-cycle request contract explicit,
        # this keeps the READY fanout out of the large shared transaction FSM.
        if requested_op == FLASH_OP_ERASE_BLOCK:
            state = _BYTE_ST_ERASE_WREN
        elif requested_op == FLASH_OP_PROGRAM:
            state = _BYTE_ST_PROGRAM_WREN
        elif requested_op == FLASH_OP_READ:
            state = _BYTE_ST_READ
        else:
            state = _BYTE_ST_READY

    elif state == _BYTE_ST_READ:
        tx_shift = (uint64_t(0x03) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 32
        rx_remaining = 8
        rx_shift = 0
        return_state = _BYTE_ST_READ_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_READ_DONE:
        read_data = rx_shift[7:0]
        done = 1
        state = _BYTE_ST_READY

    elif state == _BYTE_ST_PROGRAM_WREN:
        tx_shift = uint64_t(0x06) << 56
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM:
        tx_shift = (
            (uint64_t(0x02) << 56)
            | (uint64_t(requested_address) << 32)
            | (uint64_t(requested_data) << 24)
        )
        tx_remaining = 40
        rx_remaining = 0
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM_POLL:
        tx_shift = uint64_t(0x05) << 56
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM_POLL_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM_POLL_DONE:
        status: uint8_t = rx_shift[7:0]
        if status[0]:
            state = _BYTE_ST_PROGRAM_POLL
        else:
            state = _BYTE_ST_PROGRAM_VERIFY

    elif state == _BYTE_ST_PROGRAM_VERIFY:
        tx_shift = (uint64_t(0x03) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 32
        rx_remaining = 8
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM_VERIFY_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM_VERIFY_DONE:
        read_data = rx_shift[7:0]
        if rx_shift[7:0] != requested_data:
            error = 1
        else:
            error = 0
        done = 1
        state = _BYTE_ST_READY

    elif state == _BYTE_ST_ERASE_WREN:
        tx_shift = uint64_t(0x06) << 56
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _BYTE_ST_ERASE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_ERASE:
        tx_shift = (uint64_t(0xD8) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 32
        rx_remaining = 0
        rx_shift = 0
        return_state = _BYTE_ST_ERASE_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_ERASE_POLL:
        tx_shift = uint64_t(0x05) << 56
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _BYTE_ST_ERASE_POLL_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_ERASE_POLL_DONE:
        status: uint8_t = rx_shift[7:0]
        if status[0]:
            state = _BYTE_ST_ERASE_POLL
        else:
            done = 1
            error = 0
            state = _BYTE_ST_READY

    elif state == _BYTE_ST_BUS:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
                if tx_remaining == 0 and rx_remaining > 0:
                    rx_shift = (rx_shift << 1) | dq1
                    if rx_remaining == 1:
                        rx_remaining = 0
                        state = _BYTE_ST_BUS_RX_FINISH
                    else:
                        rx_remaining = rx_remaining - 1
            else:
                cclk = 0
                if tx_remaining > 0:
                    tx_shift = tx_shift << 1
                    if tx_remaining == 1:
                        tx_remaining = 0
                        if rx_remaining == 0:
                            state = _BYTE_ST_BUS_TX_FINISH
                    else:
                        tx_remaining = tx_remaining - 1
        else:
            timer = timer + 1

    elif state == _BYTE_ST_BUS_RX_FINISH:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            state = _BYTE_ST_BUS_CS_HIGH
        else:
            timer = timer + 1

    elif state == _BYTE_ST_BUS_TX_FINISH:
        cs_n = 1
        cclk = 0
        timer = 0
        state = _BYTE_ST_BUS_CS_HIGH

    elif state == _BYTE_ST_BUS_CS_HIGH:
        cs_n = 1
        cclk = 0
        if timer >= (_BYTE_NORMAL_CS_HIGH_CYCLES - 1):
            timer = 0
            state = return_state
        else:
            timer = timer + 1

    dq0: uint1_t = 0
    if state == _BYTE_ST_BUS and tx_remaining > 0:
        dq0 = tx_shift[63]
    elif state == _BYTE_ST_WAKE_FF or state == _BYTE_ST_WAKE_CMD:
        dq0 = wake_shift[7]

    ready: uint1_t = 0
    if state == _BYTE_ST_READY:
        ready = 1
    busy: uint1_t = not ready

    return qspi_flash_byte_io_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        read_data=read_data,
        ready=ready,
        busy=busy,
        done=done,
        error=error,
    )


# Status/WREN diagnostic --------------------------------------------------------------
#
# This is kept in the same canonical flash module so examples do not carry a
# second physical SPI implementation module.  It intentionally issues no erase
# or program command.

_STATUS_RDSR_COMMAND = 0x0500000000000000
_STATUS_WREN_COMMAND = 0x0600000000000000

_STATUS_ST_POWERUP = 0
_STATUS_ST_READ_BEFORE = 1
_STATUS_ST_READ_BEFORE_DONE = 2
_STATUS_ST_WREN = 3
_STATUS_ST_READ_AFTER = 4
_STATUS_ST_READ_AFTER_DONE = 5
_STATUS_ST_DONE = 6
_STATUS_ST_BUS = 7
_STATUS_ST_BUS_RX_FINISH = 8
_STATUS_ST_BUS_TX_FINISH = 9
_STATUS_ST_BUS_CS_HIGH = 10

@struct
class qspi_flash_status_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    status_before: uint8_t
    status_after: uint8_t
    ready: uint1_t


@hw_func
def read_status_and_test_wren(dq1: uint1_t) -> qspi_flash_status_t:
    state: Reg[uint4_t] = _STATUS_ST_POWERUP
    return_state: Reg[uint4_t] = _STATUS_ST_DONE
    timer: Reg[uint32_t] = 0

    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1
    tx_shift: Reg[uint64_t] = 0
    tx_remaining: Reg[uint7_t] = 0
    rx_remaining: Reg[uint7_t] = 0
    rx_shift: Reg[uint64_t] = 0

    status_before: Reg[uint8_t] = 0
    status_after: Reg[uint8_t] = 0
    ready: Reg[uint1_t] = 0

    if state == _STATUS_ST_POWERUP:
        cclk = 0
        cs_n = 1
        if timer >= (_BYTE_POWERUP_CYCLES - 1):
            timer = 0
            state = _STATUS_ST_READ_BEFORE
        else:
            timer = timer + 1

    elif state == _STATUS_ST_READ_BEFORE:
        tx_shift = uint64_t(_STATUS_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _STATUS_ST_READ_BEFORE_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _STATUS_ST_BUS

    elif state == _STATUS_ST_READ_BEFORE_DONE:
        status_before = rx_shift[7:0]
        state = _STATUS_ST_WREN

    elif state == _STATUS_ST_WREN:
        tx_shift = uint64_t(_STATUS_WREN_COMMAND)
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _STATUS_ST_READ_AFTER
        timer = 0
        cclk = 0
        cs_n = 0
        state = _STATUS_ST_BUS

    elif state == _STATUS_ST_READ_AFTER:
        tx_shift = uint64_t(_STATUS_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _STATUS_ST_READ_AFTER_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _STATUS_ST_BUS

    elif state == _STATUS_ST_READ_AFTER_DONE:
        status_after = rx_shift[7:0]
        ready = 1
        state = _STATUS_ST_DONE

    elif state == _STATUS_ST_DONE:
        cclk = 0
        cs_n = 1

    elif state == _STATUS_ST_BUS:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
                if tx_remaining == 0 and rx_remaining > 0:
                    rx_shift = (rx_shift << 1) | dq1
                    if rx_remaining == 1:
                        rx_remaining = 0
                        state = _STATUS_ST_BUS_RX_FINISH
                    else:
                        rx_remaining = rx_remaining - 1
            else:
                cclk = 0
                if tx_remaining > 0:
                    tx_shift = tx_shift << 1
                    if tx_remaining == 1:
                        tx_remaining = 0
                        if rx_remaining == 0:
                            state = _STATUS_ST_BUS_TX_FINISH
                    else:
                        tx_remaining = tx_remaining - 1
        else:
            timer = timer + 1

    elif state == _STATUS_ST_BUS_RX_FINISH:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            state = _STATUS_ST_BUS_CS_HIGH
        else:
            timer = timer + 1

    elif state == _STATUS_ST_BUS_TX_FINISH:
        cs_n = 1
        cclk = 0
        timer = 0
        state = _STATUS_ST_BUS_CS_HIGH

    else:  # _STATUS_ST_BUS_CS_HIGH
        cs_n = 1
        cclk = 0
        if timer >= (_BYTE_NORMAL_CS_HIGH_CYCLES - 1):
            timer = 0
            state = return_state
        else:
            timer = timer + 1

    dq0: uint1_t = 0
    if state == _STATUS_ST_BUS and tx_remaining > 0:
        dq0 = tx_shift[63]

    return qspi_flash_status_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        status_before=status_before,
        status_after=status_after,
        ready=ready,
    )
