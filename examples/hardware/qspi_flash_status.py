# pyright: reportInvalidTypeForm=none
"""Non-destructive Basys 3 configuration-flash status diagnostic.

Reads RDSR, issues WREN, then reads RDSR again.  No erase or program command is
sent.  The before/after bytes expose block-protection bits and whether WREN
actually sets WEL on the live flash.
"""

from pypeline import *


_HALF_PERIOD_CYCLES = 10  # 5 MHz SPI from 100 MHz.
_CS_HIGH_CYCLES = 10  # 100 ns between commands.
_POWERUP_CYCLES = 2_000_000  # 20 ms after configuration.

_RDSR_COMMAND = 0x0500000000000000
_WREN_COMMAND = 0x0600000000000000

_ST_POWERUP = 0
_ST_READ_BEFORE = 1
_ST_READ_BEFORE_DONE = 2
_ST_WREN = 3
_ST_READ_AFTER = 4
_ST_READ_AFTER_DONE = 5
_ST_DONE = 6
_ST_BUS = 7
_ST_BUS_RX_FINISH = 8
_ST_BUS_TX_FINISH = 9
_ST_BUS_CS_HIGH = 10


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
    state: Reg[uint4_t] = _ST_POWERUP
    return_state: Reg[uint4_t] = _ST_DONE
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

    if state == _ST_POWERUP:
        cclk = 0
        cs_n = 1
        if timer >= (_POWERUP_CYCLES - 1):
            timer = 0
            state = _ST_READ_BEFORE
        else:
            timer = timer + 1

    elif state == _ST_READ_BEFORE:
        tx_shift = uint64_t(_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _ST_READ_BEFORE_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_READ_BEFORE_DONE:
        status_before = rx_shift[7:0]
        state = _ST_WREN

    elif state == _ST_WREN:
        tx_shift = uint64_t(_WREN_COMMAND)
        tx_remaining = 8
        rx_remaining = 0
        rx_shift = 0
        return_state = _ST_READ_AFTER
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_READ_AFTER:
        tx_shift = uint64_t(_RDSR_COMMAND)
        tx_remaining = 8
        rx_remaining = 8
        rx_shift = 0
        return_state = _ST_READ_AFTER_DONE
        timer = 0
        cclk = 0
        cs_n = 0
        state = _ST_BUS

    elif state == _ST_READ_AFTER_DONE:
        status_after = rx_shift[7:0]
        ready = 1
        state = _ST_DONE

    elif state == _ST_DONE:
        cclk = 0
        cs_n = 1

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
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            state = _ST_BUS_CS_HIGH
        else:
            timer = timer + 1

    elif state == _ST_BUS_TX_FINISH:
        cs_n = 1
        cclk = 0
        timer = 0
        state = _ST_BUS_CS_HIGH

    else:  # _ST_BUS_CS_HIGH
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
