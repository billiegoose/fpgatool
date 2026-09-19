# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Exercise Basys 3 LEDs, switches, buttons, and seven-segment display."""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import fpgatool_board.basys3.switches as board_switches
import fpgatool_board.basys3.buttons as board_buttons
import hardware.led_chaser as hw


@MAIN(100.0)
def led_chaser():
    out = hw.led_chaser(
        board_switches.SW0, board_switches.SW1, board_switches.SW2, board_switches.SW3,
        board_switches.SW4, board_switches.SW5, board_switches.SW6, board_switches.SW7,
        board_switches.SW8, board_switches.SW9, board_switches.SW10, board_switches.SW11,
        board_switches.SW12, board_switches.SW13, board_switches.SW14, board_switches.SW15,
        board_buttons.BTNL, board_buttons.BTNR, board_buttons.BTNU,
        board_buttons.BTND, board_buttons.BTNC,
    )

    board_leds.LD0 = out.ld0
    board_leds.LD1 = out.ld1
    board_leds.LD2 = out.ld2
    board_leds.LD3 = out.ld3
    board_leds.LD4 = out.ld4
    board_leds.LD5 = out.ld5
    board_leds.LD6 = out.ld6
    board_leds.LD7 = out.ld7
    board_leds.LD8 = out.ld8
    board_leds.LD9 = out.ld9
    board_leds.LD10 = out.ld10
    board_leds.LD11 = out.ld11
    board_leds.LD12 = out.ld12
    board_leds.LD13 = out.ld13
    board_leds.LD14 = out.ld14
    board_leds.LD15 = out.ld15

    board_seven_segment.AN0 = out.an0
    board_seven_segment.AN1 = out.an1
    board_seven_segment.AN2 = out.an2
    board_seven_segment.AN3 = out.an3
    board_seven_segment.CA = out.ca
    board_seven_segment.CB = out.cb
    board_seven_segment.CC = out.cc
    board_seven_segment.CD = out.cd
    board_seven_segment.CE = out.ce
    board_seven_segment.CF = out.cf
    board_seven_segment.CG = out.cg
    board_seven_segment.DP = out.dp
