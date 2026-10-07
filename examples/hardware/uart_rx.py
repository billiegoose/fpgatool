# pyright: reportInvalidTypeForm=none
"""UART 8-N-1 receiver with a one-clock strobe, including repeated bytes."""
from pypeline import *


@struct
class uart_rx_t(NamedTuple):
    data: uint8_t
    valid: uint1_t


def make_uart_rx(clock_mhz, baud=115200):
    divisor = round(clock_mhz * 1_000_000 / baud)
    if not 4 <= divisor <= 65535:
        raise ValueError('UART divisor must fit 16 bits and allow start verification')
    half = divisor // 2

    @hw_func
    def receive(rx: uint1_t) -> uart_rx_t:
        meta: Reg[uint1_t] = 1
        sync: Reg[uint1_t] = 1
        state: Reg[uint2_t] = 0
        timer: Reg[uint16_t] = 0
        bit: Reg[uint3_t] = 0
        shift: Reg[uint8_t] = 0
        valid: uint1_t = 0
        if state == 0:
            if sync == 0:
                state = 1
                timer = 0
        elif state == 1:
            if timer == (half - 1):
                timer = 0
                if sync == 0:
                    state = 2
                    bit = 0
                    shift = 0
                else:
                    state = 0
            else:
                timer = timer + 1
        elif state == 2:
            if timer == (divisor - 1):
                timer = 0
                shift = (shift >> 1) | (uint8_t(sync) << 7)
                if bit == 7:
                    state = 3
                else:
                    bit = bit + 1
            else:
                timer = timer + 1
        else:
            if timer == (divisor - 1):
                timer = 0
                state = 0
                valid = sync  # Reject framing errors (low stop bit).
            else:
                timer = timer + 1
        result = uart_rx_t(data=shift, valid=valid)
        sync = meta
        meta = rx
        return result

    return receive
