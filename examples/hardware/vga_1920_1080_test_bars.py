# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic SMPTE-style VGA test bars and geometry markers."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_12bpp_t

_FRAME_WIDTH = 1920
_FRAME_HEIGHT = 1080
_CENTER_X = _FRAME_WIDTH // 2
_CENTER_Y = _FRAME_HEIGHT // 2
_CROSS_RADIUS = 10

_BAR_WIDTH = _FRAME_WIDTH // 7


@hw_func
def test_bars(sig: vga_timing_signals_t) -> vga_12bpp_t:
    r: uint4_t = 0
    g: uint4_t = 0
    b: uint4_t = 0

    if sig.active:
        if sig.pos.x < (_BAR_WIDTH * 1):
            r = 15
            g = 15
            b = 15
        elif sig.pos.x < (_BAR_WIDTH * 2):
            r = 15
            g = 15
            b = 0
        elif sig.pos.x < (_BAR_WIDTH * 3):
            r = 0
            g = 15
            b = 15
        elif sig.pos.x < (_BAR_WIDTH * 4):
            r = 0
            g = 15
            b = 0
        elif sig.pos.x < (_BAR_WIDTH * 5):
            r = 15
            g = 0
            b = 15
        elif sig.pos.x < (_BAR_WIDTH * 6):
            r = 15
            g = 0
            b = 0
        else:
            r = 0
            g = 0
            b = 15

        corner = (
            ((sig.pos.y < 5) & ((sig.pos.x < 30) | (sig.pos.x >= (_FRAME_WIDTH - 30))))
            | (
                (sig.pos.y >= (_FRAME_HEIGHT - 5))
                & ((sig.pos.x < 30) | (sig.pos.x >= (_FRAME_WIDTH - 30)))
            )
            | (
                (sig.pos.x < 5)
                & ((sig.pos.y < 30) | (sig.pos.y >= (_FRAME_HEIGHT - 30)))
            )
            | (
                (sig.pos.x >= (_FRAME_WIDTH - 5))
                & ((sig.pos.y < 30) | (sig.pos.y >= (_FRAME_HEIGHT - 30)))
            )
        )
        edge_tick = (
            ((sig.pos.x >= (_CENTER_X - 2)) & (sig.pos.x < (_CENTER_X + 2)))
            & ((sig.pos.y < 20) | (sig.pos.y >= (_FRAME_HEIGHT - 20)))
        ) | (
            ((sig.pos.y >= (_CENTER_Y - 2)) & (sig.pos.y < (_CENTER_Y + 2)))
            & ((sig.pos.x < 20) | (sig.pos.x >= (_FRAME_WIDTH - 20)))
        )

        center_cross = (
            (sig.pos.x == _CENTER_X)
            & (sig.pos.y >= (_CENTER_Y - _CROSS_RADIUS))
            & (sig.pos.y <= (_CENTER_Y + _CROSS_RADIUS))
        ) | (
            (sig.pos.y == _CENTER_Y)
            & (sig.pos.x >= (_CENTER_X - _CROSS_RADIUS))
            & (sig.pos.x <= (_CENTER_X + _CROSS_RADIUS))
        )

        if corner | edge_tick | center_cross:
            r = 0
            g = 0
            b = 0

    return vga_12bpp_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)
