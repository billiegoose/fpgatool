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
from hardware.font_row_rom import make_font_row_rom
from hardware.red2_row_data import ROW_DICTIONARY, ROW_INDICES, METADATA, KERNING
from hardware.uart_rx import make_uart_rx, uart_rx_t
from hardware.uart_text_buffer import make_uart_text_writer

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
_rows = make_font_row_rom(ROW_DICTIONARY)
_row_indices, _row_indices_t = make_ram(uint8_t, len(ROW_INDICES), ports=("r",),
                                      read_latency=1, init=ROW_INDICES)
_meta, _meta_t = make_ram(uint31_t, 128, ports=("r",), read_latency=1, init=METADATA)
_kern, _kern_t = make_ram(uint4_t, 16384, ports=("r", "r"), read_latency=1, init=KERNING)
# Eight packed pixels per word; eight memory words plus the FWFT output word.
# Including the consumer shift register, storage is at most 80 upcoming pixels.
_pixels, _pixels_t = make_fifo(uint32_t, 8)


@hw_func
def pack_pixels(bits: uint8_t) -> uint32_t:
    result: uint32_t = 0
    for n in range(8):
        result = result | (uint32_t((bits >> n) & 1) << (4 * n))
    return result


@struct
class glyph_row_t(NamedTuple):
    bits: uint21_t
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
    previous_code: Reg[uint7_t] = 0
    previous_width: Reg[uint5_t] = 0
    previous_origin: Reg[int13_t] = MARGIN_X
    older_code: Reg[uint7_t] = 0
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
    mail: Reg[glyph_row_t]
    mail_valid: Reg[uint1_t] = 0

    chars = _bytes(_bytes.p0_in_t(addr=edit.address[12:0], wr_data=edit.data,
                                wr_en=wr_en, valid=1),
                   _bytes.p1_in_t(addr=byte_read_index, valid=1))
    row_index = _row_indices(_row_indices.p0_in_t(addr=row_addr, valid=1))
    row = _rows(_rows.p0_in_t(addr=row_index.p0.rd_data, valid=1))
    meta = _meta(_meta.p0_in_t(addr=lookup_code, valid=1))
    pair_addr: uint14_t = (uint14_t(previous_code) << 7) | uint14_t(lookup_code)
    older_pair_addr: uint14_t = (uint14_t(older_code) << 7) | uint14_t(lookup_code)
    kern = _kern(_kern.p0_in_t(addr=pair_addr, valid=1),
                 _kern.p1_in_t(addr=older_pair_addr, valid=1))

    state: Reg[uint3_t] = 7  # begin, take, offsets, shifts, emit, merge, unused, idle
    window: Reg[uint64_t] = 0
    frontier: Reg[uint11_t] = 0
    incoming_left: Reg[int13_t] = 0
    incoming_bits: Reg[uint21_t] = 0
    incoming_width: Reg[uint5_t] = 0
    incoming_backtrack: Reg[uint3_t] = 0
    incoming_index: Reg[uint14_t] = 0
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
    offer: uint1_t = (state == 4) & (goal[10:3] > frontier[10:3])
    word: uint32_t = pack_pixels(window[7:0])
    fifo = _pixels(pop, word, offer)

    reset_loader: Reg[uint1_t] = 0
    stop_loader: Reg[uint1_t] = 0
    reset_request: uint1_t = reset_loader
    stop_request: uint1_t = stop_loader
    reset_loader = 0
    stop_loader = 0
    restart_index: uint14_t = line_start
    take_mail: uint1_t = (state == 1) & mail_valid

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
        shift = uint6_t(offset)
        if offset[12]:
            shift = uint6_t(-offset)
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
        older_code = 0
        older_width = 0
        previous_code = 0
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
        # Decode the next byte as the mailbox is consumed. This overlaps the
        # added ROM stages and keeps a six-clock glyph initiation interval.
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
        # Out-of-crop reads may wrap within the index ROM; their ink is masked
        # at the mailbox. Keep the crop comparison off the address path.
        row_addr = meta.p0.rd_data[30:20] + uint11_t(row_glyph_y - top_y)
        # Two read ports supply independent pair bounds from the same ROM.
        step_previous = int7_t(previous_width) + 4 - int7_t(kern.p0.rd_data)
        step_older = int7_t(older_width) + 4 - int7_t(kern.p1.rd_data)
        load_state = 5
    elif load_state == 5:
        # Register the additions separately from the maximum and mailbox mux.
        candidate_previous = previous_origin + int13_t(step_previous)
        candidate_older = older_origin + int13_t(step_older)
        load_state = 7
    elif load_state == 7:
        # Index ROM -> dictionary ROM. Its registered read settles before
        # the following mailbox stage. Kerning runs in parallel.
        next_at_end = following_index >= row_snapshot_end
        load_state = 8
    elif load_state == 8:
        if meta.p0.rd_data[8]:
            origin: int13_t = MARGIN_X
            if history_count != 0:
                origin = candidate_previous
            if (history_count == 2) & (candidate_older > origin):
                origin = candidate_older
            bits: uint21_t = 0
            if row_ink:
                bits = row.p0.rd_data
            mail = glyph_row_t(bits=bits, width=meta.p0.rd_data[4:0],
                               backtrack=meta.p0.rd_data[7:5], origin=origin,
                               index=read_index, after=following_index, kind=0)
            mail_valid = 1
            older_code = previous_code
            older_width = previous_width
            older_origin = previous_origin
            previous_code = lookup_code
            previous_width = meta.p0.rd_data[4:0]
            previous_origin = origin
            if history_count < 2:
                history_count = history_count + 1
            load_state = 6
        else:
            load_state = 1
        read_index = following_index
        at_end = next_at_end

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
def uart_text_video(rx: uint1_t) -> vga_12bpp_t:
    status = uart_text_scanout(rx)
    return status.video
