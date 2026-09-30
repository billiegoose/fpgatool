# pyright: reportInvalidTypeForm=none
"""Quad-output/quad-program SPI transport for Basys 3 configuration flash.

Commands and addresses remain single-bit SPI.  Reads use S25FL032P 0x6B Quad
Output Read and programming uses 0x32 Quad Page Program.  The device's
nonvolatile CR[1] QUAD bit is read first and enabled with WREN+WRR only when
needed, preserving the other Status and Configuration Register bits.
"""

from pypeline import *
from hardware.flash import (
    FLASH_OP_NONE,
    FLASH_OP_READ,
    FLASH_OP_PROGRAM,
    FLASH_OP_ERASE_BLOCK,
    CMD_QUAD_OUTPUT_READ,
    CMD_QUAD_PAGE_PROGRAM,
    CMD_READ_CONFIG,
    CMD_WRITE_REGISTERS,
    CONFIG_QUAD_ENABLE,
    HALF_PERIOD_CYCLES as _HALF_PERIOD_CYCLES,
    STARTUP_PRIME_CYCLES as _STARTUP_PRIME_CYCLES,
    BYTE_POWERUP_CYCLES as _BYTE_POWERUP_CYCLES,
    NORMAL_CS_HIGH_CYCLES as _BYTE_NORMAL_CS_HIGH_CYCLES,
    RECOVERY_CS_HIGH_CYCLES as _BYTE_RECOVERY_CS_HIGH_CYCLES,
    RES_CYCLES as _BYTE_RES_CYCLES,
)


# Generic quad-output/quad-program byte/block access ----------------------------------
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
_BYTE_ST_QE_RDSR = 20
_BYTE_ST_QE_RDSR_DONE = 21
_BYTE_ST_QE_RDCR = 22
_BYTE_ST_QE_RDCR_DONE = 23
_BYTE_ST_QE_WREN = 24
_BYTE_ST_QE_WRR = 25
_BYTE_ST_QE_POLL = 26
_BYTE_ST_QE_POLL_DONE = 27
_BYTE_ST_QE_VERIFY = 28
_BYTE_ST_QE_VERIFY_DONE = 29
_BYTE_ST_BUS = 30
_BYTE_ST_BUS_RX_FINISH = 31
_BYTE_ST_BUS_TX_FINISH = 32
_BYTE_ST_BUS_CS_HIGH = 33



@struct
class qspi_flash_byte_io_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq0_t: uint1_t
    dq1: uint1_t
    dq1_t: uint1_t
    dq2: uint1_t
    dq2_t: uint1_t
    dq3: uint1_t
    dq3_t: uint1_t
    read_data: uint8_t
    ready: uint1_t
    busy: uint1_t
    done: uint1_t
    error: uint1_t
    quad_enabled: uint1_t
    quad_activity: uint1_t
    quad_write_activity: uint1_t




