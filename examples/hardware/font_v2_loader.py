# pyright: reportInvalidTypeForm=none
"""Boot a font from the default program-data address, in the pixel clock domain."""
from pypeline import *
from hardware import QSPI
from hardware.qspi_burst import read_burst
from hardware.font_v2_format import (MAGIC, VERSION, HEADER_BYTES, HEADER_WORDS,
                                    PAYLOAD_WORDS, PAGE_WORD_BASE, MAX_PAGES)

FONT_FLASH_OFFSET = 0x220000


@struct
class font_v2_config_t(NamedTuple):
    metadata_base: uint10_t
    crop_base: uint10_t
    rows_base: uint10_t
    kerning_base: uint10_t
    patterns_base: uint10_t
    spacing: uint5_t
    page_count: uint4_t
    pages_a: uint32_t[MAX_PAGES]
    pages_b: uint17_t[MAX_PAGES]


@struct
class font_v2_load_t(NamedTuple):
    config: font_v2_config_t
    ready: uint1_t
    error: uint1_t
    write_enable: uint1_t
    write_address: uint10_t
    write_data: uint32_t


@hw_func
def consume_font_word(word: uint32_t, valid: uint1_t, io_error: uint1_t,
                      reset: uint1_t = 0) -> font_v2_load_t:
    """Accept ordered words; validate the header before allowing BRAM writes.

    Header and page directory are registers. Only payload words go to BRAM.
    ready is sticky and follows the final payload write and checksum check.
    """
    index: Reg[uint11_t] = 0
    # One-hot header position avoids a distributed index-decode/priority path
    # into every header register's clock enable. It becomes zero for payload.
    header_slot: Reg[uint40_t] = 1
    slot: uint40_t = header_slot
    checksum: Reg[uint32_t] = 0
    config: Reg[font_v2_config_t]
    ready: Reg[uint1_t] = 0
    error: Reg[uint1_t] = 0
    used_words: Reg[uint11_t] = 0
    glyph_count: Reg[uint9_t] = 0
    # Cache table capacities at their base words. Count validation then needs
    # a comparison, rather than rounding + adding a base + comparing in one tick.
    metadata_capacity: Reg[uint11_t] = 0
    crop_capacity: Reg[uint12_t] = 0
    row_capacity: Reg[uint13_t] = 0
    pattern_capacity: Reg[uint11_t] = 0
    kerning_limit: Reg[uint11_t] = 0
    packed_map_limit: Reg[uint11_t] = 0
    overlay_map_limit: Reg[uint11_t] = 0
    # Return the register outputs, not the forwarded writes below. Otherwise
    # header validation and page updates join the renderer's address paths.
    saved_config: font_v2_config_t = config
    saved_ready: uint1_t = ready
    saved_error: uint1_t = error
    saved_used_words: uint11_t = used_words
    saved_glyph_count: uint9_t = glyph_count
    saved_packed_map_limit: uint11_t = packed_map_limit
    saved_overlay_map_limit: uint11_t = overlay_map_limit
    # Validate each field in parallel, then reduce the registered fault bits.
    # An if/elif chain forwarding one error bit through all page slots creates
    # a long priority mux even though the word indices are mutually exclusive.
    faults: Reg[uint25_t] = 0
    finishing: Reg[uint1_t] = 0
    if io_error | (faults != 0):
        error = 1
        ready = 0
    if finishing:
        # Compare the completed checksum register, after its final addition.
        if checksum != 0:
            error = 1
        ready = ~error
    faults = 0
    checks: uint1_t[25] = [0]*25
    finishing = 0
    write_enable: uint1_t = 0
    write_address: uint10_t = 0
    if valid & (~error) & (~ready):
        checksum = checksum + word
        checks[0] = slot[0] & (word != MAGIC)
        checks[1] = slot[1] & (word != VERSION)
        checks[2] = slot[2] & (word != HEADER_BYTES)
        checks[3] = slot[3] & (word != PAYLOAD_WORDS)
        checks[4] = slot[4] & ((word < 512) | (word > 4096) | (word[1:0] != 0))
        checks[5] = slot[5] & (word >= used_words)
        checks[6] = slot[6] & (word >= used_words)
        checks[7] = slot[7] & (word >= used_words)
        checks[8] = slot[8] & (word > kerning_limit)
        checks[9] = slot[9] & (word >= used_words)
        checks[10] = slot[10] & ((word == 0) | (word > 256) | (word > metadata_capacity))
        checks[11] = slot[11] & ((word == 0) | (word > 32) | (word > crop_capacity))
        checks[12] = slot[12] & ((word > 2048) | (word > row_capacity))
        checks[13] = slot[13] & ((word == 0) | (word > 512) | (word > pattern_capacity))
        checks[14] = slot[14] & (word > 31)
        checks[15] = slot[15] & ((word == 0) | (word > MAX_PAGES))
        checks[16] = (slot[23:17] != 0) & (word != 0)
        if slot[4]:
            used_words = uint11_t(word >> 2)
            kerning_limit = used_words - 128
            packed_map_limit = used_words - 64
            overlay_map_limit = used_words - 256
        if slot[5]:
            config.metadata_base = uint10_t(word)
            metadata_capacity = saved_used_words - uint11_t(word)
        if slot[6]:
            config.crop_base = uint10_t(word)
            crop_capacity = uint12_t(saved_used_words - uint11_t(word)) << 1
        if slot[7]:
            config.rows_base = uint10_t(word)
            row_capacity = uint13_t(saved_used_words - uint11_t(word)) << 2
        if slot[8]:
            config.kerning_base = uint10_t(word)
        if slot[9]:
            config.patterns_base = uint10_t(word)
            pattern_capacity = saved_used_words - uint11_t(word)
        if slot[10]:
            glyph_count = uint9_t(word)
        if slot[14]:
            config.spacing = uint5_t(word)
        if slot[15]:
            config.page_count = uint4_t(word)
        for i in range(MAX_PAGES):
            present: uint1_t = i < saved_config.page_count
            map_limit: uint11_t = saved_packed_map_limit
            if word[26]:
                map_limit = saved_overlay_map_limit
            map_bad: uint1_t = (word[31:27] != 0) | (word[15:0] > 0x10ff) | ((uint11_t(word[25:16])) > map_limit) | (word[26] & (saved_used_words < 256))
            glyph_bad: uint1_t = (word[31:17] != 0) | (word[7:0] == 0) | (word[16:8] == 0) | (word[16:8] > 255) | ((uint10_t(word[7:0]) + uint10_t(word[16:8])) > uint10_t(saved_glyph_count))
            checks[17+i] = ((slot[PAGE_WORD_BASE + 2*i] & present & map_bad)
                            | (slot[PAGE_WORD_BASE + 2*i + 1] & present & glyph_bad)
                            | ((slot[PAGE_WORD_BASE + 2*i] | slot[PAGE_WORD_BASE + 2*i + 1]) & (~present) & (word != 0)))
            if slot[PAGE_WORD_BASE + 2*i] & present:
                config.pages_a[i] = word
            if slot[PAGE_WORD_BASE + 2*i + 1] & present:
                config.pages_b[i] = uint17_t(word)
        if index >= HEADER_WORDS:
            write_enable = 1
            write_address = uint10_t(index - HEADER_WORDS)
            if index == (HEADER_WORDS + PAYLOAD_WORDS - 1):
                finishing = 1
        header_slot = header_slot << 1
        index = index + 1
    for i in range(25):
        faults = faults | (uint25_t(checks[i]) << i)
    if reset:
        header_slot = 1
        index = 0
        checksum = 0
        ready = 0
        error = 0
        faults = 0
        finishing = 0
        write_enable = 0
        saved_ready = 0
        saved_error = 0
    return font_v2_load_t(config=saved_config, ready=saved_ready, error=saved_error,
                          write_enable=write_enable, write_address=write_address,
                          write_data=word)


