# pyright: reportInvalidTypeForm=none
"""640x480 VGA test bars and geometry markers on the Basys 3."""

from pypeline import *
import board.basys3.part35t
import board.basys3.vga as board_vga
import hardware.vga_timing as timing
import hardware.vga_test_bars as bars


@MAIN(100.0)
def vga_test_bars():
    sig = timing.vga_timing_25mhz_from_100mhz()
    board_vga.vga = bars.test_bars(sig)
