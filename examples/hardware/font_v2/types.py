# pyright: reportInvalidTypeForm=none
"""Font configuration and explicit glyph-reader memory/stream interfaces."""
from pypeline import *
from hardware.font_v2.format import MAX_PAGES


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
class glyph_row_t(NamedTuple):
    bits: uint21_t
    width: uint5_t
    backtrack: uint3_t
    origin: int13_t
    index: uint12_t
    after: uint12_t
    kind: uint2_t  # 0 glyph, 1 newline, 2 end of the snapshot.


@struct
class glyph_reader_t(NamedTuple):
    row: glyph_row_t
    valid: uint1_t
    text_address: uint12_t
    font_address_a: uint10_t
    font_address_b: uint10_t
