# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 basic board I/O for Pypeline designs.

Names follow the labels printed on the PCB: LD0..LD15, SW0..SW15, and BTNC/BTNU/BTNL/BTNR/BTND.
"""

from pypeline import Input, Output, uint1_t


# User LEDs, labeled LD0..LD15 on the PCB.
LD0: Output[uint1_t]
LD1: Output[uint1_t]
LD2: Output[uint1_t]
LD3: Output[uint1_t]
LD4: Output[uint1_t]
LD5: Output[uint1_t]
LD6: Output[uint1_t]
LD7: Output[uint1_t]
LD8: Output[uint1_t]
LD9: Output[uint1_t]
LD10: Output[uint1_t]
LD11: Output[uint1_t]
LD12: Output[uint1_t]
LD13: Output[uint1_t]
LD14: Output[uint1_t]
LD15: Output[uint1_t]

# Slide switches, labeled SW0..SW15 on the PCB.
SW0: Input[uint1_t]
SW1: Input[uint1_t]
SW2: Input[uint1_t]
SW3: Input[uint1_t]
SW4: Input[uint1_t]
SW5: Input[uint1_t]
SW6: Input[uint1_t]
SW7: Input[uint1_t]
SW8: Input[uint1_t]
SW9: Input[uint1_t]
SW10: Input[uint1_t]
SW11: Input[uint1_t]
SW12: Input[uint1_t]
SW13: Input[uint1_t]
SW14: Input[uint1_t]
SW15: Input[uint1_t]

# Pushbuttons, using the PCB labels.
BTNC: Input[uint1_t]
BTNU: Input[uint1_t]
BTNL: Input[uint1_t]
BTNR: Input[uint1_t]
BTND: Input[uint1_t]

# Four-digit seven-segment display. All of these signals are active-low.
AN0: Output[uint1_t]
AN1: Output[uint1_t]
AN2: Output[uint1_t]
AN3: Output[uint1_t]
CA: Output[uint1_t]
CB: Output[uint1_t]
CC: Output[uint1_t]
CD: Output[uint1_t]
CE: Output[uint1_t]
CF: Output[uint1_t]
CG: Output[uint1_t]
DP: Output[uint1_t]

# USB-UART bridge signals, using Digilent's Basys 3 signal names.
# RsRx is data from the host into the FPGA; RsTx is data from the FPGA to the host.
RsRx: Input[uint1_t]
RsTx: Output[uint1_t]
