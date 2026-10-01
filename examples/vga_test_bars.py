# pyright: reportInvalidTypeForm=none
"""640x480 VGA test bars and geometry markers on the Basys 3."""

from pypeline import *
from vga.types import vga_12bpp_t
from vga.timing import make_vga_timing, VGA_640_480
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import hardware.vga_test_bars as bars


vga_timing = make_vga_timing(VGA_640_480)
_test_bars = bars.make_vga_test_bars(VGA_640_480)
_MAIN_CLK_MHZ = 100.0
_PIXEL_DIV = int(_MAIN_CLK_MHZ / vga_timing.pixel_clk_mhz)
if _MAIN_CLK_MHZ != (_PIXEL_DIV * vga_timing.pixel_clk_mhz):
    raise ValueError("VGA pixel clock must divide the demo MAIN clock exactly")
_pixel_phase_t = make_uint_t(max(1, (_PIXEL_DIV - 1).bit_length()))


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


@MAIN(_MAIN_CLK_MHZ)
def vga_test_bars():
    pixel_phase: Reg[_pixel_phase_t] = 0
    px: Reg[vga_12bpp_t]

    if pixel_phase == (_PIXEL_DIV - 1):
        pixel_phase = 0
        sig = vga_timing()
        px = _test_bars(sig)
    else:
        pixel_phase = pixel_phase + 1

    write_vga_pins(px)
