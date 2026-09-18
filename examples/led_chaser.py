# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Exercise Basys 3 LEDs, switches, buttons, and seven-segment display."""

from pypeline import *
import board.basys3.part35t
import board.basys3.user_io as board_user
import hardware.led_chaser as hw


@MAIN(100.0)
def led_chaser():
    out = hw.led_chaser(
        board_user.SW0, board_user.SW1, board_user.SW2, board_user.SW3,
        board_user.SW4, board_user.SW5, board_user.SW6, board_user.SW7,
        board_user.SW8, board_user.SW9, board_user.SW10, board_user.SW11,
        board_user.SW12, board_user.SW13, board_user.SW14, board_user.SW15,
        board_user.BTNL, board_user.BTNR, board_user.BTNU,
        board_user.BTND, board_user.BTNC,
    )

    board_user.LD0 = out.ld0
    board_user.LD1 = out.ld1
    board_user.LD2 = out.ld2
    board_user.LD3 = out.ld3
    board_user.LD4 = out.ld4
    board_user.LD5 = out.ld5
    board_user.LD6 = out.ld6
    board_user.LD7 = out.ld7
    board_user.LD8 = out.ld8
    board_user.LD9 = out.ld9
    board_user.LD10 = out.ld10
    board_user.LD11 = out.ld11
    board_user.LD12 = out.ld12
    board_user.LD13 = out.ld13
    board_user.LD14 = out.ld14
    board_user.LD15 = out.ld15

    board_user.AN0 = out.an0
    board_user.AN1 = out.an1
    board_user.AN2 = out.an2
    board_user.AN3 = out.an3
    board_user.CA = out.ca
    board_user.CB = out.cb
    board_user.CC = out.cc
    board_user.CD = out.cd
    board_user.CE = out.ce
    board_user.CF = out.cf
    board_user.CG = out.cg
    board_user.DP = out.dp
