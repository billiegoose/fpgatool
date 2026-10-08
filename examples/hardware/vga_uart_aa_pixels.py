# pyright: reportInvalidTypeForm=none
"""Continuous UART bytes -> row-major font compositor -> small pixel FIFO -> VGA.

Only glyph rows and unfinished overlap ink are held by the compositor. The
pixel consumer sees four-bit color indices, never font addresses or bytes.
"""
from pypeline import *
from ram import make_ram
from fifo import make_fifo
from vga.timing import VGA_1920_1080, make_vga_timing
from vga.types import vga_12bpp_t
from hardware.font_row_aa_rom import make_font_row_rom
from hardware.red2_aa_row_data import (ROW_DICTIONARY, ROW_INDICES, METADATA, KERNING,
                                    KERNING_LEFT_COUNT, KERNING_RIGHT_COUNT)
from hardware.uart_rx import make_uart_rx, uart_rx_t
from hardware.uart_text_buffer import make_uart_text_writer

uint128_t = make_uint_t(128)

WIDTH = 1920
HEIGHT = 1080
MARGIN_X = 5
MARGIN_Y = 2
TEXT_RIGHT = WIDTH - MARGIN_X
TEXT_BOTTOM = HEIGHT - MARGIN_Y
BYTE_CAPACITY = 8192
_timing = make_vga_timing(VGA_1920_1080, v_start=1124)
_receive = make_uart_rx(148.5)
_edit = make_uart_text_writer(BYTE_CAPACITY)
_bytes, _bytes_t = make_ram(uint8_t, BYTE_CAPACITY, ports=("w", "r"), read_latency=1)
_font = make_font_row_rom(ROW_DICTIONARY)
_row_indices, _row_indices_t = make_ram(uint9_t, 2048, ports=("r",),
                                      read_latency=1, init=ROW_INDICES)
_meta, _meta_t = make_ram(uint43_t, 128, ports=("r",), read_latency=1, init=METADATA)
# Pad the compact class table to a 64-column stride: two six-bit IDs are the
# address. Both histories read the same 4096 x 4-bit dual-port block ROM.
_kerning_init = [KERNING[left * KERNING_RIGHT_COUNT + right]
                 if left < KERNING_LEFT_COUNT and right < KERNING_RIGHT_COUNT else 0
                 for left in range(64) for right in range(64)]
_kern, _kern_t = make_ram(uint4_t, 4096, ports=("r", "r"), read_latency=1, init=_kerning_init)
# Eight packed pixels per word; eight memory words plus the FWFT output word.
# Including the consumer shift register, storage is at most 80 upcoming pixels.
_pixels, _pixels_t = make_fifo(uint32_t, 8)


@hw_func
def pack_pixels(bits: uint16_t) -> uint32_t:
    result: uint32_t = 0
    for n in range(8):
        result = result | (uint32_t((bits >> (2 * n)) & 3) << (4 * n))
    return result


@hw_func
def blend_rows(a: uint128_t, b: uint128_t) -> uint128_t:
    # Select max(a, b) independently for each two-bit coverage value.
    low_mask: uint128_t = 0x55555555555555555555555555555555
    a_low: uint128_t = a & low_mask
    b_low: uint128_t = b & low_mask
    a_high: uint128_t = (a >> 1) & low_mask
    b_high: uint128_t = (b >> 1) & low_mask
    greater: uint128_t = ((a_high & (~b_high))
                         | ((~(a_high ^ b_high)) & a_low & (~b_low))) & low_mask
    select: uint128_t = greater | (greater << 1)
    return (a & select) | (b & (~select))


@struct
class glyph_row_t(NamedTuple):
    bits: uint42_t
    width: uint5_t
    backtrack: uint3_t
    origin: int13_t
    index: uint14_t
    after: uint14_t
    kind: uint2_t  # 0 glyph, 1 newline, 2 end of the snapshot.


@struct
class uart_text_status_t(NamedTuple):
    video: vga_12bpp_t
    received: uart_rx_t
    committed: uint1_t
    full: uint1_t
    underflow: uint1_t


