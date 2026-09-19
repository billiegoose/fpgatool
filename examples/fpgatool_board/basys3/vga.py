# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 built-in 12-bit VGA physical output pins."""

from pypeline import Output, uint1_t

VGA_R0: Output[uint1_t]
VGA_R1: Output[uint1_t]
VGA_R2: Output[uint1_t]
VGA_R3: Output[uint1_t]
VGA_G0: Output[uint1_t]
VGA_G1: Output[uint1_t]
VGA_G2: Output[uint1_t]
VGA_G3: Output[uint1_t]
VGA_B0: Output[uint1_t]
VGA_B1: Output[uint1_t]
VGA_B2: Output[uint1_t]
VGA_B3: Output[uint1_t]
VGA_HS: Output[uint1_t]
VGA_VS: Output[uint1_t]
