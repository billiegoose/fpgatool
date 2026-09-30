# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Basys 3 persistent-number demo using single-bit SPI flash access.

On boot the four-digit decimal value is read from a reserved 64 KiB block at
the end of the 32-Mbit configuration flash. BTNU increments, BTND decrements,
and BTNC saves the current value. The save path erases only that reserved user
block, programs a four-byte checked record through the generic flash interface,
and verifies each programmed byte.

Program this demo itself persistently once, save a number with BTNC, then power
cycle/reset the board: the number is loaded from flash again at startup.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.SPI as spi_flash
import hardware.buttons as button_hw

_button = button_hw.make_button()


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



_USER_BLOCK_ADDRESS = 0x3F0000
_MAGIC = 0xA5
_CHECK_SALT = 0x5A

_ST_BOOT_READY = 0
_ST_BOOT_LAUNCH = 1
_ST_BOOT_WAIT = 2
_ST_READY = 3
_ST_ERASE_READY = 4
_ST_ERASE_LAUNCH = 5
_ST_ERASE_WAIT = 6
_ST_PROGRAM_READY = 7
_ST_PROGRAM_LAUNCH = 8
_ST_PROGRAM_WAIT = 9


@struct
class spi_flash_store_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    value_bcd: uint16_t
    valid: uint1_t
    busy: uint1_t
    save_done: uint1_t
    save_error: uint1_t


@hw_func
def persistent_bcd_store(
    dq1: uint1_t, save: uint1_t, value_to_save: uint16_t
) -> spi_flash_store_t:
    state: Reg[uint4_t] = _ST_BOOT_READY
    byte_index: Reg[uint3_t] = 0

    boot_magic: Reg[uint8_t] = 0
    boot_hi: Reg[uint8_t] = 0
    boot_lo: Reg[uint8_t] = 0
    stored_value: Reg[uint16_t] = 0
    stored_valid: Reg[uint1_t] = 0
    requested_value: Reg[uint16_t] = 0
    save_done: Reg[uint1_t] = 0
    save_error: Reg[uint1_t] = 0

    save_done = 0

    op: uint2_t = spi_flash.FLASH_OP_NONE
    address: uint32_t = uint32_t(_USER_BLOCK_ADDRESS)
    write_data: uint8_t = 0

    if state == _ST_BOOT_LAUNCH:
        op = spi_flash.FLASH_OP_READ
        address = uint32_t(_USER_BLOCK_ADDRESS) + byte_index
    elif state == _ST_ERASE_LAUNCH:
        op = spi_flash.FLASH_OP_ERASE_BLOCK
    elif state == _ST_PROGRAM_LAUNCH:
        op = spi_flash.FLASH_OP_PROGRAM
        address = uint32_t(_USER_BLOCK_ADDRESS) + byte_index
        value_hi: uint8_t = requested_value[15:8]
        value_lo: uint8_t = requested_value[7:0]
        check: uint8_t = uint8_t(_MAGIC) ^ value_hi ^ value_lo ^ uint8_t(_CHECK_SALT)
        if byte_index == 0:
            write_data = uint8_t(_MAGIC)
        elif byte_index == 1:
            write_data = value_hi
        elif byte_index == 2:
            write_data = value_lo
        else:
            write_data = check

    flash = spi_flash.flash_byte_io(dq1, op, address, write_data)

    if state == _ST_BOOT_READY:
        if flash.ready:
            state = _ST_BOOT_LAUNCH

    elif state == _ST_BOOT_LAUNCH:
        # flash was observed ready on the previous clock, so this one-cycle
        # request is guaranteed to be sampled.
        state = _ST_BOOT_WAIT

    elif state == _ST_BOOT_WAIT:
        if flash.done:
            if byte_index == 0:
                boot_magic = flash.read_data
                byte_index = 1
                state = _ST_BOOT_READY
            elif byte_index == 1:
                boot_hi = flash.read_data
                byte_index = 2
                state = _ST_BOOT_READY
            elif byte_index == 2:
                boot_lo = flash.read_data
                byte_index = 3
                state = _ST_BOOT_READY
            else:
                expected: uint8_t = uint8_t(_MAGIC) ^ boot_hi ^ boot_lo ^ uint8_t(_CHECK_SALT)
                value: uint16_t = concat(boot_hi, boot_lo)
                bcd_valid: uint1_t = 1
                if boot_hi[7:4] > 9:
                    bcd_valid = 0
                elif boot_hi[3:0] > 9:
                    bcd_valid = 0
                elif boot_lo[7:4] > 9:
                    bcd_valid = 0
                elif boot_lo[3:0] > 9:
                    bcd_valid = 0
                if boot_magic == _MAGIC and flash.read_data == expected and bcd_valid:
                    stored_value = value
                    stored_valid = 1
                else:
                    stored_value = 0
                    stored_valid = 0
                byte_index = 0
                state = _ST_READY

    elif state == _ST_READY:
        if save:
            requested_value = value_to_save
            save_error = 0
            byte_index = 0
            state = _ST_ERASE_READY

    elif state == _ST_ERASE_READY:
        if flash.ready:
            state = _ST_ERASE_LAUNCH

    elif state == _ST_ERASE_LAUNCH:
        state = _ST_ERASE_WAIT

    elif state == _ST_ERASE_WAIT:
        if flash.done:
            if flash.error:
                save_error = 1
                save_done = 1
                state = _ST_READY
            else:
                byte_index = 0
                state = _ST_PROGRAM_READY

    elif state == _ST_PROGRAM_READY:
        if flash.ready:
            state = _ST_PROGRAM_LAUNCH

    elif state == _ST_PROGRAM_LAUNCH:
        state = _ST_PROGRAM_WAIT

    elif state == _ST_PROGRAM_WAIT:
        if flash.done:
            if flash.error:
                save_error = 1
                save_done = 1
                state = _ST_READY
            elif byte_index < 3:
                byte_index = byte_index + 1
                state = _ST_PROGRAM_READY
            else:
                stored_value = requested_value
                stored_valid = 1
                save_error = 0
                save_done = 1
                byte_index = 0
                state = _ST_READY

    busy: uint1_t = 1
    if state == _ST_READY:
        busy = 0

    return spi_flash_store_t(
        cclk=flash.cclk,
        cs_n=flash.cs_n,
        dq0=flash.dq0,
        dq2=flash.dq2,
        dq3=flash.dq3,
        value_bcd=stored_value,
        valid=stored_valid,
        busy=busy,
        save_done=save_done,
        save_error=save_error,
    )


