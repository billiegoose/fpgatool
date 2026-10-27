# pyright: reportInvalidTypeForm=none
"""0x6B continuous quad-output reads, after QSPI.flash_byte_io enables QE.

148.5 MHz / (2 * 5) = 14.85 MHz SCK. Command/address/dummy use 40 serial
clocks once, then each byte takes two clocks. No stalls occur on the wire;
the consumer must accept every valid byte (one per 20 pixel clocks).
"""
from pypeline import *
from hardware.QSPI import qspi_flash_byte_io_t

HALF_PERIOD_CYCLES = 5


@struct
class qspi_burst_t(NamedTuple):
    pins: qspi_flash_byte_io_t
    valid: uint1_t


@hw_func
def read_burst(dq: uint4_t, start: uint1_t, address: uint24_t,
               length: uint13_t, abort: uint1_t) -> qspi_burst_t:
    state: Reg[uint3_t] = 0  # idle, transmit, receive, last falling edge, CS gap
    timer: Reg[uint3_t] = 0
    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1
    tx: Reg[uint40_t] = 0
    bits: Reg[uint6_t] = 0
    remaining: Reg[uint13_t] = 0
    byte: Reg[uint8_t] = 0
    nibble: Reg[uint1_t] = 0
    data: Reg[uint8_t] = 0
    ready: uint1_t = state == 0
    valid: uint1_t = 0
    done: uint1_t = 0
    error: uint1_t = 0
    # Release all pads before the falling edge ending the final dummy clock.
    release: uint1_t = (state >= 2) | ((state == 1) & (bits == 1) & cclk)
    mosi: uint1_t = tx[39]
    if state == 0:
        if start:
            if length == 0:
                error = 1
                done = 1
            else:
                tx = (uint40_t(0x6b) << 32) | (uint40_t(address) << 8)
                bits = 40
                remaining = length
                nibble = 0
                byte = 0
                timer = 0
                cclk = 0
                cs_n = 0
                state = 1
    elif state == 4:
        if timer == (HALF_PERIOD_CYCLES - 1):
            timer = 0
            done = 1
            state = 0
        else:
            timer = timer + 1
    elif timer == (HALF_PERIOD_CYCLES - 1):
        timer = 0
        if cclk == 0:
            cclk = 1
            if state == 2:
                byte = (byte << 4) | uint8_t(dq)
                if nibble:
                    data = byte
                    valid = 1
                    remaining = remaining - 1
                    if remaining == 0:
                        state = 3
                nibble = ~nibble
        else:
            cclk = 0
            if state == 1:
                tx = tx << 1
                bits = bits - 1
                if bits == 0:
                    state = 2
            elif state == 3:
                cs_n = 1
                state = 4
    else:
        timer = timer + 1
    if abort:
        state = 0
        timer = 0
        cclk = 0
        cs_n = 1
        valid = 0
        done = 0
    pins = qspi_flash_byte_io_t(cclk=cclk, cs_n=cs_n,
        dq0=mosi, dq0_t=release, dq1=1, dq1_t=1,
        dq2=1, dq2_t=release, dq3=1, dq3_t=release,
        read_data=data, ready=ready, busy=~ready, done=done, error=error,
        quad_enabled=1, quad_activity=valid, quad_write_activity=0)
    return qspi_burst_t(pins=pins, valid=valid)
