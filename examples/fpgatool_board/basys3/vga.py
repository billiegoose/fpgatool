# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 built-in 12-bit VGA output.

The board has a resistor DAC driven by four FPGA bits per colour channel plus
horizontal and vertical sync.  Applications write a vga_12bpp_t to `vga`.
"""

from pypeline import *
from vga.types import vga_12bpp_t



# Application-facing VGA stream.
vga: Wire[vga_12bpp_t]

# PCB schematic/net labels used by Digilent's master constraints.
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


@MAIN
def vga_to_pins():
    # Register the output once, matching the existing Arty VGA adapters.
    px: Reg[vga_12bpp_t]
    VGA_R0 = px.r[0]
    VGA_R1 = px.r[1]
    VGA_R2 = px.r[2]
    VGA_R3 = px.r[3]
    VGA_G0 = px.g[0]
    VGA_G1 = px.g[1]
    VGA_G2 = px.g[2]
    VGA_G3 = px.g[3]
    VGA_B0 = px.b[0]
    VGA_B1 = px.b[1]
    VGA_B2 = px.b[2]
    VGA_B3 = px.b[3]
    VGA_HS = px.hs
    VGA_VS = px.vs
    px = vga