@MAIN(100.0)
def flash_spi_write():
    display_value: Reg[uint16_t] = 0
    boot_loaded: Reg[uint1_t] = 0

    up_button = _button(board_buttons.BTNU)
    down_button = _button(board_buttons.BTND)
    center_button = _button(board_buttons.BTNC)

    flash = persistent_bcd_store(
        board_qspi.QspiDQ1_I, center_button.pressed, display_value
    )

    # USRCCLKTS is active-high. Keep CCLK enabled while the flash controller is
    # busy and tri-state it when idle; importantly, this is a routed fabric
    # signal rather than a constant so OpenXC7 cannot discard the connection.
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(
        flash.cclk, flash.cs_n, not flash.busy
    )
    # Standard SPI: IO0 is MOSI, IO1 is MISO, IO2/IO3 stay high.
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = 0
    board_qspi.QspiDQ1_O = 0
    board_qspi.QspiDQ1_T = 1
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = 0
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = 0

    if not boot_loaded and not flash.busy:
        if flash.valid:
            display_value = flash.value_bcd
        else:
            display_value = 0
        boot_loaded = 1
    elif boot_loaded and not flash.busy:
        if up_button.pressed:
            display_value = _bcd_increment(display_value)
        elif down_button.pressed:
            display_value = _bcd_decrement(display_value)

    # LD14 = saved record valid, LD13 = save/readback error, LD11 = busy.
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
    board_leds.LD11 = flash.busy
    board_leds.LD12 = 0
    board_leds.LD13 = flash.save_error
    board_leds.LD14 = flash.valid
    board_leds.LD15 = 0

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