@hw_func
def uart_text_scanout(rx: uint1_t) -> uart_text_status_t:
    received = _receive(rx)
    sig = _timing()
    written: Reg[uint14_t] = 0
    edit = _edit(received, written)
    wr_en: uint1_t = edit.committed

    snapshot_end: Reg[uint14_t] = 0
    # Loader reads the committed frame snapshot, never the same-cycle update.
    row_snapshot_end: uint14_t = snapshot_end
    row_blank: Reg[uint1_t] = 1
    glyph_y: Reg[uint6_t] = 0
    row_glyph_y: uint6_t = glyph_y
    line_start: Reg[uint14_t] = 0
    line_end: Reg[uint14_t] = 0
    read_index: Reg[uint14_t] = 0
    byte_read_index: Reg[uint13_t] = 0
    following_index: Reg[uint14_t] = 0
    at_end: Reg[uint1_t] = 1
    next_at_end: Reg[uint1_t] = 1
    lookup_code: Reg[uint7_t] = 0
    previous_class: Reg[uint6_t] = 0
    previous_width: Reg[uint5_t] = 0
    previous_origin: Reg[int13_t] = MARGIN_X
    older_class: Reg[uint6_t] = 0
    older_width: Reg[uint5_t] = 0
    older_origin: Reg[int13_t] = MARGIN_X
    history_count: Reg[uint2_t] = 0
    step_previous: Reg[int7_t] = 0
    step_older: Reg[int7_t] = 0
    candidate_previous: Reg[int13_t] = MARGIN_X
    candidate_older: Reg[int13_t] = MARGIN_X
    load_state: Reg[uint4_t] = 0
    row_addr: Reg[uint11_t] = 0
    row_ink: Reg[uint1_t] = 0
    dictionary_address: Reg[uint9_t] = 0
    glyph_origin: Reg[int13_t] = MARGIN_X
    mail: Reg[glyph_row_t]
    mail_valid: Reg[uint1_t] = 0

    chars = _bytes(_bytes.p0_in_t(addr=edit.address[12:0], wr_data=edit.data,
                                wr_en=wr_en, valid=1),
                   _bytes.p1_in_t(addr=byte_read_index, valid=1))
    row_index = _row_indices(_row_indices.p0_in_t(addr=row_addr, valid=1))
    font = _font(_font.p0_in_t(addr=dictionary_address, valid=1))
    meta = _meta(_meta.p0_in_t(addr=lookup_code, valid=1))
    pair_addr: uint12_t = (uint12_t(previous_class) << 6) | uint12_t(meta.p0.rd_data[42:37])
    older_pair_addr: uint12_t = (uint12_t(older_class) << 6) | uint12_t(meta.p0.rd_data[42:37])
    kern = _kern(_kern.p0_in_t(addr=pair_addr, valid=1),
                 _kern.p1_in_t(addr=older_pair_addr, valid=1))

    state: Reg[uint3_t] = 7  # begin, take, offsets, shifts, emit, merge, unused, idle
    window: Reg[uint128_t] = 0
    frontier: Reg[uint11_t] = 0
    incoming_left: Reg[int13_t] = 0
    incoming_bits: Reg[uint42_t] = 0
    incoming_width: Reg[uint5_t] = 0
    incoming_backtrack: Reg[uint3_t] = 0
    incoming_index: Reg[uint14_t] = 0
    offset: Reg[int13_t] = 0
    safe_left: Reg[int13_t] = 0
    shift: Reg[uint7_t] = 0
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
    offer: uint1_t = (state == 4) & (goal[10:3] > frontier[10:3])
    word: uint32_t = pack_pixels(window[15:0])
    fifo = _pixels(pop, word, offer)

    reset_loader: Reg[uint1_t] = 0
    stop_loader: Reg[uint1_t] = 0
    reset_request: uint1_t = reset_loader
    stop_request: uint1_t = stop_loader
    reset_loader = 0
    stop_loader = 0
    restart_index: uint14_t = line_start
    take_mail: uint1_t = (state == 1) & mail_valid
    mail_available: uint1_t = (~mail_valid) | take_mail

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
            mail_valid = 0
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
            safe_left = incoming_left - int13_t(incoming_backtrack)
            offset = incoming_left - int13_t(frontier)
            state = 3
    elif state == 3:
        goal = frontier
        if safe_left > int13_t(frontier):
            goal = uint11_t(safe_left)
        shift_right = offset[12]
        shift = uint7_t(offset) << 1
        if offset[12]:
            shift = uint7_t(-offset) << 1
        state = 5
    elif state == 5:
        placed: uint128_t = uint128_t(incoming_bits) << shift
        if shift_right:
            placed = uint128_t(incoming_bits) >> shift
        window = blend_rows(window, placed)
        state = 4
    elif state == 4:
        if offer:
            if fifo.data_in_ready:
                window = window >> 16
                frontier = frontier + 8
                if last_word:
                    state = 7
        else:
            state = 1

    # VGA owns row progression. A short drain interval also recovers from an
    # underflow; the producer cannot run into another row or another frame.
    if sig.pos.x == WIDTH:
        state = 7
        stop_loader = 1
    prepare: uint1_t = (sig.pos.x == (WIDTH + 32)) & ((sig.pos.y < (HEIGHT - 1)) | (sig.pos.y == 1124))
    if prepare:
        if sig.pos.y == 1124:
            snapshot_end = written
            row_blank = 1
            glyph_y = 0
            line_start = 0
        else:
            # Preparing y+1: top and bottom margins are whole background rows.
            row_blank = (sig.pos.y < (MARGIN_Y - 1)) | (sig.pos.y >= (TEXT_BOTTOM - 1))
            if sig.pos.y >= MARGIN_Y:
                if glyph_y == 35:
                    glyph_y = 0
                    line_start = line_end
                else:
                    glyph_y = glyph_y + 1
        state = 0

    # Registered start/stop requests break the compositor-to-loader control path.
    # The loader's single-slot mailbox is the "next character row". RAM reads
    # and kerning lookup overlap the run generator's current-row work.
    if reset_request:
        read_index = restart_index
        byte_read_index = uint13_t(restart_index)
        history_count = 0
        previous_origin = MARGIN_X
        older_origin = MARGIN_X
        older_class = 0
        older_width = 0
        previous_class = 0
        previous_width = 0
        mail_valid = 0
        load_state = 1
    elif stop_request:
        mail_valid = 0
        load_state = 0
    elif load_state == 1:
        at_end = read_index >= row_snapshot_end
        load_state = 2
    elif (load_state == 2) | ((load_state == 6) & take_mail):
        # Normal decode path for the first byte and newline/end/unsupported
        # boundaries. Supported glyphs predecode at mailbox publication below.
        if at_end:
            mail = glyph_row_t(bits=0, width=0, backtrack=0, origin=0,
                               index=read_index, after=row_snapshot_end, kind=2)
            mail_valid = 1
            load_state = 6
        elif chars.p1.rd_data == 10:
            mail = glyph_row_t(bits=0, width=0, backtrack=0, origin=0,
                               index=read_index, after=read_index + 1, kind=1)
            mail_valid = 1
            load_state = 6
        elif (chars.p1.rd_data >= 32) & (chars.p1.rd_data < 128):
            lookup_code = chars.p1.rd_data[6:0]
            # Prefetch the following byte throughout the font lookup, so
            # even an immediately consumed mailbox can decode it correctly.
            byte_read_index = uint13_t(read_index + 1)
            load_state = 3
        else:
            byte_read_index = uint13_t(read_index + 1)
            read_index = read_index + 1
            load_state = 1
    elif load_state == 3:
        following_index = read_index + 1
        load_state = 4
    elif load_state == 4:
        # Metadata -> cropped row address is a registered pipeline stage.
        top_y: uint6_t = uint6_t(meta.p0.rd_data[19:15])
        height: uint6_t = meta.p0.rd_data[14:9]
        row_ink = (row_glyph_y >= top_y) & (row_glyph_y < (top_y + height))
        # Out-of-crop reads may wrap within the font ROM; their ink is masked
        # at the mailbox. Keep the crop comparison off the address path.
        row_addr = meta.p0.rd_data[30:20] + uint11_t(row_glyph_y - top_y)
        load_state = 5
    elif load_state == 5:
        # Class mappings arrive with metadata; the dependent kerning read
        # settles one clock later. Both histories share the same class ROM.
        step_previous = int7_t(previous_width) + 4 - int7_t(kern.p0.rd_data)
        step_older = int7_t(older_width) + 4 - int7_t(kern.p1.rd_data)
        load_state = 7
    elif load_state == 7:
        # Register the additions separately from the maximum and mailbox mux.
        candidate_previous = previous_origin + int13_t(step_previous)
        candidate_older = older_origin + int13_t(step_older)
        # Nine-bit cropped row ID selects the 42-bit two-bit-pixel pattern.
        dictionary_address = row_index.p0.rd_data
        next_at_end = following_index >= row_snapshot_end
        load_state = 8
    elif load_state == 8:
        # Dictionary words are being read. Resolve placement in parallel.
        glyph_origin = MARGIN_X
        if history_count != 0:
            glyph_origin = candidate_previous
        if (history_count == 2) & (candidate_older > glyph_origin):
            glyph_origin = candidate_older
        load_state = 9
    elif (load_state == 9) & mail_available:
        if meta.p0.rd_data[8]:
            bits: uint42_t = 0
            if row_ink:
                bits = font.p0.rd_data
            mail = glyph_row_t(bits=bits, width=meta.p0.rd_data[4:0],
                               backtrack=meta.p0.rd_data[7:5], origin=glyph_origin,
                               index=read_index, after=following_index, kind=0)
            mail_valid = 1
            older_class = previous_class
            older_width = previous_width
            older_origin = previous_origin
            previous_class = meta.p0.rd_data[36:31]
            previous_width = meta.p0.rd_data[4:0]
            previous_origin = glyph_origin
            if history_count < 2:
                history_count = history_count + 1
            load_state = 6
        else:
            load_state = 1
        read_index = following_index
        at_end = next_at_end
        # Start the following supported byte while this row waits in the
        # mailbox. The next publication stalls if that mailbox is still full.
        # This hides the added address stage: six clocks per glyph steady-state.
        if (~next_at_end) & (chars.p1.rd_data >= 32) & (chars.p1.rd_data < 128):
            lookup_code = chars.p1.rd_data[6:0]
            byte_read_index = uint13_t(following_index + 1)
            load_state = 3

    if wr_en:
        written = edit.tail

    # FWFT presents the next packed word before it is needed. The consumer
    # pops once per eight visible pixels and shifts one palette index per tick.
    color: uint4_t = 0
    if sig.active & (~row_fault):
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
    # Fitted sRGB palette (0, 59, 198, 255), rounded to four-bit DAC levels.
    # Four-bit indices leave room for a programmable 16-entry RGB palette.
    shade: uint4_t = 0
    inside: uint1_t = ((sig.pos.x >= MARGIN_X) & (sig.pos.x < TEXT_RIGHT)
                      & (sig.pos.y >= MARGIN_Y) & (sig.pos.y < TEXT_BOTTOM))
    if inside:
        if color == 1:
            shade = 3
        elif color == 2:
            shade = 12
        elif color == 3:
            shade = 15
    video = vga_12bpp_t(r=shade, g=shade, b=shade, hs=sig.hsync, vs=sig.vsync)
    return uart_text_status_t(video=video, received=received, committed=wr_en,
                              full=(written == BYTE_CAPACITY), underflow=underflow)


@hw_func
def uart_text_video(rx: uint1_t) -> vga_12bpp_t:
    status = uart_text_scanout(rx)
    return status.video
