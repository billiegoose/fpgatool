# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""The world's worst e-reader: four characters of QSPI-backed text at a time."""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.qspi_text_reader as text_reader


def _glyph(ch: uint8_t) -> uint7_t:
    # Active-low abcdefg. Lower-case-looking approximations are intentional for
    # letters that a seven-segment display cannot represent cleanly.
    s: uint7_t = 127
    if ch == 32: s = 127       # space
    elif ch == 45: s = 63      # -
    elif ch == 48: s = 64
    elif ch == 49: s = 121
    elif ch == 50: s = 36
    elif ch == 51: s = 48
    elif ch == 52: s = 25
    elif ch == 53: s = 18
    elif ch == 54: s = 2
    elif ch == 55: s = 120
    elif ch == 56: s = 0
    elif ch == 57: s = 16
    elif ch == 65: s = 8       # A
    elif ch == 66: s = 3       # b
    elif ch == 67: s = 70      # C
    elif ch == 68: s = 33      # d
    elif ch == 69: s = 6       # E
    elif ch == 70: s = 14      # F
    elif ch == 71: s = 66      # G
    elif ch == 72: s = 9       # H
    elif ch == 73: s = 121     # I
    elif ch == 74: s = 97      # J
    elif ch == 75: s = 10      # K-ish
    elif ch == 76: s = 71      # L
    elif ch == 77: s = 42      # M-ish
    elif ch == 78: s = 43      # n
    elif ch == 79: s = 64      # O
    elif ch == 80: s = 12      # P
    elif ch == 81: s = 24      # q
    elif ch == 82: s = 47      # r
    elif ch == 83: s = 18      # S
    elif ch == 84: s = 7       # t
    elif ch == 85: s = 65      # U
    elif ch == 86: s = 99      # V-ish
    elif ch == 87: s = 85      # W-ish
    elif ch == 88: s = 9       # X-ish
    elif ch == 89: s = 17      # Y
    elif ch == 90: s = 36      # Z
    elif ch == 63: s = 44      # ?
    return s


@MAIN(100.0)
def qspi_ereader():
    # Debounce each physical button into a stable state, then publish a
    # registered one-cycle pulse only when that stable state changes to
    # pressed.  The reader consumes the *current* pulse registers before we
    # compute their next values below, avoiding a combinational button/event
    # path into the stateful QSPI reader.
    left_stable: Reg[uint1_t] = 0
    right_stable: Reg[uint1_t] = 0
    left_count: Reg[uint21_t] = 0
    right_count: Reg[uint21_t] = 0
    left_event: Reg[uint1_t] = 0
    right_event: Reg[uint1_t] = 0
    scan: Reg[uint18_t] = 0

    page = text_reader.read_text_window(board_qspi.QspiDQ1, left_event, right_event)

    left_now: uint1_t = board_buttons.BTNL
    right_now: uint1_t = board_buttons.BTNR

    # Pulses are one clock wide.  A newly confirmed press is therefore seen
    # by read_text_window on the following clock, after which it is cleared.
    left_event = 0
    right_event = 0

    if left_now == left_stable:
        left_count = 0
    elif left_count >= 1_999_999:
        left_count = 0
        left_stable = left_now
        if left_now:
            left_event = 1
    else:
        left_count = left_count + 1

    if right_now == right_stable:
        right_count = 0
    elif right_count >= 1_999_999:
        right_count = 0
        right_stable = right_now
        if right_now:
            right_event = 1
    else:
        right_count = right_count + 1

    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(page.cclk, page.cs_n, not page.busy)
    board_qspi.QspiDQ0 = page.dq0
    board_qspi.QspiDQ2 = page.dq2
    board_qspi.QspiDQ3 = page.dq3

    scan = scan + 1
    digit: uint2_t = scan[17:16]
    seg: uint7_t = 127
    an: uint4_t = 15
    if digit == 0:
        seg = _glyph(page.char3)
        an = 14
    elif digit == 1:
        seg = _glyph(page.char2)
        an = 13
    elif digit == 2:
        seg = _glyph(page.char1)
        an = 11
    else:
        seg = _glyph(page.char0)
        an = 7

    # Glyph constants use the same active-low gfedcba encoding as the other
    # Basys 3 examples: bit 0 drives segment A and bit 6 drives segment G.
    board_seven_segment.CA = seg[0]
    board_seven_segment.CB = seg[1]
    board_seven_segment.CC = seg[2]
    board_seven_segment.CD = seg[3]
    board_seven_segment.CE = seg[4]
    board_seven_segment.CF = seg[5]
    board_seven_segment.CG = seg[6]
    board_seven_segment.DP = 1
    board_seven_segment.AN0 = an[0]
    board_seven_segment.AN1 = an[1]
    board_seven_segment.AN2 = an[2]
    board_seven_segment.AN3 = an[3]

    board_leds.LD0 = 0
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
    board_leds.LD13 = page.error
    board_leds.LD14 = page.valid
    board_leds.LD15 = page.busy
