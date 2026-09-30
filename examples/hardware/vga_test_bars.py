# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic SMPTE-style VGA test bars and geometry markers."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_12bpp_t


_CENTER_X = 320
_CENTER_Y = 240
_CROSS_RADIUS = 8


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

        center_cross = (
            ((sig.pos.x == _CENTER_X)
             & (sig.pos.y >= (_CENTER_Y - _CROSS_RADIUS))
             & (sig.pos.y <= (_CENTER_Y + _CROSS_RADIUS)))
            | ((sig.pos.y == _CENTER_Y)
               & (sig.pos.x >= (_CENTER_X - _CROSS_RADIUS))
               & (sig.pos.x <= (_CENTER_X + _CROSS_RADIUS)))
        )

        if corner | edge_tick | center_cross:
            r = 0
            g = 0
            b = 0

    return vga_12bpp_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)
