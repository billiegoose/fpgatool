# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 PS/2 physical clock/data pins."""

from pypeline import OpenDrain, uint1_t

# OpenDrain values are drive intents: 0 pulls low, 1 releases the line.
PS2Clk: OpenDrain[uint1_t]
PS2Data: OpenDrain[uint1_t]
