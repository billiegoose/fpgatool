# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 four-digit seven-segment display pins (active low)."""

from pypeline import Output, uint1_t

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
