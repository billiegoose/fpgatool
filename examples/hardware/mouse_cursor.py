# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic VGA mouse cursor renderer."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_12bpp_t


@hw_func
def black_background(sig: vga_timing_signals_t) -> vga_12bpp_t:
    return vga_12bpp_t(r=0, g=0, b=0, hs=sig.hsync, vs=sig.vsync)


@hw_func
def overlay_cursor(
    sig: vga_timing_signals_t,
    bg: vga_12bpp_t,
    mouse_x: uint10_t,
    mouse_y: uint9_t,
    mouse_left: uint1_t,
    mouse_middle: uint1_t,
    mouse_right: uint1_t,
    mouse_wheel: uint8_t,
    mouse_wheel_mode: uint1_t,
) -> vga_12bpp_t:
    r: uint4_t = bg.r
    g: uint4_t = bg.g
    b: uint4_t = bg.b

    if sig.active:
        cursor_x: uint10_t = mouse_x
        cursor_y: uint9_t = mouse_y
        if cursor_x > 637:
            cursor_x = 637
        if cursor_y == 0:
            cursor_y = 1

        dx: uint10_t = 0
        dy: uint10_t = 0
        if sig.pos.x >= cursor_x:
            dx = sig.pos.x - cursor_x
        else:
            dx = cursor_x - sig.pos.x
        if sig.pos.y >= cursor_y:
            dy = sig.pos.y - cursor_y
        else:
            dy = cursor_y - sig.pos.y

        outline = (((dx <= 1) & (dy <= 7)) | ((dy <= 1) & (dx <= 7)))
        core = (((dx == 0) & (dy <= 6)) | ((dy == 0) & (dx <= 6)))

        if outline:
            r = 0
            g = 0
            b = 0
        if core:
            any_button: uint1_t = mouse_left | mouse_middle | mouse_right
            if any_button:
                r = 15 if mouse_left else 0
                g = 15 if mouse_middle else 0
                b = 15 if mouse_right else 0
            else:
                r = 15
                g = 15
                b = 15

        wheel_phase: uint2_t = mouse_wheel[1:0]
        if mouse_wheel_mode & (dx == 0) & (dy == wheel_phase):
            r = 0
            g = 0
            b = 0

    return vga_12bpp_t(r=r, g=g, b=b, hs=bg.hs, vs=bg.vs)
