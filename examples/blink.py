# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Blink Basys 3 LD0 at 1 Hz from its 100 MHz oscillator."""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.blink as hw


@MAIN(100.0)
def blink():
    board_leds.LD0 = hw.blink_1hz()
    board_leds.LD1 = 0
    board_leds.LD2 = 0
    board_leds.LD3 = 0
    board_leds.LD4 = 0
    board_leds.LD5 = 0
    board_leds.LD6 = 0
    board_leds.LD7 = 0
    board_leds.LD8 = 0
    board_leds.LD9 = 0
    board_leds.LD10 = 0
    board_leds.LD11 = 0
    board_leds.LD12 = 0
    board_leds.LD13 = 0
    board_leds.LD14 = 0
    board_leds.LD15 = 0

    # Active-low seven-segment outputs; all high keeps the display dark.
    board_seven_segment.AN0 = 1
    board_seven_segment.AN1 = 1
    board_seven_segment.AN2 = 1
    board_seven_segment.AN3 = 1
    board_seven_segment.CA = 1
    board_seven_segment.CB = 1
    board_seven_segment.CC = 1
    board_seven_segment.CD = 1
    board_seven_segment.CE = 1
    board_seven_segment.CF = 1
    board_seven_segment.CG = 1
    board_seven_segment.DP = 1
