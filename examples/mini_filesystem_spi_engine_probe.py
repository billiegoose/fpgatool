# pyright: reportInvalidTypeForm=none
"""Read-only diagnostic: initialized QSPI byte engine plus resident JTAG bridge."""
from pypeline import *
from hardware.QSPI import flash_byte_io
from hardware.live_flash import live_flash_application_t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.live_flash as board_live_flash
import fpgatool_board.basys3.leds as board_leds


@MAIN(100.0)
def mini_filesystem_spi_engine_probe():
    dq: uint4_t = concat(board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
                         board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)
    application = flash_byte_io(dq, uint2_t(0), uint32_t(0), uint8_t(0), uint1_t(0))
    selected = board_live_flash.proxy(
        application,
        live_flash_application_t(ready=application.ready, busy=0,
                                 quiescent=application.ready,
                                 done=0, error=application.error),
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
    board_leds.LD0 = application.ready
    board_leds.LD1 = selected.control.granted
    board_leds.LD2 = application.error
    board_leds.LD3 = application.quad_enabled
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
