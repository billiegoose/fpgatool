# pyright: reportInvalidTypeForm=none
"""UART/VGA demo adapter around the reusable font-v2 glyph reader.

Only glyph rows and unfinished overlap ink are held by the compositor. The
pixel consumer sees four-bit color indices, never font addresses or bytes.
"""
from pypeline import *
from ram import make_ram
from fifo import make_fifo
from vga.timing import VGA_1920_1080, make_vga_timing
from vga.types import vga_12bpp_t
from hardware.font_v2.types import font_v2_config_t
from hardware.font_v2.renderer import read_glyph_row
from hardware.uart_rx import make_uart_rx, uart_rx_t
from hardware.uart_codepoints import uart_codepoints, codepoint_event_t

WIDTH = 1920
HEIGHT = 1080
MARGIN_X = 5
MARGIN_Y = 2
TEXT_RIGHT = WIDTH - MARGIN_X
TEXT_BOTTOM = HEIGHT - MARGIN_Y
BYTE_CAPACITY = 2048  # 24-bit Unicode scalars; three RAMB18 text blocks.
_timing = make_vga_timing(VGA_1920_1080, v_start=1124)
_receive = make_uart_rx(148.5)
_bytes, _bytes_t = make_ram(uint24_t, BYTE_CAPACITY, ports=("w", "r"), read_latency=1)
font_request_a: Wire[uint10_t]
font_request_b: Wire[uint10_t]
font_response_a: Wire[uint32_t]
font_response_b: Wire[uint32_t]
text_request: Wire[uint12_t]
font_blank_start: Wire[uint1_t]
font_blank_deadline: Wire[uint1_t]


# Eight packed pixels per word; eight memory words plus the FWFT output word.
# Including the consumer shift register, storage is at most 80 upcoming pixels.
_pixels, _pixels_t = make_fifo(uint32_t, 8)


@hw_func
def text_memory(write_address: uint11_t, write_data: uint24_t,
                write_enable: uint1_t) -> uint24_t:
    # Keep the readback connection between distinct hardware functions. A
    # read-before-write of the same global Wire inside one function is lowered
    # as an external readback input by the pinned compiler, rather than a loop.
    read_address: uint11_t = uint11_t(text_request)
    chars = _bytes(_bytes.p0_in_t(addr=write_address, wr_data=write_data,
                                wr_en=write_enable, valid=1),
                   _bytes.p1_in_t(addr=read_address, valid=1))
    return chars.p1.rd_data


@hw_func
def pack_pixels(bits: uint8_t) -> uint32_t:
    result: uint32_t = 0
    for n in range(8):
        result = result | (uint32_t((bits >> n) & 1) << (4 * n))
    return result


@struct
class uart_text_status_t(NamedTuple):
    video: vga_12bpp_t
    received: uart_rx_t
    committed: uint1_t
    full: uint1_t
    underflow: uint1_t


