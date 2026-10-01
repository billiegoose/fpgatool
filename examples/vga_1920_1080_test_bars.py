# pyright: reportInvalidTypeForm=none
"""1920x1080 VGA test bars and geometry markers on the Basys 3."""

from pypeline import *
from vga.types import vga_12bpp_t
from vga.timing import make_vga_timing, VGA_1920_1080
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.clock_148p5
import fpgatool_board.basys3.vga as board_vga
import hardware.vga_1920_1080_test_bars as bars

vga_timing = make_vga_timing(VGA_1920_1080)


@hw_func
def write_vga_pins(px: vga_12bpp_t):
    board_vga.VGA_R0 = px.r[0]
    board_vga.VGA_R1 = px.r[1]
    board_vga.VGA_R2 = px.r[2]
    board_vga.VGA_R3 = px.r[3]
    board_vga.VGA_G0 = px.g[0]
    board_vga.VGA_G1 = px.g[1]
    board_vga.VGA_G2 = px.g[2]
    board_vga.VGA_G3 = px.g[3]
    board_vga.VGA_B0 = px.b[0]
    board_vga.VGA_B1 = px.b[1]
    board_vga.VGA_B2 = px.b[2]
    board_vga.VGA_B3 = px.b[3]
    board_vga.VGA_HS = px.hs
    board_vga.VGA_VS = px.vs


@MAIN(vga_timing.pixel_clk_mhz)
def vga_1920_1080_test_bars():
    px: Reg[vga_12bpp_t]

    sig = vga_timing()
    px = bars.test_bars(sig)
    write_vga_pins(px)
