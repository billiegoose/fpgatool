# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic 1 Hz blink hardware for a 100 MHz clock."""

from pypeline import *


@hw_func
def blink_1hz() -> uint1_t:
    counter: Reg[uint32_t] = 0
    led: Reg[uint1_t] = 0

    if counter == (50_000_000 - 1):
        led = ~led
        counter = 0
    else:
        counter = counter + 1

    return led
