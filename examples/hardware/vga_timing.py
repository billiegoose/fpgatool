# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic 640x480 VGA timing at 25 MHz from a 100 MHz clock."""

from pypeline import *
from vga.types import vga_timing_signals_t, vga_pos_t


@hw_func
def vga_timing_25mhz_from_100mhz() -> vga_timing_signals_t:
    pixel_phase: Reg[uint2_t] = 0
    h_cntr: Reg[uint10_t] = 0
    v_cntr: Reg[uint10_t] = 0

    pos = vga_pos_t(x=h_cntr, y=v_cntr)
    active = (h_cntr < 640) & (v_cntr < 480)
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
