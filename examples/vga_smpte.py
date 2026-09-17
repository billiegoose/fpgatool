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
    """Classic seven vertical bars: white, yellow, cyan, green, magenta, red, blue."""
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

    return vga_12bpp_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)


@MAIN(100.0)
def vga_smpte():
    sig = vga_timing_25mhz_from_100mhz()
    board_vga.vga = smpte_bars(sig)
