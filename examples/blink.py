# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Blink Basys 3 LD0 at 1 Hz from its 100 MHz oscillator."""

from pypeline import *
import board.basys3.part35t
import board.basys3.user_io as board_user
import hardware.blink as hw


@MAIN(100.0)
def blink():
    board_user.LD0 = hw.blink_1hz()
    board_user.LD1 = 0
    board_user.LD2 = 0
    board_user.LD3 = 0
    board_user.LD4 = 0
    board_user.LD5 = 0
    board_user.LD6 = 0
    board_user.LD7 = 0
    board_user.LD8 = 0
    board_user.LD9 = 0
    board_user.LD10 = 0
    board_user.LD11 = 0
    board_user.LD12 = 0
    board_user.LD13 = 0
    board_user.LD14 = 0
    board_user.LD15 = 0

    # Active-low seven-segment outputs; all high keeps the display dark.
    board_user.AN0 = 1
    board_user.AN1 = 1
    board_user.AN2 = 1
    board_user.AN3 = 1
    board_user.CA = 1
    board_user.CB = 1
    board_user.CC = 1
    board_user.CD = 1
    board_user.CE = 1
    board_user.CF = 1
    board_user.CG = 1
    board_user.DP = 1
