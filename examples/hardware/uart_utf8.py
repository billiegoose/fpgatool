# pyright: reportInvalidTypeForm=none
"""Decode UART UTF-8 once, at receipt, into eight-bit font glyph IDs.

ASCII retains its original value. Sorted non-ASCII code points are mapped to
128, 129, ...; unsupported and malformed sequences produce no buffer edit.
The 115200-baud UART provides thousands of clocks per byte. The scanline
renderer sees only single-byte IDs, not UTF-8 sequences.
"""
from pypeline import *
from hardware.uart_rx import uart_rx_t


def make_uart_utf8_decoder(unicode_codepoints):
    if len(unicode_codepoints) > 128:
        raise ValueError('Glyph IDs must fit in one byte')

    @hw_func
    def decode(received: uart_rx_t) -> uart_rx_t:
        # Break the long path from UART receive-complete detection through
        # Unicode scalar assembly and glyph-ID selection. A one-clock delay
        # is negligible at 115200 baud and changes no byte ordering.
        input_byte: Reg[uint8_t] = 0
        input_valid: Reg[uint1_t] = 0
        input_byte = received.data
        input_valid = received.valid
        pending: Reg[uint2_t] = 0
        accumulator: Reg[uint21_t] = 0
        minimum_scalar: Reg[uint21_t] = 0
        output: uint8_t = 0
        valid: uint1_t = 0
        if input_valid:
            byte: uint8_t = input_byte
            if byte < 128:
                pending = 0
                output = byte
                valid = 1
            elif (byte & 0xC0) == 0x80:
                if pending != 0:
                    value: uint21_t = (accumulator << 6) | uint21_t(byte & 0x3F)
                    accumulator = value
                    remaining: uint2_t = pending
                    pending = remaining - 1
                    if remaining == 1:
                        for index in range(len(unicode_codepoints)):
                            if (value == unicode_codepoints[index]) & (value >= minimum_scalar):
                                output = uint8_t(128 + index)
                                valid = 1
                else:
                    pending = 0
            elif (byte >= 0xC2) & (byte <= 0xDF):
                accumulator = uint21_t(byte & 0x1F)
                minimum_scalar = 0x80
                pending = 1
            elif (byte >= 0xE0) & (byte <= 0xEF):
                accumulator = uint21_t(byte & 0x0F)
                minimum_scalar = 0x800
                pending = 2
            elif (byte >= 0xF0) & (byte <= 0xF4):
                accumulator = uint21_t(byte & 0x07)
                minimum_scalar = 0x10000
                pending = 3
            else:
                pending = 0
        return uart_rx_t(data=output, valid=valid)

    return decode
