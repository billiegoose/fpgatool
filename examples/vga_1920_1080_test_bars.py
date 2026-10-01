# pyright: reportInvalidTypeForm=none
"""1920x1080 VGA test bars and geometry markers on the Basys 3."""

from pypeline import *
from vga.types import vga_12bpp_t
from vga.timing import make_vga_timing, VGA_1920_1080
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import hardware.vga_test_bars as bars
from hardware.xilinx7_clock import MmcmStage, make_mmcm_clock, synchronize_clock_lock

vga_timing = make_vga_timing(VGA_1920_1080)
_test_bars = bars.make_vga_test_bars(VGA_1920_1080)
# Hardware-verified integer chain: 100 -> 135 -> 148.5 MHz.
_pixel_clock_generator = make_mmcm_clock(100.0, MmcmStage(27, 4, 5), MmcmStage(11, 2, 5))
assert _pixel_clock_generator.output_mhz == vga_timing.pixel_clk_mhz
pixel_clock: Wire[uint1_t] = make_clock(_pixel_clock_generator.output_mhz)
pixel_locked: AsyncWire[uint1_t]


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


@MAIN(100.0)
def vga_pixel_clock():
    signals = _pixel_clock_generator(0)
    pixel_clock = signals.clock
    pixel_locked = signals.locked


@MAIN(vga_timing.pixel_clk_mhz)
def vga_1920_1080_test_bars():
    px: Reg[vga_12bpp_t]

    if synchronize_clock_lock(pixel_locked):
        sig = vga_timing()
        px = _test_bars(sig)
    write_vga_pins(px)
