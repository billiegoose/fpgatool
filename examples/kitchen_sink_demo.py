# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Basys 3 kitchen-sink demo composed from reusable hardware blocks.

Exercises user I/O, USB-UART echo, VGA test bars, and the PS/2 mouse cursor
simultaneously. Top-level examples own pins; reusable logic lives under
`examples/hardware/`.
"""

from pypeline import *
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.switches as board_switches
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.seven_segment as board_seven_segment
import fpgatool_board.basys3.uart as board_uart
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.ps2 as board_ps2
import hardware.led_chaser as led_hw
import hardware.uart as uart_hw
import hardware.vga_timing as vga_timing
import hardware.vga_test_bars as vga_bars
import hardware.mouse_cursor as mouse_cursor
import hardware.ps2_mouse as ps2_mouse_hw


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
def kitchen_sink_demo():
    user = led_hw.led_chaser(
        board_switches.SW0, board_switches.SW1, board_switches.SW2, board_switches.SW3,
        board_switches.SW4, board_switches.SW5, board_switches.SW6, board_switches.SW7,
        board_switches.SW8, board_switches.SW9, board_switches.SW10, board_switches.SW11,
        board_switches.SW12, board_switches.SW13, board_switches.SW14, board_switches.SW15,
        board_buttons.BTNL, board_buttons.BTNR, board_buttons.BTNU,
        board_buttons.BTND, board_buttons.BTNC,
    )

    board_leds.LD0 = user.ld0
    board_leds.LD1 = user.ld1
    board_leds.LD2 = user.ld2
    board_leds.LD3 = user.ld3
    board_leds.LD4 = user.ld4
    board_leds.LD5 = user.ld5
    board_leds.LD6 = user.ld6
    board_leds.LD7 = user.ld7
    board_leds.LD8 = user.ld8
    board_leds.LD9 = user.ld9
    board_leds.LD10 = user.ld10
    board_leds.LD11 = user.ld11
    board_leds.LD12 = user.ld12
    board_leds.LD13 = user.ld13
    board_leds.LD14 = user.ld14
    board_leds.LD15 = user.ld15

    board_seven_segment.AN0 = user.an0
    board_seven_segment.AN1 = user.an1
    board_seven_segment.AN2 = user.an2
    board_seven_segment.AN3 = user.an3
    board_seven_segment.CA = user.ca
    board_seven_segment.CB = user.cb
    board_seven_segment.CC = user.cc
    board_seven_segment.CD = user.cd
    board_seven_segment.CE = user.ce
    board_seven_segment.CF = user.cf
    board_seven_segment.CG = user.cg
    board_seven_segment.DP = user.dp

    uart = uart_hw.uart_echo(board_uart.RsRx, uint8_t(0), uint8_t(0))
    board_uart.RsTx = uart.tx

    sig = vga_timing.vga_timing_25mhz_from_100mhz()
    bg = vga_bars.test_bars(sig)

    mouse = ps2_mouse_hw.ps2_mouse(board_ps2.PS2Clk_I, board_ps2.PS2Data_I)
    board_ps2.PS2Clk_T = mouse.clk_release
    board_ps2.PS2Data_T = mouse.data_release

    write_vga_pins(mouse_cursor.overlay_cursor(
        sig,
        bg,
        mouse.x,
        mouse.y,
        mouse.left,
        mouse.middle,
        mouse.right,
        mouse.wheel,
        mouse.wheel_mode,
    ))
