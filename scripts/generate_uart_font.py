#!/usr/bin/env python3
"""Export raw RED2 artwork and kerning as ordinary Pypeline ROM constants."""
import argparse
from pathlib import Path
import sys
import runpy
import tempfile
from font_glyph_ids import assign_glyph_ids

ROOT = Path(__file__).resolve().parents[1]


def pack_kerning(data):
    """Overlay padded four-bit kerning on unused high bits of row/padding words."""
    depth = 1 << (data['KERNING_LEFT_BITS'] + data['KERNING_RIGHT_BITS'])
    base = 2048 - depth
    if base < data['FONT_INDEX_BASE']:
        raise ValueError('Kerning overlaps bitmap dictionary; it cannot share the font BRAM')
    words = list(data['FONT_WORDS'])
    left_count, right_count = data['KERNING_LEFT_COUNT'], data['KERNING_RIGHT_COUNT']
    for left in range(1 << data['KERNING_LEFT_BITS']):
        for right in range(data['KERNING_STRIDE']):
            address = base | (left << data['KERNING_RIGHT_BITS']) | right
            if words[address] >= 512:
                raise ValueError('Kerning storage overlaps occupied font bits')
            kern = data['KERNING'][left * right_count + right] if left < left_count and right < right_count else 0
            if not 0 <= kern <= 15:
                raise ValueError('Kerning adjustment must fit four unsigned bits')
            words[address] |= kern << 12
    return base, words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=ROOT.parent / 'red2-font')
    parser.add_argument('--aseprite', default='aseprite')
    args = parser.parse_args()
    sys.path.insert(0, str(args.font_dir.resolve()))
    from src.font import load_glyphs
    from src.pipeline import prepare_font
    from src.bram import export_bram
    from src.specimen import EXAMPLE_TEXT
    prepared = prepare_font(load_glyphs(args.font_dir / 'RED2 Font.aseprite', args.aseprite),
                            spacing=4, kerning_slack=2, widen_pairs=False)
    glyphs, unicode_codepoints = assign_glyph_ids(prepared.glyphs)
    # The upstream pipeline owns class selection and its exhaustive history proof.
    with tempfile.TemporaryDirectory() as temporary:
        export_bram(prepared, temporary)
        row_data = runpy.run_path(str(Path(temporary) / 'red2_bram.py'))
    kerning_base, font_words = pack_kerning(row_data)
    kerning = prepared.kerning
    glyph_ids = {code: code for code in prepared.glyphs if code < 128}
    glyph_ids.update({code: 128 + i for i, code in enumerate(unicode_codepoints)})
    columns, descriptors, advances = [], [0] * 256, [0] * (256 * 256)
    for code, glyph in sorted(glyphs.items()):
        if not 0 <= code < 256 or glyph.height > 32 or glyph.width > 255:
            raise ValueError('Expected glyph IDs 0..255, at most 255 x 32 pixels')
        descriptors[code] = len(columns) | (glyph.width << 11) | (1 << 19)
        alpha = glyph.getchannel('A')
        columns.extend(sum(bool(alpha.getpixel((x, y))) << y for y in range(glyph.height))
                       for x in range(glyph.width))
    if len(columns) > 2048:
        raise ValueError('Font exceeds the provisioned 2048 columns')
    for left, left_id in glyph_ids.items():
        for right, right_id in glyph_ids.items():
            advance = kerning.advance(left, right)
            if not -64 <= advance < 64:
                raise ValueError('Pair advance exceeds seven signed bits')
            advances[(left_id << 8) | right_id] = advance
    checked = prepared.statistics["history_combinations_checked"]
    print(f'Two-glyph history verified across {checked:,} combinations at spacing 4')
    lines = ['"""Generated from raw RED2 Aseprite slices; no R2BF dependency.',
             'Descriptor: valid bit 19, width bits 18:11, base column bits 10:0.',
             'Advance index: (previous glyph ID << 8) | current glyph ID.',
             'Bitmap bit 0 is the top pixel. Regenerate with scripts/generate_uart_font.py.',
             '"""', '']
    lines.append('UNICODE_CODEPOINTS = ' + repr(unicode_codepoints) + '\n')
    for name, values in [('DESCRIPTORS', descriptors), ('COLUMNS', columns), ('ADVANCES', advances)]:
        lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        lines.append(')\n')
    output = ROOT / 'examples/hardware/red2_uart_data.py'
    output.write_text('\n'.join(lines))
    left_count, right_count = row_data['KERNING_LEFT_COUNT'], row_data['KERNING_RIGHT_COUNT']
    print(f'Kerning classes: {left_count} left x {right_count} right; '
          f'packed in font word bits 15:12 starting at {kerning_base}')
    print(f'Packed font: {row_data["FONT_DICTIONARY_COUNT"]} patterns, '
          f'{row_data["FONT_ROW_COUNT"]} cropped rows, 2048 x 16-bit ROM')
    row_lines = ['"""RED2 row-major font and kerning in one dual-port 2048 x 16-bit ROM.',
                 'Dictionary: three little-endian bytes per pattern, bit 0 is the left pixel.',
                 'Row address = metadata base + glyph_y - top_y; row ID is bits 8:0.',
                 'Kerning: bits 15:12 at FONT_KERNING_BASE | (left_class << KERNING_RIGHT_BITS) | right_class.',
                 'Metadata: right class[42:37], left class[36:31], base[30:20],',
                 'top_y[19:15], height[14:9], valid[8], guard[7:5], width[4:0].',
                 'Pair step = previous width + SPACING - adjustment.',
                 'KERNING is the dense reference table; hardware reads FONT_WORDS.',
                 'Regenerate with scripts/generate_uart_font.py.', '"""', '']
    for name in ('SPACING', 'KERNING_SLACK', 'WIDEN_PAIRS',
                 'KERNING_LEFT_COUNT', 'KERNING_RIGHT_COUNT',
                 'KERNING_LEFT_BITS', 'KERNING_RIGHT_BITS', 'KERNING_STRIDE',
                 'FONT_DICTIONARY_COUNT', 'FONT_INDEX_BASE', 'FONT_ROW_COUNT', 'UNICODE_CODEPOINTS'):
        row_lines.append(f'{name} = {row_data[name]!r}')
    row_lines += [f'FONT_KERNING_BASE = {kerning_base}', '']
    for name, values in [('FONT_WORDS', font_words), ('METADATA', row_data['METADATA']),
                         ('KERNING', row_data['KERNING'])]:
        row_lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            row_lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        row_lines.append(')\n')
    (ROOT / 'examples/hardware/red2_row_data.py').write_text('\n'.join(row_lines))
    (ROOT / 'assets/red2-readme-example.txt').write_text(EXAMPLE_TEXT)
    print(f'Generated {len(glyphs)} glyphs, {len(columns)} columns and glyph-ID pair advances: {output}')


if __name__ == '__main__':
    main()
