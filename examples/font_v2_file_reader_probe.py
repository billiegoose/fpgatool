# pyright: reportInvalidTypeForm=none
"""Timing-only file-reader core at 170 MHz (14.5% above the 148.5 MHz requirement).

The normal font loader includes the shared QSPI initializer. This probe isolates
the new lookup/streaming core and omits flash setup and STARTUPE2 clock priming.
"""
from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.leds as board_leds
from hardware.mini_filesystem import make_file_reader
from hardware.xilinx7_clock import MmcmStage, make_mmcm_clock, synchronize_clock_lock

_clock = make_mmcm_clock(100.0, MmcmStage(17, 2, 5))
clock_170: Wire[uint1_t] = make_clock(170.0)
clock_locked: AsyncWire[uint1_t]
_file = make_file_reader('RED2-Regular-v2.bin', initialize_flash=False)


@MAIN(100.0)
def file_probe_clock():
    clocks = _clock(0)
    clock_170 = clocks.clock
    clock_locked = clocks.locked


@MAIN(170.0)
def font_v2_file_reader_probe():
    locked = synchronize_clock_lock(clock_locked)
    started: Reg[uint1_t] = 0
    read: Reg[uint1_t] = 0
    dq: uint4_t = concat(board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
                         board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)
    file = _file(dq, locked & (~started), read, uint24_t(0), uint13_t(4256), uint1_t(0))
    started = locked
    read = file.opened & (~file.busy) & (~read) & (~file.error)
    flash = file.flash
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(flash.cclk, flash.cs_n, not flash.busy)
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = flash.dq0_t
    board_qspi.QspiDQ1_O = flash.dq1
    board_qspi.QspiDQ1_T = flash.dq1_t
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = flash.dq2_t
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = flash.dq3_t
    board_leds.LD0 = file.opened
    board_leds.LD1 = file.busy
    board_leds.LD2 = file.error
    board_leds.LD3 = file.valid
    board_leds.LD4 = file.done
    board_leds.LD5 = locked
    board_leds.LD6 = file.object_type[0]
    board_leds.LD7 = file.object_type[1]
    board_leds.LD8 = file.data[0]
    board_leds.LD9 = file.data[1]
    board_leds.LD10 = file.data[2]
    board_leds.LD11 = file.data[3]
    board_leds.LD12 = file.data[4]
    board_leds.LD13 = file.data[5]
    board_leds.LD14 = file.data[6]
    board_leds.LD15 = file.data[7]
