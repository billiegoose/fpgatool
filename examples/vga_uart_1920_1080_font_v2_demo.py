"""Basys 3 UART -> font-v2 RED2 text, 1920x1080 VGA at 60 Hz.

115200 baud, 8-N-1. LF starts a new line; CR is ignored. Undefined codepoints
render .notdef. Backspace (08) and Delete (7F) remove the last buffered codepoint.
Text wraps at the right margin; a 2048-codepoint buffer feeds a 64-bit compositor
and a small pixel FIFO.
"""
# pyright: reportInvalidTypeForm=none
from pypeline import *
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.uart as board_uart
import hardware.vga_uart_font_v2_pixels as renderer
from hardware.font_v2.memory import make_font_v2_rom
from hardware.font_v2.loader import load_font_from_qspi
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.live_flash as board_live_flash
from hardware.live_flash import live_flash_application_t
_font = make_font_v2_rom()
font_write_enable: Wire[uint1_t]
font_write_address: Wire[uint10_t]
font_write_data: Wire[uint32_t]
font_read_enable: Wire[uint1_t]


@MAIN(148.5)
def font_v2_memory_clock():
    address: uint10_t = renderer.font_request_a
    write_data: uint32_t = 0
    if font_write_enable:
        address = font_write_address
        write_data = font_write_data
    result = _font(_font.p0_in_t(addr=address, wr_data=write_data,
                                wr_en=font_write_enable, valid=font_read_enable | font_write_enable),
                   _font.p1_in_t(addr=renderer.font_request_b, valid=font_read_enable))
    renderer.font_response_a = result.p0.rd_data
    renderer.font_response_b = result.p1.rd_data

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
def vga_uart_1920_1080_font_v2_demo():
    px: Reg[vga_12bpp_t]
    write_vga_pins(px)
    locked = synchronize_clock_lock(pixel_locked)
    dq: uint4_t = concat(board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
                         board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)
    blank_start: Reg[uint1_t] = 0
    blank_deadline: Reg[uint1_t] = 0
    boot = load_font_from_qspi(dq, blank_start, blank_deadline,
                               board_live_flash.reload_request, board_live_flash.clear_error)
    blank_start = renderer.font_blank_start
    blank_deadline = renderer.font_blank_deadline
    live = board_live_flash.proxy(boot.flash, live_flash_application_t(
        ready=boot.font.ready, busy=boot.busy, quiescent=~boot.busy,
        done=boot.done, error=boot.font.error), dq[1])
    flash = live.flash
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(flash.cclk, flash.cs_n, not flash.busy)
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = flash.dq0_t
    board_qspi.QspiDQ1_O = flash.dq1
    board_qspi.QspiDQ1_T = flash.dq1_t
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = flash.dq2_t
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = flash.dq3_t
    # Isolate the parser's word bus from the font BRAM write placement.
    write_enable: Reg[uint1_t] = 0
    write_address: Reg[uint10_t] = 0
    write_data: Reg[uint32_t] = 0
    font_write_enable = write_enable
    font_write_address = write_address
    font_write_data = write_data
    font_read_enable = boot.font.ready
    write_enable = boot.font.write_enable
    write_address = boot.font.write_address
    write_data = boot.font.write_data
    status = renderer.uart_text_scanout(board_uart.RsRx, boot.font.config, boot.font.ready)
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
    board_leds.LD14 = boot.font.ready
    board_leds.LD15 = boot.font.error
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
