# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic SMPTE-style VGA test bars and geometry markers."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_12bpp_t


@hw_func
def test_bars(sig: vga_timing_signals_t) -> vga_12bpp_t:
    r: uint4_t = 0
    g: uint4_t = 0
    b: uint4_t = 0

    if sig.active:
        if sig.pos.x < 91:
            r = 15
            g = 15
            b = 15
        elif sig.pos.x < 183:
            r = 15
            g = 15
            b = 0
        elif sig.pos.x < 274:
            r = 0
            g = 15
            b = 15
        elif sig.pos.x < 366:
            r = 0
            g = 15
            b = 0
        elif sig.pos.x < 457:
            r = 15
            g = 0
            b = 15
        elif sig.pos.x < 549:
            r = 15
            g = 0
            b = 0
        else:
            r = 0
            g = 0
            b = 15

        corner = (
            ((sig.pos.y < 4) & ((sig.pos.x < 24) | (sig.pos.x >= 616)))
            | ((sig.pos.y >= 476) & ((sig.pos.x < 24) | (sig.pos.x >= 616)))
            | ((sig.pos.x < 4) & ((sig.pos.y < 24) | (sig.pos.y >= 456)))
            | ((sig.pos.x >= 636) & ((sig.pos.y < 24) | (sig.pos.y >= 456)))
        )
        edge_tick = (
            (((sig.pos.x >= 318) & (sig.pos.x < 322)) & ((sig.pos.y < 16) | (sig.pos.y >= 464)))
            | (((sig.pos.y >= 238) & (sig.pos.y < 242)) & ((sig.pos.x < 16) | (sig.pos.x >= 624)))
        )

        circle_xmax: uint6_t[61] = [
            60, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59,
            58, 58, 58, 58, 58, 57, 57, 57, 56, 56, 56, 55,
            55, 54, 54, 54, 53, 53, 52, 51, 51, 50, 50, 49,
            48, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38,
            37, 36, 34, 33, 31, 29, 28, 26, 23, 21, 18, 15,
            10, 0,
        ]
        dx: uint10_t = 0
        dy: uint10_t = 0
        if sig.pos.x >= 320:
            dx = sig.pos.x - 320
        else:
            dx = 320 - sig.pos.x
        if sig.pos.y >= 240:
            dy = sig.pos.y - 240
        else:
            dy = 240 - sig.pos.y
        center_circle: uint1_t = 0
        if dy <= 60:
            center_circle = dx <= circle_xmax[dy[5:0]]

        if corner | edge_tick | center_circle:
            r = 0
            g = 0
            b = 0

    return vga_12bpp_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)
