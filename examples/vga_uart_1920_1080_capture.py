"""Simulation harness: ideal 148.5 MHz clock replaces the board MMCM.

Use vga_uart_1920_1080_demo.py for hardware. This harness runs the same UART and VGA
core, with real serial bits driven by fpgatool sim --uart-file.
"""
# pyright: reportInvalidTypeForm=none
from pypeline import *
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.uart as board_uart
from hardware.vga_uart_pixels import uart_text_scanout

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


@MAIN(148.5)
def vga_uart_1920_1080_capture():
    px: Reg[vga_12bpp_t]
    write_vga_pins(px)
    status = uart_text_scanout(board_uart.RsRx)
    px = status.video
    board_uart.RsTx = 1
