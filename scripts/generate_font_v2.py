#!/usr/bin/env python3
"""Export the RED2 reference into the version-2, single-word-pattern font image.

All payload tables share 1024 words. Header/page-directory values are kept
separately so the renderer has no font-specific Unicode comparison logic.
"""
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pack_streams(streams):
    unique = sorted(set(s for s in streams if s))
    parts = [s for s in unique if not any(s != t and s in t for t in unique)]
    def overlap(a, b):
        return next((n for n in range(min(len(a), len(b)), 0, -1)
                     if a[-n:] == b[:n]), 0)
    while len(parts) > 1:
        n, ai, bi = max((overlap(a, b), -i, -j)
                       for i, a in enumerate(parts) for j, b in enumerate(parts) if i != j)
        i, j = -ai, -bi
        joined = parts[i] + parts[j][n:]
        parts = [s for k, s in enumerate(parts) if k not in (i, j)] + [joined]
    return parts[0] if parts else b''


def compile_font(source):
    raw = bytes(b for w in source.FONT_WORDS[:source.FONT_INDEX_BASE]
                for b in (w & 255, w >> 8))
    patterns = [int.from_bytes(raw[3*i:3*i+3], 'little')
                for i in range(source.FONT_DICTIONARY_COUNT)]
    if any(p >= (1 << 21) for p in patterns):
        raise ValueError('Bit patterns must fit the lower 21 bits of each word')
    glyphs = []
    for code, meta in enumerate(source.METADATA):
        if meta & 256:
            base, height = (meta >> 20) & 2047, (meta >> 9) & 63
            ids = tuple(w & 511 for w in source.FONT_WORDS[base:base+height])
            cp = code if code < 128 else source.UNICODE_CODEPOINTS[code-128]
            glyphs.append((code, cp, meta, ids))
    glyphs.sort(key=lambda g: -1 if g[0] == 0 else g[1])
    if len(glyphs) > 256:
        raise ValueError('This profile uses eight-bit global glyph IDs')
    all_ids = sorted({i for g in glyphs for i in g[3]})
    secondary = None
    first, second = all_ids, []
    if len(all_ids) > 256:
        candidates = []
        for glyph in glyphs:
            first_ids = sorted({i for g in glyphs if g != glyph for i in g[3]})
            second_ids = sorted(set(glyph[3]))
            if len(first_ids) <= 256 and len(second_ids) <= 256:
                candidates.append((256+len(second_ids), glyph[0], first_ids, second_ids))
        if not candidates:
            raise ValueError('This exporter requires a one- or two-bank glyph partition')
        _, secondary, first, second = min(candidates)
    banks = [first, second]
    remap = [{old: new for new, old in enumerate(bank)} for bank in banks]
    overlay_ascii = any(code != 0 and cp >> 8 == 0 for code, cp, _, _ in glyphs)
    physical = [patterns[i] for i in first]
    # Bank 1 begins at ID 256. The overlaid map also reserves exactly 256
    # words even when a small font has fewer unique patterns.
    if second or overlay_ascii:
        physical.extend([0]*(256-len(first)))
    physical.extend(patterns[i] for i in second)
    unicode_maps = []
    for prefix in sorted({cp >> 8 for code, cp, _, _ in glyphs if code != 0}):
        entries = [(cp & 255, gid) for gid, (code, cp, _, _) in enumerate(glyphs)
                   if code != 0 and cp >> 8 == prefix]
        direct = bytearray([255]*256)
        for local, (low, gid) in enumerate(entries):
            direct[low] = local
        unicode_maps.append((prefix, direct, entries[0][1], len(entries)))
    ascii_map = next((data for prefix, data, _, _ in unicode_maps if prefix == 0), None)
    streams, crops = {}, []
    for code, cp, meta, ids in glyphs:
        mirror = len(ids) > 1 and ids == ids[::-1]
        stream = ids[:(len(ids)+1)//2] if mirror else ids
        streams[code] = bytes(remap[int(code == secondary)][i] for i in stream)
        crops.append(((meta >> 15) & 31, len(ids), mirror))
    classes = sorted(set(crops))
    if len(classes) > 32:
        raise ValueError('Font needs crop-class merging before it fits this profile')
    pool = pack_streams(list(streams.values()))
    if len(pool) > 2048:
        raise ValueError('Row-byte pool exceeds eleven-bit offsets')
    image = bytearray()
    def append(data):
        base = len(image)//4
        image.extend(data)
        image.extend(bytes((-len(image)) % 4))
        return base
    metadata = []
    for glyph, crop in zip(glyphs, crops):
        code, cp, meta, ids = glyph
        base = pool.find(streams[code])
        left, right = (meta >> 31) & 63, (meta >> 37) & 63
        if max(left, right) >= 32 or meta & 224:
            raise ValueError('Five-bit classes and zero backtrack required')
        metadata.append(base | (classes.index(crop) << 11) | (left << 16)
                        | (right << 21) | ((meta & 31) << 26) | (int(code == secondary) << 31))
    metadata_base = append(b''.join(w.to_bytes(4, 'little') for w in metadata))
    crop_base = append(b''.join((t | (h << 5) | (int(m) << 11)).to_bytes(2, 'little')
                               for t, h, m in classes))
    rows_base = append(pool)
    kern = [source.KERNING[l*source.KERNING_RIGHT_COUNT+r]
            if l < source.KERNING_LEFT_COUNT and r < source.KERNING_RIGHT_COUNT else 0
            for l in range(32) for r in range(32)]
    kerning_base = append(bytes(kern[i] | (kern[i+1] << 4) for i in range(0, 1024, 2)))
    # For this image the preceding tables end at word 384. Kerning first
    # therefore aligns its 128 words and starts patterns at word 512, removing
    # address adders without padding. Bases remain explicit format data.
    pattern_base = append(b''.join(
        (p | ((ascii_map[i] if ascii_map is not None and i < 256 else 0) << 21))
        .to_bytes(4, 'little') for i, p in enumerate(physical)))
    pages = []
    for prefix, direct, first_gid, count in unicode_maps:
        # Encoding 1: one map byte in bits [28:21] of each pattern word.
        # Encoding 0: four ordinary map bytes per word.
        overlay = int(prefix == 0)
        map_base = pattern_base if overlay else append(direct)
        pages.append((prefix, map_base, first_gid, count, overlay))
    used = len(image)
    if used > 4096:
        raise ValueError(f'Font requires {used} bytes; one block holds 4096')
    image.extend(bytes(4096-used))
    return dict(FONT_FORMAT_VERSION=2, METADATA_BASE=metadata_base, CROP_BASE=crop_base, ROWS_BASE=rows_base,
                PATTERNS_BASE=pattern_base, KERNING_BASE=kerning_base, PAGES=tuple(pages),
                GLYPH_COUNT=len(glyphs), CROP_COUNT=len(classes), ROW_BYTE_COUNT=len(pool),
                PATTERN_COUNT=len(physical), USED_BYTES=used, SPACING=source.SPACING,
                SOURCE_CODES=tuple(g[0] for g in glyphs),
                FONT_WORDS=tuple(int.from_bytes(image[i:i+4], 'little') for i in range(0,4096,4)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'examples/hardware/red2_row_data.py')
    parser.add_argument('--output', type=Path, default=ROOT/'examples/hardware/red2_font_v2_data.py')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('font_source', args.source)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    data = compile_font(source)
    lines = ['"""Generated font v2; regenerate with scripts/generate_font_v2.py."""', '']
    for name, value in data.items():
        if name == 'FONT_WORDS':
            lines += ['FONT_WORDS = (']
            lines += ['    '+', '.join(str(w) for w in value[i:i+8])+',' for i in range(0,1024,8)]
            lines += [')']
        else:
            lines.append(f'{name} = {value!r}')
    args.output.write_text('\n'.join(lines)+'\n')
    print(f'{data["USED_BYTES"]}/4096 bytes; {data["GLYPH_COUNT"]} glyphs; '
          f'{data["CROP_COUNT"]} crops; {data["ROW_BYTE_COUNT"]} row bytes; '
          f'{data["PATTERN_COUNT"]} patterns')


if __name__ == '__main__':
    main()
