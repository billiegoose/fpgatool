# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Basys 3 kitchen-sink demo composed from reusable hardware blocks.

Exercises user I/O, USB-UART echo, VGA test bars, and the PS/2 mouse cursor
simultaneously. Top-level examples own pins; reusable logic lives under
`examples/hardware/`.
"""

from pypeline import *
from vga.types import vga_12bpp_t
from vga.timing import make_vga_timing, VGA_1920_1080
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.switches as board_switches
import fpgatool_board.basys3.buttons as board_buttons
import fpgatool_board.basys3.seven_segment as board_seven_segment
import fpgatool_board.basys3.uart as board_uart
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.ps2 as board_ps2
import hardware.led_chaser as led_hw
import hardware.buttons as button_hw

_button = button_hw.make_button()
import hardware.uart as uart_hw
import hardware.vga_test_bars as vga_bars
import hardware.mouse_cursor as mouse_cursor
import hardware.ps2_mouse as ps2_mouse_hw
from hardware.xilinx7_clock import MmcmStage, make_mmcm_clock, synchronize_clock_lock


vga_timing = make_vga_timing(VGA_1920_1080)
_test_bars = vga_bars.make_vga_test_bars(VGA_1920_1080)
_MAIN_CLK_MHZ = 100.0
_pixel_clock_generator = make_mmcm_clock(_MAIN_CLK_MHZ, MmcmStage(27, 4, 5), MmcmStage(11, 2, 5))
assert _pixel_clock_generator.output_mhz == vga_timing.pixel_clk_mhz
pixel_clock: Wire[uint1_t] = make_clock(_pixel_clock_generator.output_mhz)
pixel_locked: AsyncWire[uint1_t]
_mouse = ps2_mouse_hw.make_ps2_mouse(
    vga_timing.pixel_clk_mhz, VGA_1920_1080.frame_width, VGA_1920_1080.frame_height,
)
# Pipeline the complete pixel result, including sync, so overlay and background
# stay aligned while meeting the 148.5 MHz pixel clock.
_cursor = AUTO_PIPELINE(mouse_cursor.make_mouse_cursor(VGA_1920_1080), latency=2)


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


@MAIN(_MAIN_CLK_MHZ)
def kitchen_sink_demo():
    # Consume the previous cycle's debounced levels to break the long path
    # through button debounce, chaser update, and seven-segment decoding.
    left_button: Reg[button_hw.button_t]
    right_button: Reg[button_hw.button_t]
    up_button: Reg[button_hw.button_t]
    down_button: Reg[button_hw.button_t]
    center_button: Reg[button_hw.button_t]

    user = led_hw.led_chaser(
        board_switches.SW0, board_switches.SW1, board_switches.SW2, board_switches.SW3,
        board_switches.SW4, board_switches.SW5, board_switches.SW6, board_switches.SW7,
        board_switches.SW8, board_switches.SW9, board_switches.SW10, board_switches.SW11,
        board_switches.SW12, board_switches.SW13, board_switches.SW14, board_switches.SW15,
        left_button.level, right_button.level, up_button.level,
        down_button.level, center_button.level,
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

    left_button = _button(board_buttons.BTNL)
    right_button = _button(board_buttons.BTNR)
    up_button = _button(board_buttons.BTNU)
    down_button = _button(board_buttons.BTND)
    center_button = _button(board_buttons.BTNC)



@MAIN(_MAIN_CLK_MHZ)
def vga_pixel_clock():
    signals = _pixel_clock_generator(0)
    pixel_clock = signals.clock
    pixel_locked = signals.locked


@MAIN(vga_timing.pixel_clk_mhz)
def kitchen_sink_video():
    px: Reg[vga_12bpp_t]

    # Mouse and renderer share the pixel clock, so all coordinates and buttons
    # are coherent without a clock-domain crossing. Release PS/2 until locked.
    board_ps2.PS2Clk_T = 1
    board_ps2.PS2Data_T = 1
    if synchronize_clock_lock(pixel_locked):
        mouse = _mouse(board_ps2.PS2Clk_I, board_ps2.PS2Data_I)
        board_ps2.PS2Clk_T = mouse.clk_release
        board_ps2.PS2Data_T = mouse.data_release
        sig = vga_timing()
        bg = _test_bars(sig)
        px = _cursor(
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

    write_vga_pins(px)
