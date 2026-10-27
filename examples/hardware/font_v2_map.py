# pyright: reportInvalidTypeForm=none
"""Register Unicode page selection and its complete map read address."""
from pypeline import *
from hardware.font_v2_loader import font_v2_config_t
from hardware.font_v2_format import MAX_PAGES


@struct
class font_v2_page_t(NamedTuple):
    codepoint: uint24_t
    present: uint1_t
    map_base: uint10_t
    map_address: uint10_t
    glyph_base: uint8_t
    glyph_count: uint9_t
    overlay: uint1_t


@hw_func
def lookup_unicode_page(cp: uint24_t, config: font_v2_config_t) -> font_v2_page_t:
    selected: Reg[font_v2_page_t]
    saved: font_v2_page_t = selected
    selected = font_v2_page_t(codepoint=cp, present=0, map_base=0, map_address=0,
                              glyph_base=0, glyph_count=0, overlay=0)
    for page in range(MAX_PAGES):
        a: uint32_t = config.pages_a[page]
        b: uint17_t = config.pages_b[page]
        hit: uint1_t = (page < config.page_count) & (cp[23:8] == a[15:0])
        base: uint10_t = 0
        first: uint8_t = 0
        count: uint9_t = 0
        overlay: uint1_t = 0
        address: uint10_t = 0
        offset: uint8_t = uint8_t(cp[7:2])
        if a[26]:
            offset = cp[7:0]
        candidate: uint10_t = uint10_t(a[25:16]) + uint10_t(offset)
        if hit:
            base = a[25:16]
            address = candidate
            first = b[7:0]
            count = b[16:8]
            overlay = a[26]
        # V2 directory prefixes are unique. An OR reduction of these masked
        # fields avoids an eight-entry priority mux on every selected bit.
        selected.present = selected.present | hit
        selected.map_base = selected.map_base | base
        selected.map_address = selected.map_address | address
        selected.glyph_base = selected.glyph_base | first
        selected.glyph_count = selected.glyph_count | count
        selected.overlay = selected.overlay | overlay
    return saved
