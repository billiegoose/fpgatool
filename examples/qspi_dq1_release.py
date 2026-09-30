# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Electrical diagnostic for post-configuration QSPI DQ1 ownership.

Keeps the flash deselected and mirrors QspiDQ1 to LD0.  The board constraint
adds an internal pull-up on DQ1, so LD0 should be on if D19 has actually been
released to ordinary user I/O after FPGA startup.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.leds as board_leds


@MAIN(100.0)
def qspi_dq1_release():
    # Keep the flash completely deselected.  STARTUPE2 is still instantiated so
    # the design exercises the same configuration-resource ownership as the SPI
    # examples, but CCLK remains low.
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(0, 1, board_qspi.QspiDQ1_I)
    board_qspi.QspiDQ0_O = 0
    board_qspi.QspiDQ0_T = 0
    board_qspi.QspiDQ1_O = 0
    board_qspi.QspiDQ1_T = 1
    board_qspi.QspiDQ2_O = 1
    board_qspi.QspiDQ2_T = 0
    board_qspi.QspiDQ3_O = 1
    board_qspi.QspiDQ3_T = 0

    board_leds.LD0 = board_qspi.QspiDQ1_I
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
    board_leds.LD15 = 1
