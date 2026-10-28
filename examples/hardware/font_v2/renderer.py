# pyright: reportInvalidTypeForm=none
"""Backpressured glyph rows with Unicode lookup and two-glyph kerning.

No pins, UART, VGA timing, text storage, font storage, or pixel FIFO are owned
here. Call once per clock. Text and font responses come from synchronous
one-clock memories; returned addresses drive their next reads. Keep config,
row_y, text_end, and origin stable during a row. Pulse start with start_index;
take consumes a valid row. stop or !font_ready flushes the reader. A start
resets history and discards any old output. kind: 0 glyph, 1 LF, 2 text end.
"""
from pypeline import *
from hardware.font_v2.types import font_v2_config_t, glyph_row_t, glyph_reader_t
from hardware.font_v2.mapping import lookup_unicode_page
from hardware.font_v2.row_address import capture_row_address, row_address_input_t


@hw_func
def read_glyph_row(config: font_v2_config_t, font_ready: uint1_t,
                   text_data: uint24_t, font_a: uint32_t, font_b: uint32_t,
                   row_y: uint6_t, text_end: uint12_t, start_index: uint12_t,
                   origin: int13_t, start: uint1_t, stop: uint1_t,
                   take: uint1_t) -> glyph_reader_t:
    read_index: Reg[uint12_t] = 0
    byte_read_index: Reg[uint12_t] = 0
    previous_class: Reg[uint5_t] = 0
    previous_width: Reg[uint5_t] = 0
    previous_origin: Reg[int13_t] = 0
    older_class: Reg[uint5_t] = 0
    older_width: Reg[uint5_t] = 0
    older_origin: Reg[int13_t] = 0
    history_count: Reg[uint2_t] = 0
    amount_previous: Reg[uint4_t] = 0
    amount_older: Reg[uint4_t] = 0
    step_previous: Reg[int7_t] = 0
    step_older: Reg[int7_t] = 0
    candidate_previous: Reg[int13_t] = 0
    candidate_older: Reg[int13_t] = 0
    prefer_older: Reg[uint1_t] = 0
    saved_prefer_older: uint1_t = prefer_older
    # Both candidates are stable by phase 4, before publication in phase 5.
    # Keep this comparison off publication's history-count/selection path.
    prefer_older = candidate_older > candidate_previous
    codepoint: Reg[uint24_t] = 0
    prefetch_ready: Reg[uint2_t] = 0
    load_state: Reg[uint3_t] = 0  # idle, warmup, launch, and five overlapped read phases
    font_addr_a: Reg[uint10_t] = 0
    font_addr_b: Reg[uint10_t] = 0
    prefetched_local: Reg[uint8_t] = 0
    prefetched_kind: Reg[uint2_t] = 3
    prefetched_valid: Reg[uint1_t] = 0
    current_meta: Reg[uint32_t] = 0
    current_valid: Reg[uint1_t] = 0
    current_kind: Reg[uint2_t] = 3
    current_index: Reg[uint12_t] = 0
    current_after: Reg[uint12_t] = 0
    source_done: Reg[uint1_t] = 0
    page_present: Reg[uint1_t] = 0
    page_metadata_base: Reg[uint10_t] = 0
    page_glyph_count: Reg[uint9_t] = 0
    map_select: Reg[uint2_t] = 0
    map_overlay: Reg[uint1_t] = 0
    crop_select: Reg[uint1_t] = 0
    crop_address: Reg[uint10_t] = 0
    row_select: Reg[uint2_t] = 0
    kern1_select: Reg[uint3_t] = 0
    kern2_select: Reg[uint3_t] = 0
    previous_kern_address: Reg[uint10_t] = 0
    older_kern_address: Reg[uint10_t] = 0
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

    saved_row: glyph_row_t = mail
    saved_valid: uint1_t = mail_valid & font_ready & (~start) & (~stop)
    text_address: uint12_t = byte_read_index
    take_mail: uint1_t = take & mail_valid
    mail_available: uint1_t = (~mail_valid) | take_mail
    if take_mail:
        mail_valid = 0
    mapped_page = lookup_unicode_page(codepoint, config)
    row_lookup = capture_row_address(row_address_input_t(
        crop_word=uint32_t(crop), crop_select=0, y=row_y,
        glyph_base=current_meta[10:0], rows_base=uint10_t(config.rows_base)), load_phase == 5)

    # Requests depend on the registered read phase, not the compositor's
    # reset/stop priority chain. Speculative requests during a pipeline flush
    # are discarded; stalled phase 5 must keep A's map and B's older kerning.
    # Masked parallel selection avoids a deep mux into the BRAM address pins.
    request_crop: uint1_t = load_phase == 3
    request_meta: uint1_t = load_phase == 7
    request_map: uint1_t = (load_phase == 2) | (load_phase == 4)
    request_older: uint1_t = load_phase == 4
    request_previous: uint1_t = (load_phase == 5) & ((~pending_valid) | mail_available)
    metadata_candidate: uint10_t = page_metadata_base + uint10_t(prefetched_local)
    metadata_address: uint10_t = config.metadata_base
    if page_present & (uint9_t(prefetched_local) < page_glyph_count):
        metadata_address = metadata_candidate
    pattern_address: uint10_t = uint10_t(config.patterns_base) + uint10_t(pattern_id)
    next_a: uint10_t = 0
    next_b: uint10_t = 0
    if request_crop:
        next_a = next_a | crop_address
        next_b = next_b | pattern_address
    if request_meta:
        next_a = next_a | metadata_address
        next_b = next_b | row_lookup.address
    if request_map:
        next_a = next_a | mapped_page.map_address
    if request_older:
        next_b = next_b | older_kern_address
    if request_previous:
        next_b = next_b | previous_kern_address
    if not (request_crop | request_meta | request_map):
        next_a = next_a | font_addr_a
    if not (request_crop | request_meta | request_older | request_previous):
        next_b = next_b | font_addr_b
    font_addr_a = next_a
    font_addr_b = next_b

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
    if start:
        read_index = start_index
        byte_read_index = uint12_t(start_index)
        history_count = 0
        previous_origin = origin
        older_origin = origin
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
    elif stop:
        current_valid = 0
        pending_valid = 0
        mail_valid = 0
        load_state = 0
    elif load_phase == 1:
        # Warm text BRAM, codepoint, and registered Unicode page selection.
        if prefetch_ready == 2:
            load_state = 2
        prefetch_ready = prefetch_ready + 1
    elif load_phase == 3:
        # Both requests consume old address/ID registers. No ROM output feeds
        # another ROM address in the same clock.
        # Forecast both classes after publication, before the mailbox can
        # stall. Do not chain publication's history updates into BRAM addresses.
        k1_class: uint5_t = previous_class
        k2_class: uint5_t = older_class
        if pending_valid & (pending_kind == 0):
            k1_class = pending_meta[20:16]
            k2_class = previous_class
        k1: uint10_t = (uint10_t(k1_class) << 5) | uint10_t(current_meta[25:21])
        k2: uint10_t = (uint10_t(k2_class) << 5) | uint10_t(current_meta[25:21])
        previous_kern_address = uint10_t(config.kerning_base) + (k1 >> 3)
        older_kern_address = uint10_t(config.kerning_base) + (k2 >> 3)
        kern1_select = k1[2:0]
        kern2_select = k2[2:0]
        candidate_previous = previous_origin + int13_t(step_previous)
        load_state = 4
    elif load_phase == 4:
        crop = font_a[11:0]
        if crop_select:
            crop = font_a[27:16]
        pattern_bits = font_b[20:0]
        load_state = 5
    elif (load_phase == 5) & ((~pending_valid) | mail_available):
        # Publication is the only stall point. A holds the map response and
        # B holds older kerning. Crop and saved pattern stay stable.
        if pending_valid & (pending_kind != 3):
            placed_origin: int13_t = origin
            if history_count != 0:
                placed_origin = candidate_previous
            if (history_count == 2) & saved_prefer_older:
                placed_origin = candidate_older
            bits: uint21_t = 0
            if pending_ink:
                bits = pattern_bits
            mail = glyph_row_t(bits=bits, width=pending_meta[30:26], backtrack=0,
                               origin=placed_origin, index=pending_index, after=pending_after,
                               kind=pending_kind)
            mail_valid = 1
            if pending_kind == 0:
                older_class = previous_class
                older_width = previous_width
                older_origin = previous_origin
                previous_class = pending_meta[20:16]
                previous_width = pending_meta[30:26]
                previous_origin = placed_origin
                if history_count < 2:
                    history_count = history_count + 1
        local: uint8_t = uint8_t(font_a >> (uint5_t(map_select) << 3))
        if map_overlay:
            local = font_a[28:21]
        # Missing entries and absent Unicode pages use glyph 0 (.notdef).
        # Keep ordinary glyph tokens so fallback ink and advance are retained.
        # Capture selection before comparing the map byte against the loaded
        # page count. The next phase validates the registered byte.
        prefetched_local = local
        load_state = 7
    elif load_phase == 7:
        # Candidate arithmetic and validity run in parallel from registers;
        # selecting fallback must follow the addition, not precede it.
        row_ink = row_lookup.ink
        row_select = row_lookup.byte_select
        amount_previous = uint4_t(font_b >> (uint5_t(kern1_select) << 2))
        step_older = int7_t(older_width) + int7_t(config.spacing) - int7_t(saved_older_amount)
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
        step_previous = int7_t(previous_width) + int7_t(config.spacing) - int7_t(saved_previous_amount)
        candidate_older = older_origin + int13_t(step_older)
        # Register metadata-derived crop address instead of forwarding it to
        # BRAM. Raw crop and prepared row have their own later register cuts.
        current_meta = font_a
        crop_select = font_a[11]
        crop_address = uint10_t(config.crop_base) + uint10_t(font_a[15:12])
        current_valid = prefetched_valid
        current_kind = prefetched_kind
        current_index = read_index - 1
        current_after = read_index
        if prefetched_kind == 2:
            current_after = text_end
        load_state = 3

    # Prefetch while capturing the crop response; hold that map in phase 5
    # until the previous glyph can be published.
    launch_next: uint1_t = (load_phase == 2) | (load_phase == 4)
    if (~start) & (~stop) & launch_next:
        cp: uint24_t = mapped_page.codepoint
        prefetched_valid = ~source_done
        prefetched_kind = 0
        page_present = mapped_page.present
        map_overlay = mapped_page.overlay
        page_metadata_base = config.metadata_base + uint10_t(mapped_page.glyph_base)
        page_glyph_count = mapped_page.glyph_count
        map_select = cp[1:0]
        if read_index >= text_end:
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

    if not font_ready:
        load_state = 0
        mail_valid = 0
    # Capture the synchronous text response after all consumers used old CP.
    codepoint = text_data
    return glyph_reader_t(row=saved_row, valid=saved_valid,
        text_address=text_address, font_address_a=font_addr_a,
        font_address_b=font_addr_b)
