# pyright: reportInvalidTypeForm=none
"""One explicit register boundary for the font-v2 renderer's row address."""
from pypeline import *


@struct
class row_address_input_t(NamedTuple):
    crop_word: uint32_t
    crop_select: uint1_t
    y: uint6_t
    glyph_base: uint11_t
    rows_base: uint10_t


@struct
class row_address_t(NamedTuple):
    address: uint10_t
    byte_select: uint2_t
    ink: uint1_t


@struct
class row_address_stage_t(NamedTuple):
    folded: uint6_t
    physical_base: uint12_t
    base_low: uint6_t
    base_high_full: uint1_t
    ink: uint1_t


@hw_func
def prepare_row_address(i: row_address_input_t) -> row_address_stage_t:
    crop: uint16_t = uint16_t(i.crop_word)
    if i.crop_select:
        crop = i.crop_word[31:16]
    top: uint6_t = uint6_t(crop[4:0])
    height: uint6_t = crop[10:5]
    from_top: uint7_t = uint7_t(i.y) - uint7_t(top)
    forward: uint6_t = from_top[5:0]
    # Compute the other direction directly from the inputs, avoiding a
    # dependence on the forward subtraction. All row arithmetic wraps at 6 bits.
    reflected: uint6_t = top + height + (~i.y)
    height_difference: uint7_t = uint7_t(forward) - uint7_t(height)
    within_height: uint1_t = height_difference[6]
    midpoint_difference: uint6_t = uint6_t(forward[4:0]) - uint6_t(height[5:1])
    past_midpoint: uint1_t = ~midpoint_difference[5]
    # For visible rows this is the midpoint test. Combining it with the height
    # test also preserves min(forward, reflected) for all wrapped blank rows.
    use_reflected: uint1_t = past_midpoint & within_height
    if forward[5]:
        use_reflected = past_midpoint | within_height
    folded: uint6_t = forward
    if crop[11] & use_reflected:
        folded = reflected
    ink: uint1_t = (~from_top[6]) & within_height
    # Incorporate the header's row-pool base in parallel with crop arithmetic,
    # so no second word-address addition follows row selection after the cut.
    physical_base: uint12_t = (uint12_t(i.rows_base) << 2) + uint12_t(i.glyph_base)
    return row_address_stage_t(folded=folded, physical_base=physical_base,
        base_low=i.glyph_base[5:0], base_high_full=i.glyph_base[10:6] == 31,
        ink=ink)


@hw_func
def finish_row_address(s: row_address_stage_t) -> row_address_t:
    physical: uint12_t = s.physical_base + uint12_t(s.folded)
    address: uint10_t = physical[11:2]
    # Preserve the original 11-bit row-stream offset's wrap, even for a base
    # at its boundary. A carry beyond bit 10 subtracts 512 words (toggles bit 9).
    # This small carry calculation runs alongside the physical-address adder.
    low_sum: uint7_t = uint7_t(s.base_low) + uint7_t(s.folded)
    wrapped: uint1_t = s.base_high_full & low_sum[6]
    address = address ^ (uint10_t(wrapped) << 9)
    return row_address_t(address=address, byte_select=physical[1:0], ink=s.ink)


@hw_func
def calculate_row_address(i: row_address_input_t) -> row_address_t:
    return finish_row_address(prepare_row_address(i))


@hw_func
def row_address(i: row_address_input_t) -> row_address_t:
    row_register: Reg[row_address_stage_t]
    # Read before assignment: Pypeline otherwise forwards the new value.
    result = finish_row_address(row_register)
    row_register = prepare_row_address(i)
    return result


@hw_func
def capture_row_address(i: row_address_input_t, capture: uint1_t) -> row_address_t:
    row_register: Reg[row_address_stage_t]
    result = finish_row_address(row_register)
    if capture:
        row_register = prepare_row_address(i)
    return result


ROW_ADDRESS_LATENCY = 1
