# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Basys 3 kitchen-sink demo composed from reusable hardware blocks.

Exercises user I/O, USB-UART echo, VGA test bars, and the PS/2 mouse cursor
simultaneously. Top-level examples own pins; reusable logic lives under
`examples/hardware/`.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.user_io as board_user
import board.basys3.uart as board_uart
import board.basys3.vga as board_vga
import board.basys3.ps2_mouse as board_mouse
import hardware.led_chaser as led_hw
import hardware.uart as uart_hw
import hardware.vga_timing as vga_timing
import hardware.vga_test_bars as vga_bars
import hardware.mouse_cursor as mouse_cursor


@MAIN(100.0)
def kitchen_sink_demo():
    user = led_hw.led_chaser(
        board_user.SW0, board_user.SW1, board_user.SW2, board_user.SW3,
        board_user.SW4, board_user.SW5, board_user.SW6, board_user.SW7,
        board_user.SW8, board_user.SW9, board_user.SW10, board_user.SW11,
        board_user.SW12, board_user.SW13, board_user.SW14, board_user.SW15,
        board_user.BTNL, board_user.BTNR, board_user.BTNU,
        board_user.BTND, board_user.BTNC,
    )

    board_user.LD0 = user.ld0
    board_user.LD1 = user.ld1
    board_user.LD2 = user.ld2
    board_user.LD3 = user.ld3
    board_user.LD4 = user.ld4
    board_user.LD5 = user.ld5
    board_user.LD6 = user.ld6
    board_user.LD7 = user.ld7
    board_user.LD8 = user.ld8
    board_user.LD9 = user.ld9
    board_user.LD10 = user.ld10
    board_user.LD11 = user.ld11
    board_user.LD12 = user.ld12
    board_user.LD13 = user.ld13
    board_user.LD14 = user.ld14
    board_user.LD15 = user.ld15

    board_user.AN0 = user.an0
    board_user.AN1 = user.an1
    board_user.AN2 = user.an2
    board_user.AN3 = user.an3
    board_user.CA = user.ca
    board_user.CB = user.cb
    board_user.CC = user.cc
    board_user.CD = user.cd
    board_user.CE = user.ce
    board_user.CF = user.cf
    board_user.CG = user.cg
    board_user.DP = user.dp

    uart = uart_hw.uart_echo(board_uart.RsRx, uint8_t(0), uint8_t(0))
    board_uart.RsTx = uart.tx

    sig = vga_timing.vga_timing_25mhz_from_100mhz()
    bg = vga_bars.test_bars(sig)
    mouse = board_mouse.mouse
    board_vga.vga = mouse_cursor.overlay_cursor(
        sig,
        bg,
        mouse.x,
        mouse.y,
        mouse.left,
        mouse.middle,
        mouse.right,
        mouse.wheel,
        mouse.wheel_mode,
    )
