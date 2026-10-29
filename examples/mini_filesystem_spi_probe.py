# pyright: reportInvalidTypeForm=none
"""Temporary hardware diagnostic: USER1/USER2 flash bridge with an idle application."""
from pypeline import *
from hardware.QSPI import qspi_flash_byte_io_t
from hardware.live_flash import live_flash_application_t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.live_flash as board_live_flash
import fpgatool_board.basys3.leds as board_leds


@MAIN(100.0)
def mini_filesystem_spi_probe():
    dq: uint4_t = concat(board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
                         board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)
    selected = board_live_flash.proxy(
        qspi_flash_byte_io_t(
            cclk=0, cs_n=1, dq0=0, dq0_t=1,
            dq1=1, dq1_t=1, dq2=1, dq2_t=1, dq3=1, dq3_t=1,
            read_data=0, ready=1, busy=0, done=0, error=0,
            quad_enabled=0, quad_activity=0, quad_write_activity=0),
        live_flash_application_t(ready=1, busy=0, quiescent=1,
                                 done=0, error=0),
        dq[1])
    flash = selected.flash
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(
        flash.cclk, flash.cs_n, not flash.busy)
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = flash.dq0_t
    board_qspi.QspiDQ1_O = flash.dq1
    board_qspi.QspiDQ1_T = flash.dq1_t
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = flash.dq2_t
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = flash.dq3_t
    board_leds.LD0 = selected.control.granted
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
    board_leds.LD13 = 0
    board_leds.LD14 = 0
    board_leds.LD15 = 0
