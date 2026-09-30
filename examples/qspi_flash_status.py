# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Non-destructive configuration-flash status/WREN diagnostic.

The display shows BBAA in hexadecimal: BB is RDSR before WREN and AA is RDSR
after WREN.  LD15 lights when the diagnostic is complete.  LD0..LD7 mirror the
after-WREN status byte.  No erase or page-program command is issued.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.SPI as qspi_flash


def _hex_segments(value: uint4_t) -> uint7_t:
    segments: uint7_t = 127
    if value == 0:
        segments = 64
    elif value == 1:
        segments = 121
    elif value == 2:
        segments = 36
    elif value == 3:
        segments = 48
    elif value == 4:
        segments = 25
    elif value == 5:
        segments = 18
    elif value == 6:
        segments = 2
    elif value == 7:
        segments = 120
    elif value == 8:
        segments = 0
    elif value == 9:
        segments = 16
    elif value == 10:
        segments = 8
    elif value == 11:
        segments = 3
    elif value == 12:
        segments = 70
    elif value == 13:
        segments = 33
    elif value == 14:
        segments = 6
    else:
        segments = 14
    return segments


@MAIN(100.0)
def qspi_flash_status():
    flash = qspi_flash.read_status_and_test_wren(board_qspi.QspiDQ1_I)

    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(
        flash.cclk, flash.cs_n, flash.ready
    )
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = 0
    board_qspi.QspiDQ1_O = 0
    board_qspi.QspiDQ1_T = 1
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = 0
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = 0

    board_leds.LD0 = flash.status_after[0]
    board_leds.LD1 = flash.status_after[1]
    board_leds.LD2 = flash.status_after[2]
    board_leds.LD3 = flash.status_after[3]
    board_leds.LD4 = flash.status_after[4]
    board_leds.LD5 = flash.status_after[5]
    board_leds.LD6 = flash.status_after[6]
    board_leds.LD7 = flash.status_after[7]
    board_leds.LD8 = 0
    board_leds.LD9 = 0
    board_leds.LD10 = 0
    board_leds.LD11 = 0
    board_leds.LD12 = 0
    board_leds.LD13 = 0
    board_leds.LD14 = 0
    board_leds.LD15 = flash.ready

    scan_counter: Reg[uint16_t] = 0
    scan_counter = scan_counter + 1
    digit: uint2_t = scan_counter[15:14]

    nibble: uint4_t = flash.status_after[3:0]
    if digit == 1:
        nibble = flash.status_after[7:4]
    elif digit == 2:
        nibble = flash.status_before[3:0]
    elif digit == 3:
        nibble = flash.status_before[7:4]

    segments: uint7_t = _hex_segments(nibble)

    board_seven_segment.AN0 = 1
    board_seven_segment.AN1 = 1
    board_seven_segment.AN2 = 1
    board_seven_segment.AN3 = 1
    if flash.ready:
        if digit == 0:
            board_seven_segment.AN0 = 0
        elif digit == 1:
            board_seven_segment.AN1 = 0
        elif digit == 2:
            board_seven_segment.AN2 = 0
        else:
            board_seven_segment.AN3 = 0

    board_seven_segment.CA = segments[0]
    board_seven_segment.CB = segments[1]
    board_seven_segment.CC = segments[2]
    board_seven_segment.CD = segments[3]
    board_seven_segment.CE = segments[4]
    board_seven_segment.CF = segments[5]
    board_seven_segment.CG = segments[6]
    board_seven_segment.DP = 1
