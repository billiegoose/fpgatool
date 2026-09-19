# pyright: reportInvalidTypeForm=none
"""Thin Basys 3 adapter for the board-agnostic PS/2 mouse hardware."""

from pypeline import *
import hardware.ps2_mouse as hw


# The PIC24 USB host bridge exposes PS/2 clock/data on these two physical pins.
# OpenDrain values are drive intents: 0 pulls low, 1 releases the line.
PS2Clk: OpenDrain[uint1_t]
PS2Data: OpenDrain[uint1_t]

mouse: Wire[hw.ps2_mouse_t]


@MAIN(100.0)
def ps2_mouse_io():
    link = hw.ps2_mouse(PS2Clk, PS2Data)

    PS2Clk = link.clk_release
    PS2Data = link.data_release

    mouse = hw.ps2_mouse_t(
        x=link.x,
        y=link.y,
        left=link.left,
        middle=link.middle,
        right=link.right,
        wheel=link.wheel,
        wheel_mode=link.wheel_mode,
        ready=link.ready,
    )