@struct
class font_v2_boot_t(NamedTuple):
    font: font_v2_load_t
    flash: QSPI.qspi_flash_byte_io_t
    busy: uint1_t
    done: uint1_t


@hw_func
def load_font_from_qspi(dq: uint4_t, blank_start: uint1_t = 0,
                        blank_deadline: uint1_t = 0,
                        reload: uint1_t = 0,
                        clear_error: uint1_t = 0) -> font_v2_boot_t:
    """Load at boot or on a reload pulse; done marks successful publication.

    Flash ownership and physical pin routing belong to the caller. This loader
    starts no flash transfers while idle, so its idle state is quiescent.
    """
    # INIT, QE wait, preflight start/read, wait-vblank, copy start/read,
    # publish, idle. Preflight changes neither BRAM nor active config.
    phase: Reg[uint4_t] = 0
    active_config: Reg[font_v2_config_t]
    active_ready: Reg[uint1_t] = 0
    update_error: Reg[uint1_t] = 0
    runtime_copy: Reg[uint1_t] = 0
    assembled: Reg[uint32_t] = 0
    byte_index: Reg[uint2_t] = 0
    word: Reg[uint32_t] = 0
    word_valid: Reg[uint1_t] = 0
    cycle_phase: uint4_t = phase
    saved_config: font_v2_config_t = active_config
    saved_ready: uint1_t = active_ready
    saved_error: uint1_t = update_error
    parser_reset: uint1_t = (cycle_phase == 2) | (cycle_phase == 5)
    parsed = consume_font_word(word, word_valid, uint1_t(0), parser_reset)
    word_valid = 0
    initialization = QSPI.flash_byte_io(dq, uint2_t(0), uint32_t(0), uint8_t(0),
                                       uint1_t(cycle_phase == 0))
    timed_out: uint1_t = (cycle_phase == 6) & runtime_copy & blank_deadline
    burst = read_burst(dq, parser_reset, uint24_t(FONT_FLASH_OFFSET),
                       uint13_t(HEADER_BYTES + 4096), parsed.error | timed_out)
    if burst.valid:
        assembled = assembled | (uint32_t(burst.pins.read_data) << (uint5_t(byte_index) << 3))
        if byte_index == 3:
            word = assembled
            word_valid = 1
            assembled = 0
        byte_index = byte_index + 1
    if parser_reset:
        assembled = 0
        byte_index = 0
        word_valid = 0
    if cycle_phase == 0:
        phase = 1
    elif cycle_phase == 1:
        if initialization.ready:
            if initialization.quad_enabled:
                phase = 2
            else:
                update_error = 1
                phase = 8
    elif cycle_phase == 2:
        phase = 3
    elif cycle_phase == 3:
        if parsed.error:
            update_error = 1
            phase = 8
        elif parsed.ready & burst.pins.ready:
            phase = 4
    elif cycle_phase == 4:
        # Bootstrap has no visible old font to preserve. Live replacement must
        # begin at the first blank line, never partway through the interval.
        if (~active_ready) | blank_start:
            runtime_copy = active_ready
            active_ready = 0
            phase = 5
    elif cycle_phase == 5:
        phase = 6
    elif cycle_phase == 6:
        if parsed.error | timed_out:
            # A failed in-place copy cannot restore the previous BRAM. Keep
            # the display disabled until a subsequent successful upload.
            active_ready = 0
            update_error = 1
            phase = 8
        elif parsed.ready & burst.pins.ready:
            phase = 7
    elif cycle_phase == 7:
        active_config = parsed.config
        active_ready = 1
        update_error = 0
        phase = 8
    elif cycle_phase == 8:
        if reload:
            phase = 0
    if clear_error:
        update_error = 0
    flash = burst.pins
    if cycle_phase <= 1:
        flash = initialization
    write_enable: uint1_t = (cycle_phase == 6) & parsed.write_enable & (~timed_out)
    font = font_v2_load_t(config=saved_config, ready=saved_ready, error=saved_error,
        write_enable=write_enable, write_address=parsed.write_address,
        write_data=parsed.write_data)
    return font_v2_boot_t(font=font, flash=flash,
                          busy=uint1_t(cycle_phase != 8), done=uint1_t(cycle_phase == 7))
