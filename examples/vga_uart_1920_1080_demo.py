"""Basys 3 UART -> RED2 text, 1920x1080 VGA at 60 Hz.

115200 baud, 8-N-1. LF starts a new line; CR and unsupported characters are
ignored. Backspace (08) and Delete (7F) remove the last buffered byte.
Text wraps at the right margin; an 8 KiB byte buffer feeds a 64-bit compositor and a small pixel FIFO.
"""
# pyright: reportInvalidTypeForm=none
from pypeline import *
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.uart as board_uart
from hardware.vga_uart_pixels import uart_text_scanout
from hardware.uart_diagnostics import uart_diagnostics
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
from hardware.xilinx7_clock import MmcmStage, make_mmcm_clock, synchronize_clock_lock

# Hardware-verified integer chain: 100 -> 135 -> 148.5 MHz.
_clock_generator = make_mmcm_clock(100.0, MmcmStage(27, 4, 5), MmcmStage(11, 2, 5))
pixel_clock: Wire[uint1_t] = make_clock(148.5)
pixel_locked: AsyncWire[uint1_t]

@hw_func
def write_vga_pins(px: vga_12bpp_t):
    board_vga.VGA_R0 = px.r[0]
    board_vga.VGA_R1 = px.r[1]
    board_vga.VGA_R2 = px.r[2]
    board_vga.VGA_R3 = px.r[3]
    board_vga.VGA_G0 = px.g[0]
    board_vga.VGA_G1 = px.g[1]
    board_vga.VGA_G2 = px.g[2]
    board_vga.VGA_G3 = px.g[3]
    board_vga.VGA_B0 = px.b[0]
    board_vga.VGA_B1 = px.b[1]
    board_vga.VGA_B2 = px.b[2]
    board_vga.VGA_B3 = px.b[3]
    board_vga.VGA_HS = px.hs
    board_vga.VGA_VS = px.vs


@MAIN(100.0)
def vga_uart_clock():
    signals = _clock_generator(0)
    pixel_clock = signals.clock
    pixel_locked = signals.locked


@MAIN(148.5)
def vga_uart_1920_1080_demo():
    px: Reg[vga_12bpp_t]
    write_vga_pins(px)
    locked = synchronize_clock_lock(pixel_locked)
    status = uart_text_scanout(board_uart.RsRx)
    if locked:
        px = status.video
    diag = uart_diagnostics(board_uart.RsRx, locked, status.received,
                            status.committed, status.full)
    board_uart.RsTx = 1
    board_leds.LD0 = diag.leds[0]
    board_leds.LD1 = diag.leds[1]
    board_leds.LD2 = diag.leds[2]
    board_leds.LD3 = diag.leds[3]
    board_leds.LD4 = diag.leds[4]
    board_leds.LD5 = diag.leds[5]
    board_leds.LD6 = diag.leds[6]
    board_leds.LD7 = diag.leds[7]
    board_leds.LD8 = diag.leds[8]
    board_leds.LD9 = diag.leds[9]
    board_leds.LD10 = diag.leds[10]
    board_leds.LD11 = diag.leds[11]
    board_leds.LD12 = diag.leds[12]
    board_leds.LD13 = diag.leds[13]
    board_leds.LD14 = diag.leds[14]
    board_leds.LD15 = diag.leds[15]
    board_seven_segment.AN0 = diag.anodes[0]
    board_seven_segment.AN1 = diag.anodes[1]
    board_seven_segment.AN2 = diag.anodes[2]
    board_seven_segment.AN3 = diag.anodes[3]
    board_seven_segment.CA = diag.segments[0]
    board_seven_segment.CB = diag.segments[1]
    board_seven_segment.CC = diag.segments[2]
    board_seven_segment.CD = diag.segments[3]
    board_seven_segment.CE = diag.segments[4]
    board_seven_segment.CF = diag.segments[5]
    board_seven_segment.CG = diag.segments[6]
    board_seven_segment.DP = ~status.underflow
