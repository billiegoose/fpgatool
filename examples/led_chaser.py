# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Chase one lit LED across LD0..LD15; each matching SW switch inverts it."""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def led_chaser():
    # Advance every 100 ms from the 100 MHz board clock.
    counter: Reg[uint32_t] = 0
    position: Reg[uint4_t] = 0

    if counter == (10_000_000 - 1):
        counter = 0
        position = position + 1
    else:
        counter = counter + 1

    # Each switch XORs its matching LED, so the switch locally inverts the chaser.
    board.LD0 = (position == 0) ^ board.SW0
    board.LD1 = (position == 1) ^ board.SW1
    board.LD2 = (position == 2) ^ board.SW2
    board.LD3 = (position == 3) ^ board.SW3
    board.LD4 = (position == 4) ^ board.SW4
    board.LD5 = (position == 5) ^ board.SW5
    board.LD6 = (position == 6) ^ board.SW6
    board.LD7 = (position == 7) ^ board.SW7
    board.LD8 = (position == 8) ^ board.SW8
    board.LD9 = (position == 9) ^ board.SW9
    board.LD10 = (position == 10) ^ board.SW10
    board.LD11 = (position == 11) ^ board.SW11
    board.LD12 = (position == 12) ^ board.SW12
    board.LD13 = (position == 13) ^ board.SW13
    board.LD14 = (position == 14) ^ board.SW14
    board.LD15 = (position == 15) ^ board.SW15
