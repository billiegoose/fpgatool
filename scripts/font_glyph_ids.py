"""Compact GPU/FPGA glyph IDs: ASCII unchanged, Unicode in slots 128 onward."""


def assign_glyph_ids(glyphs):
    """Return (glyphs indexed by byte-sized ID, sorted extra Unicode scalars)."""
    extra = tuple(sorted(code for code in glyphs if code >= 128))
    if len(extra) > 128:
        raise ValueError('More than 128 non-ASCII glyphs exceed eight-bit IDs')
    mapping = {code: code for code in glyphs if code < 128}
    mapping.update({code: 128 + index for index, code in enumerate(extra)})
    return {mapping[code]: glyph for code, glyph in glyphs.items()}, extra


def edited_glyph_ids(data, unicode_codepoints, capacity=8192):
    """Independent UART reference: UTF-8 decode before the glyph edit buffer."""
    import codecs
    decoder = codecs.getincrementaldecoder('utf-8')('ignore')
    lookup = {cp: 128 + index for index, cp in enumerate(unicode_codepoints)}
    result = bytearray()
    for byte in data:
        if byte in (8, 127):
            decoder.reset()
            if result:
                result.pop()
            continue
        for character in decoder.decode(bytes((byte,))):
            code = ord(character)
            glyph = code if code < 128 else lookup.get(code)
            if glyph is not None and len(result) < capacity:
                result.append(glyph)
    return result
