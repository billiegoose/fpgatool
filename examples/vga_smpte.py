# pyright: reportInvalidTypeForm=none
"""640x480 SMPTE-style colour bars on the Basys 3 built-in VGA connector.

Run with::

    ./fpgatool.sh run examples/vga_smpte.py --comb

The Basys 3 provides a 100 MHz oscillator. VGA pixels advance once every four
board clocks, yielding the 25 MHz pixel rate used by 640x480 VGA timing.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.vga as board_vga
import board.basys3.ps2_mouse as board_mouse
from vga.types import vga_timing_signals_t, vga_12bpp_t, vga_pos_t


@hw_func
def vga_timing_25mhz_from_100mhz() -> vga_timing_signals_t:
    """640x480 timing with each pixel held for four 100 MHz board clocks."""
    pixel_phase: Reg[uint2_t] = 0
    h_cntr: Reg[uint10_t] = 0
    v_cntr: Reg[uint10_t] = 0

    pos = vga_pos_t(x=h_cntr, y=v_cntr)
    active = (h_cntr < 640) & (v_cntr < 480)
    # 640x480 VGA sync pulses are active-low.
    hsync = ~((h_cntr >= 656) & (h_cntr < 752))
    vsync = ~((v_cntr >= 490) & (v_cntr < 492))
    start_of_frame = (h_cntr == 0) & (v_cntr == 0)
    end_of_frame = (h_cntr == 799) & (v_cntr == 524)

    if pixel_phase == 3:
        pixel_phase = 0
        if h_cntr == 799:
            h_cntr = 0
            if v_cntr == 524:
                v_cntr = 0
            else:
                v_cntr = v_cntr + 1
        else:
            h_cntr = h_cntr + 1
    else:
        pixel_phase = pixel_phase + 1

    return vga_timing_signals_t(
        pos=pos,
        hsync=hsync,
        vsync=vsync,
        active=active,
        start_of_frame=start_of_frame,
        end_of_frame=end_of_frame,
    )


def smpte_bars(sig: vga_timing_signals_t) -> vga_12bpp_t:
    """Seven colour bars with active-area alignment markers at the screen edges."""
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

        # Black alignment marks touch the exact 640x480 active-area edges.
        # If a display overscans or our porch/sync timing is shifted, these
        # strokes will be clipped or displaced asymmetrically.
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

        # Exact radius-60 filled circle without a per-pixel multiplier chain.
        # For each |y-240| row, this table is floor(sqrt(60^2-dy^2)); the
        # predicate therefore selects exactly the same integer pixels as
        # dx*dx + dy*dy <= 3600, but maps to a lookup/mux plus compare.
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


def mouse_crosshair(
    sig: vga_timing_signals_t,
    bg: vga_12bpp_t,
    mouse: board_mouse.ps2_mouse_t,
) -> vga_12bpp_t:
    """Overlay a small outlined cursor; mouse buttons select additive RGB colour."""
    r: uint4_t = bg.r
    g: uint4_t = bg.g
    b: uint4_t = bg.b

    if sig.active:
        # Keep the logical mouse range at the full 640x480, but compensate for
        # the empirically visible raster edge: the crosshair looked one pixel too
        # high at the top and two pixels too far right on the physical monitor.
        cursor_x: uint10_t = mouse.x
        cursor_y: uint9_t = mouse.y
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

        # One-pixel black border around a 13-pixel coloured plus sign.  Keeping
        # the outline separate makes the cursor visible on every SMPTE bar and
        # over the black geometry diagnostic at screen centre.
        outline = (((dx <= 1) & (dy <= 7)) | ((dy <= 1) & (dx <= 7)))
        core = (((dx == 0) & (dy <= 6)) | ((dy == 0) & (dx <= 6)))

        if outline:
            r = 0
            g = 0
            b = 0
        if core:
            # No button: white.  Held buttons map directly to RGB channels, so
            # combinations naturally produce yellow/cyan/magenta/white.
            any_button: uint1_t = mouse.left | mouse.middle | mouse.right
            if any_button:
                r = 15 if mouse.left else 0
                g = 15 if mouse.middle else 0
                b = 15 if mouse.right else 0
            else:
                r = 15
                g = 15
                b = 15

        # Wheel mode adds a tiny black notch on the vertical cursor arm.  Its
        # distance from the centre cycles with the cumulative wheel position, so
        # each detent is persistent and visible even though PS/2 packets are brief.
        wheel_phase: uint2_t = mouse.wheel[1:0]
        if mouse.wheel_mode & (dx == 0) & (dy == wheel_phase):
            r = 0
            g = 0
            b = 0

    return vga_12bpp_t(r=r, g=g, b=b, hs=bg.hs, vs=bg.vs)


@MAIN(100.0)
def vga_smpte():
    sig = vga_timing_25mhz_from_100mhz()
    bg = smpte_bars(sig)
    board_vga.vga = mouse_crosshair(sig, bg, board_mouse.mouse)
