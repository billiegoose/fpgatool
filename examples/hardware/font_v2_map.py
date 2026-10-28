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
    lower: Reg[font_v2_page_t]
    upper: Reg[font_v2_page_t]
    saved_lower: font_v2_page_t = lower
    saved_upper: font_v2_page_t = upper
    lower = font_v2_page_t(codepoint=cp, present=0, map_base=0, map_address=0,
                              glyph_base=0, glyph_count=0, overlay=0)
    upper = font_v2_page_t(codepoint=0, present=0, map_base=0, map_address=0,
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
        # V2 prefixes are unique. Register two parallel reductions so a page
        # comparison need not route through all eight entries before the cut.
        # Combining the old groups below preserves the one-clock interface.
        if page < (MAX_PAGES // 2):
            lower.present = lower.present | hit
            lower.map_base = lower.map_base | base
            lower.map_address = lower.map_address | address
            lower.glyph_base = lower.glyph_base | first
            lower.glyph_count = lower.glyph_count | count
            lower.overlay = lower.overlay | overlay
        else:
            upper.present = upper.present | hit
            upper.map_base = upper.map_base | base
            upper.map_address = upper.map_address | address
            upper.glyph_base = upper.glyph_base | first
            upper.glyph_count = upper.glyph_count | count
            upper.overlay = upper.overlay | overlay
    return font_v2_page_t(codepoint=saved_lower.codepoint,
        present=saved_lower.present | saved_upper.present,
        map_base=saved_lower.map_base | saved_upper.map_base,
        map_address=saved_lower.map_address | saved_upper.map_address,
        glyph_base=saved_lower.glyph_base | saved_upper.glyph_base,
        glyph_count=saved_lower.glyph_count | saved_upper.glyph_count,
        overlay=saved_lower.overlay | saved_upper.overlay)