@hw_func
def flash_byte_io(
    dq: uint4_t,
    op: uint2_t,
    address: uint32_t,
    write_data: uint8_t,
) -> qspi_flash_byte_io_t:
    """Generic quad-output/quad-program access to arbitrary flash byte addresses.

    A nonzero ``op`` is sampled only while ``ready`` is high and should normally
    be presented for one clock. ``FLASH_OP_READ`` returns one byte.
    ``FLASH_OP_PROGRAM`` performs WREN + one-byte page program + WIP polling +
    readback verification. ``FLASH_OP_ERASE_BLOCK`` performs WREN + 0xD8 erase +
    WIP polling on the 64 KiB block containing ``address``.
    """

    state: Reg[uint6_t] = _BYTE_ST_POWERUP
    return_state: Reg[uint6_t] = _BYTE_ST_READY
    timer: Reg[uint32_t] = 0

    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1
    tx_shift: Reg[uint64_t] = 0
    tx_remaining: Reg[uint7_t] = 0
    rx_remaining: Reg[uint7_t] = 0
    rx_shift: Reg[uint64_t] = 0
    rx_width: Reg[uint3_t] = 1
    tx_quad_shift: Reg[uint8_t] = 0
    tx_quad_remaining: Reg[uint4_t] = 0

    status_saved: Reg[uint8_t] = 0
    config_saved: Reg[uint8_t] = 0
    quad_enabled: Reg[uint1_t] = 0
    # Sticky proof bits for the actual widened payload phases.
    quad_activity: Reg[uint1_t] = 0
    quad_write_activity: Reg[uint1_t] = 0

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
            state = _BYTE_ST_QE_RDSR
        else:
            timer = timer + 1

    elif state == _BYTE_ST_QE_RDSR:
        tx_shift = uint64_t(0x05) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
        rx_shift = 0
        return_state = _BYTE_ST_QE_RDSR_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_RDSR_DONE:
        status_saved = rx_shift[7:0]
        state = _BYTE_ST_QE_RDCR

    elif state == _BYTE_ST_QE_RDCR:
        tx_shift = uint64_t(CMD_READ_CONFIG) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
        rx_shift = 0
        return_state = _BYTE_ST_QE_RDCR_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_RDCR_DONE:
        config_saved = rx_shift[7:0]
        if rx_shift[1]:
            quad_enabled = 1
            state = _BYTE_ST_READY
        else:
            state = _BYTE_ST_QE_WREN

    elif state == _BYTE_ST_QE_WREN:
        tx_shift = uint64_t(0x06) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 0
        return_state = _BYTE_ST_QE_WRR
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_WRR:
        tx_shift = (uint64_t(CMD_WRITE_REGISTERS) << 56) | (uint64_t(status_saved) << 48) | (uint64_t(config_saved | CONFIG_QUAD_ENABLE) << 40)
        tx_remaining = 24
        tx_quad_remaining = 0
        rx_remaining = 0
        return_state = _BYTE_ST_QE_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_POLL:
        tx_shift = uint64_t(0x05) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
        rx_shift = 0
        return_state = _BYTE_ST_QE_POLL_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_POLL_DONE:
        if rx_shift[0]:
            state = _BYTE_ST_QE_POLL
        else:
            state = _BYTE_ST_QE_VERIFY

    elif state == _BYTE_ST_QE_VERIFY:
        tx_shift = uint64_t(CMD_READ_CONFIG) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
        rx_shift = 0
        return_state = _BYTE_ST_QE_VERIFY_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_QE_VERIFY_DONE:
        if rx_shift[1]:
            quad_enabled = 1
        else:
            quad_enabled = 0
        state = _BYTE_ST_READY

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
        # QSPI.py is intentionally QSPI-only. If CR[1] could not be enabled,
        # fail the request instead of silently falling back to ordinary 0x03 SPI.
        if not quad_enabled:
            error = 1
            done = 1
            state = _BYTE_ST_READY
        elif requested_op == FLASH_OP_ERASE_BLOCK:
            state = _BYTE_ST_ERASE_WREN
        elif requested_op == FLASH_OP_PROGRAM:
            state = _BYTE_ST_PROGRAM_WREN
        elif requested_op == FLASH_OP_READ:
            state = _BYTE_ST_READ
        else:
            state = _BYTE_ST_READY

    elif state == _BYTE_ST_READ:
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_shift = 0
        tx_shift = (uint64_t(CMD_QUAD_OUTPUT_READ) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 40
        rx_width = 4
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
        tx_quad_remaining = 0
        rx_remaining = 0
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM:
        rx_remaining = 0
        tx_shift = (uint64_t(CMD_QUAD_PAGE_PROGRAM) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 32
        tx_quad_shift = requested_data
        tx_quad_remaining = 8
        rx_shift = 0
        return_state = _BYTE_ST_PROGRAM_POLL
        timer = 0
        cclk = 0
        cs_n = 0
        state = _BYTE_ST_BUS

    elif state == _BYTE_ST_PROGRAM_POLL:
        tx_shift = uint64_t(0x05) << 56
        tx_remaining = 8
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
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
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_shift = 0
        tx_shift = (uint64_t(CMD_QUAD_OUTPUT_READ) << 56) | (uint64_t(requested_address) << 32)
        tx_remaining = 40
        rx_width = 4
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
        tx_quad_remaining = 0
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
        tx_quad_remaining = 0
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
        tx_quad_remaining = 0
        rx_remaining = 8
        rx_width = 1
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
                    if rx_width == 4:
                        rx_shift = (rx_shift << 4) | concat(dq[3], dq[2], dq[1], dq[0])
                        quad_activity = 1
                        if rx_remaining <= 4:
                            rx_remaining = 0
                            state = _BYTE_ST_BUS_RX_FINISH
                        else:
                            rx_remaining = rx_remaining - 4
                    else:
                        rx_shift = (rx_shift << 1) | dq[1]
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
                        if rx_remaining == 0 and tx_quad_remaining == 0:
                            state = _BYTE_ST_BUS_TX_FINISH
                    else:
                        tx_remaining = tx_remaining - 1
                elif tx_quad_remaining > 0:
                    tx_quad_shift = tx_quad_shift << 4
                    if tx_quad_remaining <= 4:
                        tx_quad_remaining = 0
                        state = _BYTE_ST_BUS_TX_FINISH
                    else:
                        tx_quad_remaining = tx_quad_remaining - 4
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
    dq1: uint1_t = 1
    dq2: uint1_t = 1
    dq3: uint1_t = 1
    dq0_t: uint1_t = 0
    dq1_t: uint1_t = 1
    dq2_t: uint1_t = 0
    dq3_t: uint1_t = 0

    if state == _BYTE_ST_BUS and tx_remaining > 0:
        dq0 = tx_shift[63]
    elif state == _BYTE_ST_BUS and tx_quad_remaining > 0:
        dq0 = tx_quad_shift[4]
        dq1 = tx_quad_shift[5]
        dq2 = tx_quad_shift[6]
        dq3 = tx_quad_shift[7]
        dq0_t = 0
        dq1_t = 0
        dq2_t = 0
        dq3_t = 0
        # This branch is the actual four-lane program-data drive phase.
        quad_write_activity = 1
    elif state == _BYTE_ST_WAKE_FF or state == _BYTE_ST_WAKE_CMD:
        dq0 = wake_shift[7]

    release_quad: uint1_t = 0
    if rx_width == 4:
        if state == _BYTE_ST_BUS_RX_FINISH:
            release_quad = 1
        elif state == _BYTE_ST_BUS and rx_remaining > 0:
            # QOR starts driving IO3..IO0 on the falling edge after the final
            # dummy bit. Release all four pads during the preceding high
            # half-cycle so they are already high-Z at that falling edge.
            if tx_remaining == 0:
                release_quad = 1
            elif cclk and tx_remaining == 1:
                release_quad = 1
    if release_quad:
        dq0_t = 1
        dq1_t = 1
        dq2_t = 1
        dq3_t = 1

    ready: uint1_t = 0
    if state == _BYTE_ST_READY:
        ready = 1
    busy: uint1_t = not ready

    return qspi_flash_byte_io_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq0_t=dq0_t,
        dq1=dq1,
        dq1_t=dq1_t,
        dq2=dq2,
        dq2_t=dq2_t,
        dq3=dq3,
        dq3_t=dq3_t,
        read_data=read_data,
        ready=ready,
        busy=busy,
        done=done,
        error=error,
        quad_enabled=quad_enabled,
        quad_activity=quad_activity,
        quad_write_activity=quad_write_activity,
    )
