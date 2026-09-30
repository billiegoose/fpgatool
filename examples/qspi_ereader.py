# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""The world's worst e-reader: four characters of QSPI-backed text at a time."""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.QSPI as qspi_flash
import hardware.buttons as button_hw


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



_TEXT_SECTOR_ADDRESS = 0x3E0000
_TEXT_DATA_ADDRESS = _TEXT_SECTOR_ADDRESS + 6
_TEXT_MAX_LENGTH = 65530
_MAGIC = 0x45524452  # ASCII ERDR

_ST_HEADER_READY = 0
_ST_HEADER_LAUNCH = 1
_ST_HEADER_WAIT = 2
_ST_READY = 3
_ST_WINDOW_READY = 4
_ST_WINDOW_LAUNCH = 5
_ST_WINDOW_WAIT = 6


@struct
class qspi_text_window_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq0_t: uint1_t
    dq1: uint1_t
    dq1_t: uint1_t
    dq2: uint1_t
    dq2_t: uint1_t
    dq3: uint1_t
    dq3_t: uint1_t
    char0: uint8_t
    char1: uint8_t
    char2: uint8_t
    char3: uint8_t
    position: uint16_t
    length: uint16_t
    valid: uint1_t
    busy: uint1_t
    error: uint1_t
    quad_enabled: uint1_t
    quad_activity: uint1_t


@hw_func
def read_text_window(dq: uint4_t, move_left: uint1_t, move_right: uint1_t) -> qspi_text_window_t:
    state: Reg[uint3_t] = _ST_HEADER_READY
    byte_index: Reg[uint3_t] = 0

    header_magic: Reg[uint32_t] = 0
    header_length_hi: Reg[uint8_t] = 0
    position: Reg[uint16_t] = 0
    length: Reg[uint16_t] = 0
    char0: Reg[uint8_t] = 32
    char1: Reg[uint8_t] = 32
    char2: Reg[uint8_t] = 32
    char3: Reg[uint8_t] = 32
    valid: Reg[uint1_t] = 0
    error: Reg[uint1_t] = 0

    op: uint2_t = qspi_flash.FLASH_OP_NONE
    address: uint32_t = uint32_t(_TEXT_SECTOR_ADDRESS)

    if state == _ST_HEADER_LAUNCH:
        op = qspi_flash.FLASH_OP_READ
        address = uint32_t(_TEXT_SECTOR_ADDRESS) + byte_index
    elif state == _ST_WINDOW_LAUNCH:
        op = qspi_flash.FLASH_OP_READ
        address = uint32_t(_TEXT_DATA_ADDRESS) + position + byte_index

    flash = qspi_flash.flash_byte_io(dq, op, address, uint8_t(0))

    if state == _ST_HEADER_READY:
        if flash.ready:
            state = _ST_HEADER_LAUNCH

    elif state == _ST_HEADER_LAUNCH:
        state = _ST_HEADER_WAIT

    elif state == _ST_HEADER_WAIT:
        if flash.done:
            if byte_index < 4:
                header_magic = (header_magic << 8) | flash.read_data
                byte_index = byte_index + 1
                state = _ST_HEADER_READY
            elif byte_index == 4:
                header_length_hi = flash.read_data
                byte_index = 5
                state = _ST_HEADER_READY
            else:
                header_length: uint16_t = concat(header_length_hi, flash.read_data)
                if header_magic == _MAGIC and header_length > 0 and header_length <= _TEXT_MAX_LENGTH:
                    length = header_length
                    position = 0
                    valid = 1
                    error = 0
                    byte_index = 0
                    state = _ST_WINDOW_READY
                else:
                    valid = 0
                    error = 1
                    byte_index = 0
                    state = _ST_READY

    elif state == _ST_READY:
        if valid:
            max_position: uint16_t = 0
            if length > 4:
                max_position = length - 4
            if move_left and position > 0:
                position = position - 1
                byte_index = 0
                state = _ST_WINDOW_READY
            elif move_right and position < max_position:
                position = position + 1
                byte_index = 0
                state = _ST_WINDOW_READY

    elif state == _ST_WINDOW_READY:
        if flash.ready:
            state = _ST_WINDOW_LAUNCH

    elif state == _ST_WINDOW_LAUNCH:
        state = _ST_WINDOW_WAIT

    elif state == _ST_WINDOW_WAIT:
        if flash.done:
            if byte_index == 0:
                char0 = flash.read_data
                byte_index = 1
                state = _ST_WINDOW_READY
            elif byte_index == 1:
                char1 = flash.read_data
                byte_index = 2
                state = _ST_WINDOW_READY
            elif byte_index == 2:
                char2 = flash.read_data
                byte_index = 3
                state = _ST_WINDOW_READY
            else:
                char3 = flash.read_data
                byte_index = 0
                state = _ST_READY

    busy: uint1_t = state != _ST_READY
    return qspi_text_window_t(
        cclk=flash.cclk,
        cs_n=flash.cs_n,
        dq0=flash.dq0,
        dq0_t=flash.dq0_t,
        dq1=flash.dq1,
        dq1_t=flash.dq1_t,
        dq2=flash.dq2,
        dq2_t=flash.dq2_t,
        dq3=flash.dq3,
        dq3_t=flash.dq3_t,
        char0=char0,
        char1=char1,
        char2=char2,
        char3=char3,
        position=position,
        length=length,
        valid=valid,
        busy=busy,
        error=error,
        quad_enabled=flash.quad_enabled,
        quad_activity=flash.quad_activity,
    )


@MAIN(100.0)
def qspi_ereader():
    scan: Reg[uint18_t] = 0

    left_button = button_hw.debounce_button(board_buttons.BTNL)
    right_button = button_hw.debounce_button(board_buttons.BTNR)

    dq: uint4_t = concat(
        board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
        board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I
    )
    page = read_text_window(dq, left_button.pressed, right_button.pressed)

    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(page.cclk, page.cs_n, not page.busy)
    board_qspi.QspiDQ0_O = page.dq0
    board_qspi.QspiDQ0_T = page.dq0_t
    board_qspi.QspiDQ1_O = page.dq1
    board_qspi.QspiDQ1_T = page.dq1_t
    board_qspi.QspiDQ2_O = page.dq2
    board_qspi.QspiDQ2_T = page.dq2_t
    board_qspi.QspiDQ3_O = page.dq3
    board_qspi.QspiDQ3_T = page.dq3_t

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
    board_leds.LD11 = page.busy
    # Hardware proof indicators:
    #   LD15 = the flash Configuration Register reports QUAD enabled.
    #   LD12 = sticky flag set only after a 4-bit QSPI payload nibble was sampled.
    board_leds.LD12 = page.quad_activity
    board_leds.LD13 = page.error
    board_leds.LD14 = page.valid
    board_leds.LD15 = page.quad_enabled
