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

    # Center pauses while held. The LED and seven-segment chasers advance on
    # the same tick; 16 LED positions versus 32 segment positions means the
    # segment path takes exactly twice as long to make a complete cycle.
    if board.BTNC:
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

    # Seven-segment physical chase path, numbered 0..31:
    #   0..3   top horizontals, left -> right
    #   4..7   middle horizontals, right -> left
    #   8..11  bottom horizontals, left -> right
    #   12..19 lower verticals, right -> left
    #   20..27 upper verticals, left -> right
    #   28..31 decimal points, right -> left
    # Each SWn XORs the two consecutive path positions 2n and 2n+1.
    q0: uint1_t = (segment_position == 0) ^ board.SW0
    q1: uint1_t = (segment_position == 1) ^ board.SW0
    q2: uint1_t = (segment_position == 2) ^ board.SW1
    q3: uint1_t = (segment_position == 3) ^ board.SW1
    q4: uint1_t = (segment_position == 4) ^ board.SW2
    q5: uint1_t = (segment_position == 5) ^ board.SW2
    q6: uint1_t = (segment_position == 6) ^ board.SW3
    q7: uint1_t = (segment_position == 7) ^ board.SW3
    q8: uint1_t = (segment_position == 8) ^ board.SW4
    q9: uint1_t = (segment_position == 9) ^ board.SW4
    q10: uint1_t = (segment_position == 10) ^ board.SW5
    q11: uint1_t = (segment_position == 11) ^ board.SW5
    q12: uint1_t = (segment_position == 12) ^ board.SW6
    q13: uint1_t = (segment_position == 13) ^ board.SW6
    q14: uint1_t = (segment_position == 14) ^ board.SW7
    q15: uint1_t = (segment_position == 15) ^ board.SW7
    q16: uint1_t = (segment_position == 16) ^ board.SW8
    q17: uint1_t = (segment_position == 17) ^ board.SW8
    q18: uint1_t = (segment_position == 18) ^ board.SW9
    q19: uint1_t = (segment_position == 19) ^ board.SW9
    q20: uint1_t = (segment_position == 20) ^ board.SW10
    q21: uint1_t = (segment_position == 21) ^ board.SW10
    q22: uint1_t = (segment_position == 22) ^ board.SW11
    q23: uint1_t = (segment_position == 23) ^ board.SW11
    q24: uint1_t = (segment_position == 24) ^ board.SW12
    q25: uint1_t = (segment_position == 25) ^ board.SW12
    q26: uint1_t = (segment_position == 26) ^ board.SW13
    q27: uint1_t = (segment_position == 27) ^ board.SW13
    q28: uint1_t = (segment_position == 28) ^ board.SW14
    q29: uint1_t = (segment_position == 29) ^ board.SW14
    q30: uint1_t = (segment_position == 30) ^ board.SW15
    q31: uint1_t = (segment_position == 31) ^ board.SW15

    # Active-low multiplexed display. AN0 is the rightmost digit and AN3 the
    # leftmost digit. Map the numbered path above onto the physical segments.
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
        board.CA = ~q3
        board.CB = ~q27
        board.CC = ~q12
        board.CD = ~q11
        board.CE = ~q13
        board.CF = ~q26
        board.CG = ~q4
        board.DP = ~q28
    elif scan_digit == 1:
        board.AN1 = 0
        board.CA = ~q2
        board.CB = ~q25
        board.CC = ~q14
        board.CD = ~q10
        board.CE = ~q15
        board.CF = ~q24
        board.CG = ~q5
        board.DP = ~q29
    elif scan_digit == 2:
        board.AN2 = 0
        board.CA = ~q1
        board.CB = ~q23
        board.CC = ~q16
        board.CD = ~q9
        board.CE = ~q17
        board.CF = ~q22
        board.CG = ~q6
        board.DP = ~q30
    else:
        board.AN3 = 0
        board.CA = ~q0
        board.CB = ~q21
        board.CC = ~q18
        board.CD = ~q8
        board.CE = ~q19
        board.CF = ~q20
        board.CG = ~q7
        board.DP = ~q31
