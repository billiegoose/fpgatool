# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 pushbutton pins using PCB labels."""

from pypeline import Input, uint1_t

BTNC: Input[uint1_t]
BTNU: Input[uint1_t]
BTNL: Input[uint1_t]
BTNR: Input[uint1_t]
BTND: Input[uint1_t]
