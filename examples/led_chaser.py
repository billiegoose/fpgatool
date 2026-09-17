# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Exercise Basys 3 LEDs, switches, buttons, and seven-segment display."""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def led_chaser():
    counter: Reg[uint32_t] = 0
    position: Reg[uint4_t] = 0
    direction_right: Reg[uint1_t] = 1

    # Scan the four seven-segment digits at 1 kHz per complete display frame.
    scan_counter: Reg[uint32_t] = 0
    scan_digit: Reg[uint4_t] = 0
    if scan_counter >= (25_000 - 1):
        scan_counter = 0
        if scan_digit == 3:
            scan_digit = 0
        else:
            scan_digit = scan_digit + 1
    else:
        scan_counter = scan_counter + 1

    # The PCB numbers LD0..LD15 from right to left, so the physical direction
    # buttons map oppositely to increasing/decreasing LED numbers.
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

    # Center pauses while held.
    if board.BTNC:
        counter = 0
    elif counter >= (step_cycles - 1):
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

    # Sixteen logical chaser signals. Each switch locally inverts its matching
    # signal; the same signal drives LDn and one pair of seven-segment LEDs.
    s0: uint1_t = (position == 0) ^ board.SW0
    s1: uint1_t = (position == 1) ^ board.SW1
    s2: uint1_t = (position == 2) ^ board.SW2
    s3: uint1_t = (position == 3) ^ board.SW3
    s4: uint1_t = (position == 4) ^ board.SW4
    s5: uint1_t = (position == 5) ^ board.SW5
    s6: uint1_t = (position == 6) ^ board.SW6
    s7: uint1_t = (position == 7) ^ board.SW7
    s8: uint1_t = (position == 8) ^ board.SW8
    s9: uint1_t = (position == 9) ^ board.SW9
    s10: uint1_t = (position == 10) ^ board.SW10
    s11: uint1_t = (position == 11) ^ board.SW11
    s12: uint1_t = (position == 12) ^ board.SW12
    s13: uint1_t = (position == 13) ^ board.SW13
    s14: uint1_t = (position == 14) ^ board.SW14
    s15: uint1_t = (position == 15) ^ board.SW15

    board.LD0 = s0
    board.LD1 = s1
    board.LD2 = s2
    board.LD3 = s3
    board.LD4 = s4
    board.LD5 = s5
    board.LD6 = s6
    board.LD7 = s7
    board.LD8 = s8
    board.LD9 = s9
    board.LD10 = s10
    board.LD11 = s11
    board.LD12 = s12
    board.LD13 = s13
    board.LD14 = s14
    board.LD15 = s15

    # The display is active-low. AN0 is the rightmost digit, matching LD0 at
    # the right edge of the LED bank. Four pairs of segment LEDs live on each
    # digit: CA/CB, CC/CD, CE/CF, and CG/DP.
    board.AN0 = 1
    board.AN1 = 1
    board.AN2 = 1
    board.AN3 = 1
    board.CA = 1
    board.CB = 1
    board.CC = 1
    board.CD = 1
    board.CE = 1
    board.CF = 1
    board.CG = 1
    board.DP = 1

    if scan_digit == 0:
        board.AN0 = 0
        board.CA = ~s0
        board.CB = ~s0
        board.CC = ~s1
        board.CD = ~s1
        board.CE = ~s2
        board.CF = ~s2
        board.CG = ~s3
        board.DP = ~s3
    elif scan_digit == 1:
        board.AN1 = 0
        board.CA = ~s4
        board.CB = ~s4
        board.CC = ~s5
        board.CD = ~s5
        board.CE = ~s6
        board.CF = ~s6
        board.CG = ~s7
        board.DP = ~s7
    elif scan_digit == 2:
        board.AN2 = 0
        board.CA = ~s8
        board.CB = ~s8
        board.CC = ~s9
        board.CD = ~s9
        board.CE = ~s10
        board.CF = ~s10
        board.CG = ~s11
        board.DP = ~s11
    else:
        board.AN3 = 0
        board.CA = ~s12
        board.CB = ~s12
        board.CC = ~s13
        board.CD = ~s13
        board.CE = ~s14
        board.CF = ~s14
        board.CG = ~s15
        board.DP = ~s15
