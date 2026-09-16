# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Exercise Basys 3 LEDs, switches, and pushbuttons with an interactive chaser."""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def led_chaser():
    counter: Reg[uint32_t] = 0
    position: Reg[uint4_t] = 0
    direction_right: Reg[uint1_t] = 1

    # The PCB numbers LD0..LD15 from right to left, so the physical direction
    # buttons map oppositely to increasing/decreasing LED numbers.
    # If both are held, BTNR wins.
    if board.BTNL:
        direction_right = 1
    if board.BTNR:
        direction_right = 0

    # Default: 100 ms/step. Up is temporarily 2x faster; down is 2x slower.
    step_cycles: uint32_t = 10_000_000
    if board.BTNU:
        step_cycles = 5_000_000
    if board.BTND:
        step_cycles = 20_000_000

    # Center pauses while held. Reset the divider while paused so releasing it
    # always gives a full interval before the next step.
    if board.BTNC:
        counter = 0
    elif counter == (step_cycles - 1):
        counter = 0
        if direction_right:
            if position == 15:
                position = 0
            else:
                position = position + 1
        else:
            if position == 0:
                position = 15
            else:
                position = position - 1
    else:
        counter = counter + 1

    # Each slide switch XORs its matching LED, locally inverting the chaser.
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
