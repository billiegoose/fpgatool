# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 USB-UART bridge pins.

Use this narrow board module for reusable serial transports so importing UART
support does not also declare unrelated LEDs, switches, buttons, or seven-segment
outputs from `fpgatool_board.basys3.io`.
"""

from pypeline import Input, Output, uint1_t

# PCB / Digilent constraint names: host -> FPGA and FPGA -> host respectively.
RsRx: Input[uint1_t]
RsTx: Output[uint1_t]
