# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 USB-UART bridge pins."""

from pypeline import Input, Output, uint1_t

# Host -> FPGA and FPGA -> host respectively.
RsRx: Input[uint1_t]
RsTx: Output[uint1_t]
