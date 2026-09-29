# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Basys 3 persistent-number demo using the configuration flash.

On boot the four-digit decimal value is read from a reserved 64 KiB block at
the end of the 32-Mbit configuration flash. BTNU increments, BTND decrements,
and BTNC saves the current value. The save path erases only that reserved user
block, page-programs a small checked record, and reads it back for verification.

Program this demo itself persistently once, save a number with BTNC, then power
cycle/reset the board: the number is loaded from flash again at startup.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.qspi_flash_rw as qspi_rw


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
    else:
        segments = 127
    return segments


def _bcd_increment(value: uint16_t) -> uint16_t:
    ones: uint4_t = value[3:0]
    tens: uint4_t = value[7:4]
    hundreds: uint4_t = value[11:8]
    thousands: uint4_t = value[15:12]
    result: uint16_t = value
    if value != 0x9999:
        if ones < 9:
            ones = ones + 1
        else:
            ones = 0
            if tens < 9:
                tens = tens + 1
            else:
                tens = 0
                if hundreds < 9:
                    hundreds = hundreds + 1
                else:
                    hundreds = 0
                    thousands = thousands + 1
        result = concat(thousands, hundreds, tens, ones)
    return result


def _bcd_decrement(value: uint16_t) -> uint16_t:
    ones: uint4_t = value[3:0]
    tens: uint4_t = value[7:4]
    hundreds: uint4_t = value[11:8]
    thousands: uint4_t = value[15:12]
    result: uint16_t = value
    if value != 0:
        if ones > 0:
            ones = ones - 1
        else:
            ones = 9
            if tens > 0:
                tens = tens - 1
            else:
                tens = 9
                if hundreds > 0:
                    hundreds = hundreds - 1
                else:
                    hundreds = 9
                    thousands = thousands - 1
        result = concat(thousands, hundreds, tens, ones)
    return result


@MAIN(100.0)
def qspi_flash_rw():
    display_value: Reg[uint16_t] = 0
    boot_loaded: Reg[uint1_t] = 0

    up_prev: Reg[uint1_t] = 0
    down_prev: Reg[uint1_t] = 0
    center_prev: Reg[uint1_t] = 0
    debounce: Reg[uint22_t] = 0

    up_event: uint1_t = 0
    down_event: uint1_t = 0
    save_event: uint1_t = 0

    if debounce > 0:
        debounce = debounce - 1
    else:
        if board_buttons.BTNU and not up_prev:
            up_event = 1
            debounce = 2_000_000
        elif board_buttons.BTND and not down_prev:
            down_event = 1
            debounce = 2_000_000
        elif board_buttons.BTNC and not center_prev:
            save_event = 1
            debounce = 2_000_000

    up_prev = board_buttons.BTNU
    down_prev = board_buttons.BTND
    center_prev = board_buttons.BTNC

    flash = qspi_rw.persistent_bcd_store(board_qspi.QspiDQ1, save_event, display_value)

    # USRCCLKTS is active-high. Keep CCLK enabled while the flash controller is
    # busy and tri-state it when idle; importantly, this is a routed fabric
    # signal rather than a constant so OpenXC7 cannot discard the connection.
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(
        flash.cclk, flash.cs_n, not flash.busy
    )
    board_qspi.QspiDQ0 = flash.dq0
    board_qspi.QspiDQ2 = flash.dq2
    board_qspi.QspiDQ3 = flash.dq3

    if not boot_loaded and not flash.busy:
        if flash.valid:
            display_value = flash.value_bcd
        else:
            display_value = 0
        boot_loaded = 1
    elif boot_loaded and not flash.busy:
        if up_event:
            display_value = _bcd_increment(display_value)
        elif down_event:
            display_value = _bcd_decrement(display_value)

    # LD15 = flash busy, LD14 = saved record valid, LD13 = last save failed.
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
    board_leds.LD13 = flash.save_error
    board_leds.LD14 = flash.valid
    board_leds.LD15 = flash.busy

    scan_counter: Reg[uint16_t] = 0
    scan_counter = scan_counter + 1
    digit: uint2_t = scan_counter[15:14]

    nibble: uint4_t = display_value[3:0]
    if digit == 1:
        nibble = display_value[7:4]
    elif digit == 2:
        nibble = display_value[11:8]
    elif digit == 3:
        nibble = display_value[15:12]

    segments: uint7_t = _hex_segments(nibble)
    board_seven_segment.AN0 = 1
    board_seven_segment.AN1 = 1
    board_seven_segment.AN2 = 1
    board_seven_segment.AN3 = 1
    if boot_loaded:
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
