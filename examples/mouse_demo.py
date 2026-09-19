# pyright: reportInvalidTypeForm=none
"""Basys 3 PS/2 mouse cursor diagnostic on a plain black VGA background."""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.ps2_mouse as board_mouse
import hardware.vga_timing as timing
import hardware.mouse_cursor as cursor


@MAIN(100.0)
def mouse_demo():
    sig = timing.vga_timing_25mhz_from_100mhz()
    bg = cursor.black_background(sig)
    mouse = board_mouse.mouse
    board_vga.vga = cursor.overlay_cursor(
        sig,
        bg,
        mouse.x,
        mouse.y,
        mouse.left,
        mouse.middle,
        mouse.right,
        mouse.wheel,
        mouse.wheel_mode,
    )
