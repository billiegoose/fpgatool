# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Read the Basys 3 configuration flash JEDEC ID without modifying flash.

The demo issues only the standard 0x9F Read JEDEC ID command in single-bit SPI
mode.  After the read completes:

* LD0..LD7 show the manufacturer byte, least-significant bit first;
* LD8..LD15 show the memory-type byte, least-significant bit first;
* the right two seven-segment digits show the capacity byte in hexadecimal;
* the left two seven-segment digits show the manufacturer byte in hexadecimal.

This makes the three returned bytes directly observable without UART or any
host-side software.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.SPI as qspi_flash


def _hex_segments(value: uint4_t) -> uint7_t:
    # Active-low Basys 3 segments, returned as abcdefg packed into uint7_t.
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
def qspi_flash_id():
    flash = qspi_flash.read_jedec_id(board_qspi.QspiDQ1_I)

    # Keep CCLK enabled during the transaction and tri-state it after ready.
    # The non-constant TS signal is required by the current OpenXC7 flow.
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

    board_leds.LD0 = flash.manufacturer_id[0]
    board_leds.LD1 = flash.manufacturer_id[1]
    board_leds.LD2 = flash.manufacturer_id[2]
    board_leds.LD3 = flash.manufacturer_id[3]
    board_leds.LD4 = flash.manufacturer_id[4]
    board_leds.LD5 = flash.manufacturer_id[5]
    board_leds.LD6 = flash.manufacturer_id[6]
    board_leds.LD7 = flash.manufacturer_id[7]
    board_leds.LD8 = flash.memory_type[0]
    board_leds.LD9 = flash.memory_type[1]
    board_leds.LD10 = flash.memory_type[2]
    board_leds.LD11 = flash.memory_type[3]
    board_leds.LD12 = flash.memory_type[4]
    board_leds.LD13 = flash.memory_type[5]
    board_leds.LD14 = flash.memory_type[6]
    board_leds.LD15 = flash.memory_type[7]

    scan_counter: Reg[uint16_t] = 0
    scan_counter = scan_counter + 1
    digit: uint2_t = scan_counter[15:14]

    nibble: uint4_t = flash.capacity[3:0]
    if digit == 1:
        nibble = flash.capacity[7:4]
    elif digit == 2:
        nibble = flash.manufacturer_id[3:0]
    elif digit == 3:
        nibble = flash.manufacturer_id[7:4]

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

    # Lookup constants use the conventional active-low gfedcba encoding:
    # bit 0 is segment A and bit 6 is segment G.
    board_seven_segment.CA = segments[0]
    board_seven_segment.CB = segments[1]
    board_seven_segment.CC = segments[2]
    board_seven_segment.CD = segments[3]
    board_seven_segment.CE = segments[4]
    board_seven_segment.CF = segments[5]
    board_seven_segment.CG = segments[6]
    board_seven_segment.DP = 1
