"""Simulation harness: ideal 148.5 MHz clock replaces the board MMCM.

Use vga_uart_1920_1080_font_v2_demo.py for hardware. This harness runs the same UART and VGA
core, with real serial bits driven by fpgatool sim --uart-file.
"""
# pyright: reportInvalidTypeForm=none
from pypeline import *
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.vga as board_vga
import fpgatool_board.basys3.uart as board_uart
import hardware.vga_uart_font_v2_pixels as renderer
from hardware.font_v2.memory import make_font_v2_rom
from hardware.font_v2.loader import consume_font_word
from hardware.font_v2.format import HEADER_WORDS, PAYLOAD_WORDS
from hardware import red2_font_v2_data as reference
import os
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

# Exercise the same header decoder and BRAM writes, bypassing only the SPI bus.
_boot_words = reference.FONT_HEADER_WORDS + reference.FONT_WORDS
# Optional HDL regression: replace spacing at the sixth vertical blank. The
# fixture bypasses SPI pins but emits words at the burst reader's real cadence.
_reload_test = int(os.environ.get('FPGATOOL_FONT_RELOAD_CAPTURE', '0'))
_replacement = list(_boot_words)
_replacement[14] = 9
_replacement[16] = 0
_replacement[16] = -sum(_replacement) & 0xffffffff
_replacement_words = tuple(_replacement)
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
def vga_uart_1920_1080_font_v2_capture():
    px: Reg[vga_12bpp_t]
    write_vga_pins(px)
    index: Reg[uint11_t] = 0
    frame: Reg[uint4_t] = 0
    replaced: Reg[uint1_t] = 0
    pace: Reg[uint7_t] = 0
    command_wait: Reg[uint9_t] = 0
    reset: uint1_t = 0
    if _reload_test & renderer.font_blank_start:
        if frame == 5:
            replaced = 1
            index = 0
            pace = 0
            command_wait = 400
            reset = 1
        if frame < 15:
            frame = frame + 1
    boot_word: uint32_t = 0
    # Simulation-only fixture ROM; hardware reads these words from QSPI.
    words: uint32_t[HEADER_WORDS + PAYLOAD_WORDS] = _boot_words
    replacement: uint32_t[HEADER_WORDS + PAYLOAD_WORDS] = _replacement_words
    active: uint1_t = index < (HEADER_WORDS + PAYLOAD_WORDS)
    if replaced:
        active = active & (pace == 79) & (command_wait == 0)
        if command_wait != 0:
            command_wait = command_wait - 1
        else:
            pace = pace + 1
            if pace == 80:
                pace = 0
    active = active & (~reset)
    if active:
        boot_word = words[index]
        if replaced:
            boot_word = replacement[index]
        index = index + 1
    boot = consume_font_word(boot_word, active, uint1_t(0), reset)
    # Isolate the parser's word bus from the font BRAM write placement.
    write_enable: Reg[uint1_t] = 0
    write_address: Reg[uint10_t] = 0
    write_data: Reg[uint32_t] = 0
    font_write_enable = write_enable
    font_write_address = write_address
    font_write_data = write_data
    font_read_enable = boot.ready
    write_enable = boot.write_enable
    write_address = boot.write_address
    write_data = boot.write_data
    status = renderer.uart_text_scanout(board_uart.RsRx, boot.config, boot.ready)
    px = status.video
    board_uart.RsTx = 1