@hw_func
def uart_text_scanout(rx: uint1_t, config: font_v2_config_t, font_ready: uint1_t) -> uart_text_status_t:
    received = _receive(rx)
    sig = _timing()
    # The final blank line is reserved for the normal next-frame preparation.
    font_blank_start = (sig.pos.x == 0) & (sig.pos.y == HEIGHT)
    font_blank_deadline = (sig.pos.x == 0) & (sig.pos.y == 1124)
    written: Reg[uint12_t] = 0
    decoded: Reg[codepoint_event_t]
    # Consume the previous event before assigning the register below. Pypeline
    # forwards assignments within a call, so assigning here would join the
    # UART decoder and text RAM write-address logic into one combinational path.
    erase: uint1_t = (decoded.data == 8) | (decoded.data == 127)
    wr_en: uint1_t = decoded.valid & (((~erase) & (written < BYTE_CAPACITY)) | (erase & (written != 0)))
    write_address: uint11_t = uint11_t(written)
    # Keep a data qualifier before text BRAM as well as its write enable.
    # This gives registered UART data a logic stage on the short hold path.
    write_data: uint24_t = 0
    if decoded.valid:
        write_data = decoded.data
    write_tail: uint12_t = written + 1
    if erase:
        write_data = 0
        write_address = uint11_t(written - 1)
        write_tail = written - 1

    snapshot_end: Reg[uint12_t] = 0
    # Loader reads the committed frame snapshot, never the same-cycle update.
    row_snapshot_end: uint12_t = snapshot_end
    row_blank: Reg[uint1_t] = 1
    glyph_y: Reg[uint6_t] = 0
    row_glyph_y: uint6_t = glyph_y
    line_start: Reg[uint12_t] = 0
    line_end: Reg[uint12_t] = 0
    text_data = text_memory(write_address, write_data, wr_en)

    state: Reg[uint3_t] = 7  # begin, take, offsets, shifts, emit, merge, unused, idle
    window: Reg[uint64_t] = 0
    frontier: Reg[uint11_t] = 0
    incoming_left: Reg[int13_t] = 0
    incoming_bits: Reg[uint21_t] = 0
    incoming_width: Reg[uint5_t] = 0
    incoming_backtrack: Reg[uint3_t] = 0
    incoming_index: Reg[uint12_t] = 0
    offset: Reg[int13_t] = 0
    safe_left: Reg[int13_t] = 0
    shift: Reg[uint6_t] = 0
    shift_right: Reg[uint1_t] = 0
    goal: Reg[uint11_t] = 0
    ending: Reg[uint1_t] = 0

    holding: Reg[uint32_t] = 0
    left: Reg[uint4_t] = 0
    row_fault: Reg[uint1_t] = 0
    underflow: Reg[uint1_t] = 0
    drain: uint1_t = (sig.pos.x >= WIDTH) & (sig.pos.x < (WIDTH + 32))
    pop: uint1_t = (sig.active & (~row_fault) & (left == 0)) | drain

    # Writes are directly handshaken: the window moves only on acceptance.
    last_word: uint1_t = frontier == (WIDTH - 8)
    done_after_word: uint1_t = (frontier[10:3] + 1) >= goal[10:3]
    offer: uint1_t = (state == 4) & (goal[10:3] > frontier[10:3])
    word: uint32_t = pack_pixels(window[7:0])
    fifo = _pixels(pop, word, offer)

    reset_loader: Reg[uint1_t] = 0
    stop_loader: Reg[uint1_t] = 0
    reset_request: uint1_t = reset_loader
    stop_request: uint1_t = stop_loader
    reset_loader = 0
    stop_loader = 0
    restart_index: uint12_t = line_start
    glyph = read_glyph_row(config, font_ready, text_data,
        font_response_a, font_response_b, row_glyph_y, row_snapshot_end,
        restart_index, int13_t(MARGIN_X), reset_request, stop_request, state == 1)
    text_request = glyph.text_address
    font_request_a = glyph.font_address_a
    font_request_b = glyph.font_address_b
    mail = glyph.row
    mail_valid: uint1_t = glyph.valid

    if state == 0:
        window = 0
        frontier = 0
        goal = 0
        ending = 0
        if row_blank | (glyph_y >= 32):
            ending = 1
            goal = WIDTH
            state = 4
            stop_loader = 1
        else:
            reset_loader = 1
            state = 1
    elif state == 1:
        if mail_valid:
            if mail.kind != 0:
                line_end = mail.after
                goal = WIDTH
                ending = 1
                state = 4
                stop_loader = 1
            else:
                incoming_left = mail.origin
                incoming_bits = mail.bits
                incoming_width = mail.width
                incoming_backtrack = mail.backtrack
                incoming_index = mail.index
                state = 2
    elif state == 2:
        if (incoming_left + int13_t(incoming_width)) > TEXT_RIGHT:
            line_end = incoming_index
            goal = WIDTH
            ending = 1
            state = 4
            stop_loader = 1
        else:
            relative: int13_t = incoming_left - int13_t(frontier)
            safe: int13_t = incoming_left - int13_t(incoming_backtrack)
            goal = frontier
            if safe > int13_t(frontier):
                goal = uint11_t(safe)
            shift_right = relative[12]
            shift = uint6_t(relative)
            if relative[12]:
                shift = uint6_t(-relative)
            state = 5
    elif state == 5:
        placed: uint64_t = uint64_t(incoming_bits) << shift
        if shift_right:
            placed = uint64_t(incoming_bits) >> shift
        window = window | placed
        state = 4
    elif state == 4:
        if offer:
            if fifo.data_in_ready:
                window = window >> 8
                frontier = frontier + 8
                if last_word:
                    state = 7
                elif (~ending) & done_after_word:
                    state = 1
        else:
            state = 1

    # VGA owns row progression. A short drain interval also recovers from an
    # underflow; the producer cannot run into another row or another frame.
    if sig.pos.x == WIDTH:
        state = 7
        stop_loader = 1
    # Decode one clock ahead in horizontal blanking. These registered beam
    # predicates preserve the existing x=WIDTH+32 handoff while keeping the
    # full horizontal/vertical comparisons out of row-state register enables.
    prepare: Reg[uint1_t] = 0
    prepare_frame: Reg[uint1_t] = 0
    prepare_margin: Reg[uint1_t] = 0
    prepare_advance: Reg[uint1_t] = 0
    if prepare & font_ready:
        if prepare_frame:
            snapshot_end = written
            row_blank = 1
            glyph_y = 0
            line_start = 0
        else:
            # Preparing y+1: top and bottom margins are whole background rows.
            row_blank = prepare_margin
            if prepare_advance:
                if glyph_y == 35:
                    glyph_y = 0
                    line_start = line_end
                else:
                    glyph_y = glyph_y + 1
        state = 0
    prepare = (sig.pos.x == (WIDTH + 31)) & ((sig.pos.y < (HEIGHT - 1)) | (sig.pos.y == 1124))
    prepare_frame = sig.pos.y == 1124
    prepare_margin = (sig.pos.y < (MARGIN_Y - 1)) | (sig.pos.y >= (TEXT_BOTTOM - 1))
    prepare_advance = sig.pos.y >= MARGIN_Y

    if not font_ready:
        state = 7
        left = 0
        # A font can become ready in the middle of an active scanline. Keep
        # that row blank until the normal end-of-row reset and preparation,
        # rather than reporting a FIFO underflow before any pixels are offered.
        row_fault = 1
        underflow = 0

    if wr_en:
        written = write_tail
    decoded = uart_codepoints(received)

    # FWFT presents the next packed word before it is needed. The consumer
    # pops once per eight visible pixels and shifts one palette index per tick.
    color: uint4_t = 0
    if sig.active & (~row_fault) & font_ready:
        if left == 0:
            if fifo.data_out_valid:
                color = fifo.data_out[3:0]
                holding = fifo.data_out >> 4
                left = 7
            else:
                underflow = 1
                row_fault = 1
        else:
            color = holding[3:0]
            holding = holding >> 4
            left = left - 1
    if sig.pos.x == WIDTH:
        left = 0
        row_fault = 0
    # Binary font ink maps to palette entries 0 (black) and 1 (white).
    # Four-bit indices leave room for a programmable 16-entry RGB palette.
    shade: uint4_t = 0
    inside: uint1_t = ((sig.pos.x >= MARGIN_X) & (sig.pos.x < TEXT_RIGHT)
                      & (sig.pos.y >= MARGIN_Y) & (sig.pos.y < TEXT_BOTTOM))
    if (color == 1) & inside:
        shade = 15
    video = vga_12bpp_t(r=shade, g=shade, b=shade, hs=sig.hsync, vs=sig.vsync)
    return uart_text_status_t(video=video, received=received, committed=wr_en,
                              full=(written == BYTE_CAPACITY), underflow=underflow)


@hw_func
def uart_text_video(rx: uint1_t, config: font_v2_config_t, font_ready: uint1_t) -> vga_12bpp_t:
    status = uart_text_scanout(rx, config, font_ready)
    return status.video
