# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Blink Basys 3 LD0 at 1 Hz from its 100 MHz oscillator."""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def blink():
    counter: Reg[uint32_t] = 0
    led: Reg[uint1_t] = 0

    if counter == (50_000_000 - 1):
        led = ~led
        counter = 0
    else:
        counter = counter + 1

    board.LD0 = led
