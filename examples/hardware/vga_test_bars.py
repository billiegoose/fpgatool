# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic VGA test bars and geometry markers."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_12bpp_t
from vga.timing import VgaTimingSpec


def make_vga_test_bars(spec: VgaTimingSpec):
    """Return a test-pattern hw_func specialized to a VGA timing specification.

    Active frame dimensions become elaboration-time constants. Seven bars
    divide the width as evenly as possible. All modes use the same marker
    sizes: 5-pixel-thick, 30-pixel-long corners; 4-pixel-wide, 20-pixel-long
    edge ticks; and a center cross with a 10-pixel radius. Blanking is black,
    and sync signals pass through unchanged.
    """
    FRAME_WIDTH = spec.frame_width
    FRAME_HEIGHT = spec.frame_height
    for name, value in (("frame_width", FRAME_WIDTH), ("frame_height", FRAME_HEIGHT)):
        if type(value) is not int or not 60 <= value <= 4096:
            raise ValueError(f"{name} must be an integer in 60..4096 to fit the markers and VGA position type")

    _CENTER_X = FRAME_WIDTH // 2
    _CENTER_Y = FRAME_HEIGHT // 2
    _CROSS_RADIUS = 10
    _CORNER_LENGTH = 30
    _TICK_LENGTH = 20
    _CORNER_THICKNESS = 5
    # Round each boundary independently so bar widths differ by at most one
    # pixel, rather than assigning every leftover pixel to the final blue bar.
    _BAR_1 = (FRAME_WIDTH + 3) // 7
    _BAR_2 = (FRAME_WIDTH * 2 + 3) // 7
    _BAR_3 = (FRAME_WIDTH * 3 + 3) // 7
    _BAR_4 = (FRAME_WIDTH * 4 + 3) // 7
    _BAR_5 = (FRAME_WIDTH * 5 + 3) // 7
    _BAR_6 = (FRAME_WIDTH * 6 + 3) // 7

    @hw_func
    def test_bars(sig: vga_timing_signals_t) -> vga_12bpp_t:
        r: uint4_t = 0
        g: uint4_t = 0
        b: uint4_t = 0

        if sig.active:
            if sig.pos.x < _BAR_1:
                r = 15
                g = 15
                b = 15
            elif sig.pos.x < _BAR_2:
                r = 15
                g = 15
                b = 0
            elif sig.pos.x < _BAR_3:
                r = 0
                g = 15
                b = 15
            elif sig.pos.x < _BAR_4:
                r = 0
                g = 15
                b = 0
            elif sig.pos.x < _BAR_5:
                r = 15
                g = 0
                b = 15
            elif sig.pos.x < _BAR_6:
                r = 15
                g = 0
                b = 0
            else:
                r = 0
                g = 0
                b = 15

            corner = (
                ((sig.pos.y < _CORNER_THICKNESS) & ((sig.pos.x < _CORNER_LENGTH) | (sig.pos.x >= (FRAME_WIDTH - _CORNER_LENGTH))))
                | (
                    (sig.pos.y >= (FRAME_HEIGHT - _CORNER_THICKNESS))
                    & ((sig.pos.x < _CORNER_LENGTH) | (sig.pos.x >= (FRAME_WIDTH - _CORNER_LENGTH)))
                )
                | (
                    (sig.pos.x < _CORNER_THICKNESS)
                    & ((sig.pos.y < _CORNER_LENGTH) | (sig.pos.y >= (FRAME_HEIGHT - _CORNER_LENGTH)))
                )
                | (
                    (sig.pos.x >= (FRAME_WIDTH - _CORNER_THICKNESS))
                    & ((sig.pos.y < _CORNER_LENGTH) | (sig.pos.y >= (FRAME_HEIGHT - _CORNER_LENGTH)))
                )
            )
            edge_tick = (
                ((sig.pos.x >= (_CENTER_X - 2)) & (sig.pos.x < (_CENTER_X + 2)))
                & ((sig.pos.y < _TICK_LENGTH) | (sig.pos.y >= (FRAME_HEIGHT - _TICK_LENGTH)))
            ) | (
                ((sig.pos.y >= (_CENTER_Y - 2)) & (sig.pos.y < (_CENTER_Y + 2)))
                & ((sig.pos.x < _TICK_LENGTH) | (sig.pos.x >= (FRAME_WIDTH - _TICK_LENGTH)))
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

    return test_bars
