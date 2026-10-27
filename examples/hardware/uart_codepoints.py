# pyright: reportInvalidTypeForm=none
"""UART UTF-8 to Unicode scalars, independent of any loaded font."""
from pypeline import *
from hardware.uart_rx import uart_rx_t


@struct
class codepoint_event_t(NamedTuple):
    data: uint24_t
    valid: uint1_t


@hw_func
def uart_codepoints(received: uart_rx_t) -> codepoint_event_t:
    byte: Reg[uint8_t] = 0
    strobe: Reg[uint1_t] = 0
    pending: Reg[uint2_t] = 0
    accumulator: Reg[uint21_t] = 0
    minimum: Reg[uint21_t] = 0
    output: uint24_t = 0
    valid: uint1_t = 0
    if strobe:
        if byte < 128:
            pending = 0
            output = uint24_t(byte)
            valid = 1
        elif (byte & 0xC0) == 0x80:
            if pending != 0:
                value: uint21_t = (accumulator << 6) | uint21_t(byte & 63)
                accumulator = value
                remaining: uint2_t = pending
                pending = remaining - 1
                if remaining == 1:
                    if (value >= minimum) & (value <= 0x10FFFF) & ((value < 0xD800) | (value > 0xDFFF)):
                        output = uint24_t(value)
                        valid = 1
        elif (byte >= 0xC2) & (byte <= 0xDF):
            accumulator = uint21_t(byte & 31)
            minimum = 0x80
            pending = 1
        elif (byte >= 0xE0) & (byte <= 0xEF):
            accumulator = uint21_t(byte & 15)
            minimum = 0x800
            pending = 2
        elif (byte >= 0xF0) & (byte <= 0xF4):
            accumulator = uint21_t(byte & 7)
            minimum = 0x10000
            pending = 3
        else:
            pending = 0
    # Read the previous byte above before capturing the next UART event.
    byte = received.data
    strobe = received.valid
    return codepoint_event_t(data=output, valid=valid)
