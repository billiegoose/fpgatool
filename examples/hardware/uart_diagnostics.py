# pyright: reportInvalidTypeForm=none
"""UART diagnostics in the 148.5 MHz pixel domain, with persistent indicators."""
from pypeline import *
from hardware.uart_rx import uart_rx_t


@struct
class uart_diagnostics_t(NamedTuple):
    leds: uint16_t
    anodes: uint4_t
    segments: uint7_t


@hw_func
def uart_diagnostics(rx: uint1_t, locked: uint1_t, received: uart_rx_t,
                     committed: uint1_t, full: uint1_t) -> uart_diagnostics_t:
    meta: Reg[uint1_t] = 1
    sync: Reg[uint1_t] = 1
    last: Reg[uint8_t] = 0
    count: Reg[uint8_t] = 0
    seen_low: Reg[uint1_t] = 0
    seen_byte: Reg[uint1_t] = 0
    seen_write: Reg[uint1_t] = 0
    toggle: Reg[uint1_t] = 0
    heartbeat: Reg[uint27_t] = 0
    scan: Reg[uint16_t] = 0
    # Display CCBB: byte count modulo 256, then last byte, both hexadecimal.
    value: uint16_t = (uint16_t(count) << 8) | uint16_t(last)
    digit: uint2_t = scan[15:14]
    nibble: uint4_t = (value >> (uint4_t(digit) << 2)) & 15
    # Bits 0..6 are A..G; ones light segments, pins are active low.
    patterns: uint7_t[16] = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07,
                             0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71]
    leds: uint16_t = (uint16_t(last) | (uint16_t(locked) << 8)
                      | (uint16_t(heartbeat[26]) << 9) | (uint16_t(sync) << 10)
                      | (uint16_t(seen_low) << 11) | (uint16_t(seen_byte) << 12)
                      | (uint16_t(toggle) << 13) | (uint16_t(seen_write) << 14)
                      | (uint16_t(full) << 15))
    result = uart_diagnostics_t(leds=leds, anodes=~(uint4_t(1) << digit),
                                segments=~patterns[nibble])
    if received.valid:
        last = received.data
        count = count + 1
        seen_byte = 1
        toggle = ~toggle
    if sync == 0:
        seen_low = 1
    if committed:
        seen_write = 1
    sync = meta
    meta = rx
    heartbeat = heartbeat + 1
    scan = scan + 1
    return result
