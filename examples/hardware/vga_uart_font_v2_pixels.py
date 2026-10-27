# pyright: reportInvalidTypeForm=none
"""Font-v2 renderer: Unicode scalars -> banked font compositor -> VGA.

Only glyph rows and unfinished overlap ink are held by the compositor. The
pixel consumer sees four-bit color indices, never font addresses or bytes.
"""
from pypeline import *
from ram import make_ram
from fifo import make_fifo
from vga.timing import VGA_1920_1080, make_vga_timing
from vga.types import vga_12bpp_t
from hardware.font_v2_rom import make_font_v2_rom
from hardware.red2_font_v2_data import (FONT_WORDS, METADATA_BASE, CROP_BASE, ROWS_BASE,
                                      PATTERNS_BASE, KERNING_BASE, PAGES, SPACING)
from hardware.uart_rx import make_uart_rx, uart_rx_t
from hardware.uart_codepoints import uart_codepoints, codepoint_event_t
from hardware.font_v2_row_address import capture_row_address, row_address_input_t

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
_font = make_font_v2_rom(FONT_WORDS)
font_request_a: Wire[uint10_t]
font_request_b: Wire[uint10_t]
font_response_a: Wire[uint32_t]
font_response_b: Wire[uint32_t]


@MAIN(148.5)
def font_v2_memory_clock():
    result = _font(_font.p0_in_t(addr=font_request_a, valid=1),
                   _font.p1_in_t(addr=font_request_b, valid=1))
    font_response_a = result.p0.rd_data
    font_response_b = result.p1.rd_data


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
    index: uint12_t
    after: uint12_t
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
    read_index: Reg[uint12_t] = 0
    byte_read_index: Reg[uint12_t] = 0
    previous_class: Reg[uint5_t] = 0
    previous_width: Reg[uint5_t] = 0
    previous_origin: Reg[int13_t] = MARGIN_X
    older_class: Reg[uint5_t] = 0
    older_width: Reg[uint5_t] = 0
    older_origin: Reg[int13_t] = MARGIN_X
    history_count: Reg[uint2_t] = 0
    amount_previous: Reg[uint4_t] = 0
    amount_older: Reg[uint4_t] = 0
    step_previous: Reg[int7_t] = 0
    step_older: Reg[int7_t] = 0
    candidate_previous: Reg[int13_t] = MARGIN_X
    candidate_older: Reg[int13_t] = MARGIN_X
    codepoint: Reg[uint24_t] = 0
    prefetch_ready: Reg[uint1_t] = 0
    load_state: Reg[uint3_t] = 0  # idle, warmup, launch, and five overlapped read phases
    font_addr_a: Reg[uint10_t] = 0
    font_addr_b: Reg[uint10_t] = 0
    prefetched_gid: Reg[uint8_t] = 0
    prefetched_kind: Reg[uint2_t] = 3
    prefetched_valid: Reg[uint1_t] = 0
    current_meta: Reg[uint32_t] = 0
    current_valid: Reg[uint1_t] = 0
    current_kind: Reg[uint2_t] = 3
    current_index: Reg[uint12_t] = 0
    current_after: Reg[uint12_t] = 0
    source_done: Reg[uint1_t] = 0
    page_present: Reg[uint1_t] = 0
    page_glyph_base: Reg[uint8_t] = 0
    page_glyph_count: Reg[uint9_t] = 0
    map_select: Reg[uint2_t] = 0
    map_overlay: Reg[uint1_t] = 0
    crop_select: Reg[uint1_t] = 0
    crop_address: Reg[uint10_t] = 0
    row_select: Reg[uint2_t] = 0
    kern1_select: Reg[uint3_t] = 0
    kern2_select: Reg[uint3_t] = 0
    row_ink: Reg[uint1_t] = 0
    pattern_id: Reg[uint9_t] = 0
    pattern_bits: Reg[uint21_t] = 0
    crop: Reg[uint12_t] = 0
    pending_meta: Reg[uint32_t] = 0
    pending_valid: Reg[uint1_t] = 0
    pending_ink: Reg[uint1_t] = 0
    pending_kind: Reg[uint2_t] = 3
    pending_index: Reg[uint12_t] = 0
    pending_after: Reg[uint12_t] = 0
    mail: Reg[glyph_row_t]
    mail_valid: Reg[uint1_t] = 0
    load_phase: uint3_t = load_state

    chars = _bytes(_bytes.p0_in_t(addr=write_address, wr_data=write_data,
                                wr_en=wr_en, valid=1),
                   _bytes.p1_in_t(addr=byte_read_index[10:0], valid=1))
    font_a: uint32_t = font_response_a
    font_b: uint32_t = font_response_b
    row_lookup = capture_row_address(row_address_input_t(
        crop_word=uint32_t(crop), crop_select=0, y=row_glyph_y,
        glyph_base=current_meta[10:0], rows_base=uint10_t(ROWS_BASE)), load_phase == 5)

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

    # Snapshot old register values before any assignment: Pypeline forwards
    # same-call writes, including writes in a separate phase-conditional block.
    saved_previous_amount: uint4_t = amount_previous
    saved_older_amount: uint4_t = amount_older
    # Capture the nibble separately from advance arithmetic. While publication
    # stalls, B holds this same older-kerning word, so repeated captures agree.
    if load_phase == 5:
        amount_older = uint4_t(font_b >> (uint5_t(kern2_select) << 2))

    # The font memory runs in a separate same-clock actor: its synchronous
    # outputs feed this controller and these requests feed its next reads.
    # Five phases overlap this glyph with the preceding glyph. Each pattern
    # needs one direct read; two crop-register cuts fit without increasing II.
    if reset_request:
        read_index = restart_index
        byte_read_index = uint12_t(restart_index)
        history_count = 0
        previous_origin = MARGIN_X
        older_origin = MARGIN_X
        previous_class = 0
        previous_width = 0
        older_class = 0
        older_width = 0
        current_valid = 0
        pending_valid = 0
        prefetched_valid = 0
        source_done = 0
        mail_valid = 0
        prefetch_ready = 0
        load_state = 1
    elif stop_request:
        current_valid = 0
        pending_valid = 0
        mail_valid = 0
        load_state = 0
    elif load_phase == 1:
        # Text BRAM and the explicit prefetch register each take one clock.
        if prefetch_ready:
            load_state = 2
        prefetch_ready = 1
    elif load_phase == 3:
        # Both requests consume old address/ID registers. No ROM output feeds
        # another ROM address in the same clock.
        font_addr_a = crop_address
        font_addr_b = uint10_t(PATTERNS_BASE) + uint10_t(pattern_id)
        candidate_previous = previous_origin + int13_t(step_previous)
        load_state = 4
    elif load_phase == 4:
        crop = font_a[11:0]
        if crop_select:
            crop = font_a[27:16]
        pattern_bits = font_b[20:0]
        # Forecast the older class after publication: a supported pending
        # glyph advances history; skipped/control tokens leave it unchanged.
        k2_class: uint5_t = older_class
        if pending_valid & (pending_kind == 0):
            k2_class = previous_class
        k2: uint10_t = (uint10_t(k2_class) << 5) | uint10_t(current_meta[25:21])
        font_addr_b = uint10_t(KERNING_BASE) + (k2 >> 3)
        kern2_select = k2[2:0]
        load_state = 5
    elif (load_phase == 5) & ((~pending_valid) | mail_available):
        # Publication is the only stall point. A holds the map response and
        # B holds older kerning. Crop and saved pattern stay stable.
        if pending_valid & (pending_kind != 3):
            origin: int13_t = MARGIN_X
            if history_count != 0:
                origin = candidate_previous
            if (history_count == 2) & (candidate_older > origin):
                origin = candidate_older
            bits: uint21_t = 0
            if pending_ink:
                bits = pattern_bits
            mail = glyph_row_t(bits=bits, width=pending_meta[30:26], backtrack=0,
                               origin=origin, index=pending_index, after=pending_after,
                               kind=pending_kind)
            mail_valid = 1
            if pending_kind == 0:
                older_class = previous_class
                older_width = previous_width
                older_origin = previous_origin
                previous_class = pending_meta[20:16]
                previous_width = pending_meta[30:26]
                previous_origin = origin
                if history_count < 2:
                    history_count = history_count + 1
        local: uint8_t = uint8_t(font_a >> (uint5_t(map_select) << 3))
        if map_overlay:
            local = font_a[28:21]
        mapped: uint1_t = page_present & (uint9_t(local) < page_glyph_count)
        # Missing entries and absent Unicode pages use glyph 0 (.notdef).
        # Keep ordinary glyph tokens so fallback ink and advance are retained.
        prefetched_gid = 0
        if mapped:
            prefetched_gid = page_glyph_base + local
        # Publication advances history before requesting current kerning.
        k1: uint10_t = (uint10_t(previous_class) << 5) | uint10_t(current_meta[25:21])
        font_addr_b = uint10_t(KERNING_BASE) + (k1 >> 3)
        kern1_select = k1[2:0]
        load_state = 7
    elif load_phase == 7:
        font_addr_a = uint10_t(METADATA_BASE) + uint10_t(prefetched_gid)
        font_addr_b = row_lookup.address
        row_ink = row_lookup.ink
        row_select = row_lookup.byte_select
        amount_previous = uint4_t(font_b >> (uint5_t(kern1_select) << 2))
        step_older = int7_t(older_width) + SPACING - int7_t(saved_older_amount)
        load_state = 6
    elif load_phase == 6:
        # Consume the old row/current packet before accepting the new metadata
        # on A. The saved pattern ID feeds a request only in the next phase.
        row_id: uint8_t = uint8_t(font_b >> (uint5_t(row_select) << 3))
        pattern_id = (uint9_t(current_meta[31]) << 8) | uint9_t(row_id)
        pending_valid = current_valid
        pending_meta = current_meta
        pending_ink = row_ink
        pending_kind = current_kind
        pending_index = current_index
        pending_after = current_after
        step_previous = int7_t(previous_width) + SPACING - int7_t(saved_previous_amount)
        candidate_older = older_origin + int13_t(step_older)
        # Register metadata-derived crop address instead of forwarding it to
        # BRAM. Raw crop and prepared row have their own later register cuts.
        current_meta = font_a
        crop_select = font_a[11]
        crop_address = uint10_t(CROP_BASE) + uint10_t(font_a[15:12])
        current_valid = prefetched_valid
        current_kind = prefetched_kind
        current_index = read_index - 1
        current_after = read_index
        if prefetched_kind == 2:
            current_after = row_snapshot_end
        load_state = 3

    # Prefetch while capturing the crop response; hold that map in phase 5
    # until the previous glyph can be published.
    launch_next: uint1_t = (load_phase == 2) | (load_phase == 4)
    if (~reset_request) & (~stop_request) & launch_next:
        cp: uint24_t = codepoint
        prefetched_valid = ~source_done
        prefetched_kind = 0
        page_present = 0
        map_overlay = 0
        page_glyph_base = 0
        page_glyph_count = 0
        map_select = cp[1:0]
        font_addr_a = 0
        for prefix, map_base, glyph_base, count, overlay in PAGES:
            if cp[23:8] == prefix:
                page_present = 1
                page_glyph_base = uint8_t(glyph_base)
                page_glyph_count = uint9_t(count)
                map_overlay = overlay
                font_addr_a = uint10_t(map_base) + uint10_t(cp[7:2])
                if overlay:
                    font_addr_a = uint10_t(map_base) + uint10_t(cp[7:0])
        if read_index >= row_snapshot_end:
            prefetched_kind = 2
            source_done = 1
        elif cp == 10:
            prefetched_kind = 1
            source_done = 1
        elif cp < 32:
            prefetched_kind = 3
        byte_read_index = uint12_t(read_index + 1)
        read_index = read_index + 1
        load_state = 5

    font_request_a = font_addr_a
    font_request_b = font_addr_b

    if wr_en:
        written = write_tail
    # Consume the old value above before capturing the synchronous RAM output.
    codepoint = chars.p1.rd_data
    decoded = uart_codepoints(received)

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
