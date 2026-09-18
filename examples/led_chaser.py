# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Exercise Basys 3 LEDs, switches, buttons, and seven-segment display."""

from pypeline import *
import board.basys3.part35t
import board.basys3.user_io as board_user


@MAIN(100.0)
def led_chaser():
    counter: Reg[uint32_t] = 0
    position: Reg[uint4_t] = 0
    segment_position: Reg[uint32_t] = 0
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
    if board_user.BTNL:
        direction_right = 1
    if board_user.BTNR:
        direction_right = 0

    # Default: 100 ms/step. Up is temporarily 2x faster; down is 2x slower.
    step_cycles: uint32_t = 10_000_000
    if board_user.BTNU:
        step_cycles = 5_000_000
    if board_user.BTND:
        step_cycles = 20_000_000

    # Center pauses while held. The LED and seven-segment chasers advance on
    # the same tick; 16 LED positions versus 32 segment positions means the
    # segment path takes exactly twice as long to make a complete cycle.
    if board_user.BTNC:
        counter = 0
    elif counter >= (step_cycles - 1):
        counter = 0
        if direction_right:
            if position == 15:
                position = 0
            else:
                position = position + 1
            if segment_position == 31:
                segment_position = 0
            else:
                segment_position = segment_position + 1
        else:
            if position == 0:
                position = 15
            else:
                position = position - 1
            if segment_position == 0:
                segment_position = 31
            else:
                segment_position = segment_position - 1
    else:
        counter = counter + 1

    # LED chaser: each slide switch XORs its matching LED.
    board_user.LD0 = (position == 0) ^ board_user.SW0
    board_user.LD1 = (position == 1) ^ board_user.SW1
    board_user.LD2 = (position == 2) ^ board_user.SW2
    board_user.LD3 = (position == 3) ^ board_user.SW3
    board_user.LD4 = (position == 4) ^ board_user.SW4
    board_user.LD5 = (position == 5) ^ board_user.SW5
    board_user.LD6 = (position == 6) ^ board_user.SW6
    board_user.LD7 = (position == 7) ^ board_user.SW7
    board_user.LD8 = (position == 8) ^ board_user.SW8
    board_user.LD9 = (position == 9) ^ board_user.SW9
    board_user.LD10 = (position == 10) ^ board_user.SW10
    board_user.LD11 = (position == 11) ^ board_user.SW11
    board_user.LD12 = (position == 12) ^ board_user.SW12
    board_user.LD13 = (position == 13) ^ board_user.SW13
    board_user.LD14 = (position == 14) ^ board_user.SW14
    board_user.LD15 = (position == 15) ^ board_user.SW15

    # Seven-segment physical chase path, numbered 0..31:
    #   0..3   top horizontals, left -> right
    #   4..7   middle horizontals, right -> left
    #   8..11  bottom horizontals, left -> right
    #   12..19 lower verticals, right -> left
    #   20..27 upper verticals, left -> right
    #   28..31 decimal points, right -> left
    # Each SWn XORs the two consecutive path positions 2n and 2n+1.
    q0: uint1_t = (segment_position == 0) ^ board_user.SW0
    q1: uint1_t = (segment_position == 1) ^ board_user.SW0
    q2: uint1_t = (segment_position == 2) ^ board_user.SW1
    q3: uint1_t = (segment_position == 3) ^ board_user.SW1
    q4: uint1_t = (segment_position == 4) ^ board_user.SW2
    q5: uint1_t = (segment_position == 5) ^ board_user.SW2
    q6: uint1_t = (segment_position == 6) ^ board_user.SW3
    q7: uint1_t = (segment_position == 7) ^ board_user.SW3
    q8: uint1_t = (segment_position == 8) ^ board_user.SW4
    q9: uint1_t = (segment_position == 9) ^ board_user.SW4
    q10: uint1_t = (segment_position == 10) ^ board_user.SW5
    q11: uint1_t = (segment_position == 11) ^ board_user.SW5
    q12: uint1_t = (segment_position == 12) ^ board_user.SW6
    q13: uint1_t = (segment_position == 13) ^ board_user.SW6
    q14: uint1_t = (segment_position == 14) ^ board_user.SW7
    q15: uint1_t = (segment_position == 15) ^ board_user.SW7
    q16: uint1_t = (segment_position == 16) ^ board_user.SW8
    q17: uint1_t = (segment_position == 17) ^ board_user.SW8
    q18: uint1_t = (segment_position == 18) ^ board_user.SW9
    q19: uint1_t = (segment_position == 19) ^ board_user.SW9
    q20: uint1_t = (segment_position == 20) ^ board_user.SW10
    q21: uint1_t = (segment_position == 21) ^ board_user.SW10
    q22: uint1_t = (segment_position == 22) ^ board_user.SW11
    q23: uint1_t = (segment_position == 23) ^ board_user.SW11
    q24: uint1_t = (segment_position == 24) ^ board_user.SW12
    q25: uint1_t = (segment_position == 25) ^ board_user.SW12
    q26: uint1_t = (segment_position == 26) ^ board_user.SW13
    q27: uint1_t = (segment_position == 27) ^ board_user.SW13
    q28: uint1_t = (segment_position == 28) ^ board_user.SW14
    q29: uint1_t = (segment_position == 29) ^ board_user.SW14
    q30: uint1_t = (segment_position == 30) ^ board_user.SW15
    q31: uint1_t = (segment_position == 31) ^ board_user.SW15

    # Active-low multiplexed display. AN0 is the rightmost digit and AN3 the
    # leftmost digit. Map the numbered path above onto the physical segments.
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

    if scan_digit == 0:
        board_user.AN0 = 0
        board_user.CA = ~q3
        board_user.CB = ~q27
        board_user.CC = ~q12
        board_user.CD = ~q11
        board_user.CE = ~q13
        board_user.CF = ~q26
        board_user.CG = ~q4
        board_user.DP = ~q28
    elif scan_digit == 1:
        board_user.AN1 = 0
        board_user.CA = ~q2
        board_user.CB = ~q25
        board_user.CC = ~q14
        board_user.CD = ~q10
        board_user.CE = ~q15
        board_user.CF = ~q24
        board_user.CG = ~q5
        board_user.DP = ~q29
    elif scan_digit == 2:
        board_user.AN2 = 0
        board_user.CA = ~q1
        board_user.CB = ~q23
        board_user.CC = ~q16
        board_user.CD = ~q9
        board_user.CE = ~q17
        board_user.CF = ~q22
        board_user.CG = ~q6
        board_user.DP = ~q30
    else:
        board_user.AN3 = 0
        board_user.CA = ~q0
        board_user.CB = ~q21
        board_user.CC = ~q18
        board_user.CD = ~q8
        board_user.CE = ~q19
        board_user.CF = ~q20
        board_user.CG = ~q7
        board_user.DP = ~q31
