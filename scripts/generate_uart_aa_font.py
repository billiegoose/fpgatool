#!/usr/bin/env python3
"""Export raw RED2 artwork and kerning as ordinary Pypeline ROM constants."""
import argparse
import ast
from pathlib import Path
import sys
from kerning_history import verify_two_glyph_history

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=ROOT.parent / 'red2-font')
    parser.add_argument('--aseprite', default='aseprite')
    args = parser.parse_args()
    sys.path.insert(0, str(args.font_dir.resolve()))
    from render_font import load_glyphs, AutoKerning
    from antialias_font import compile_glyph, FITTED_PALETTE
    glyphs = load_glyphs(args.font_dir / 'RED2 Font.aseprite', args.aseprite)
    kerning = AutoKerning(glyphs, spacing=4)
    aa_glyphs = {code: compile_glyph(glyph) for code, glyph in glyphs.items()}
    columns, aa_columns, descriptors, advances = [], [], [0] * 128, [0] * 16384
    for code, glyph in sorted(glyphs.items()):
        if not 0 <= code < 128 or glyph.height > 32 or glyph.width > 255:
            raise ValueError('Expected ASCII glyphs at most 255 x 32 pixels')
        descriptors[code] = len(columns) | (glyph.width << 10) | (1 << 18)
        alpha = glyph.getchannel('A')
        columns.extend(sum(bool(alpha.getpixel((x, y))) << y for y in range(glyph.height))
                       for x in range(glyph.width))
        aa = aa_glyphs[code]
        aa_columns.extend(sum(aa.getpixel((x, y)) << (2 * y) for y in range(aa.height))
                          for x in range(aa.width))
    if len(columns) > 1024:
        raise ValueError('Font exceeds the provisioned 1024 columns')
    for left in glyphs:
        for right in glyphs:
            advance = kerning.advance(left, right)
            if not -64 <= advance < 64:
                raise ValueError('Pair advance exceeds seven signed bits')
            advances[(left << 7) | right] = advance
    checked = verify_two_glyph_history(advances, sorted(glyphs))
    print(f'Two-glyph history verified across {checked:,} combinations at spacing 4')
    lines = ['"""Generated from raw RED2 Aseprite slices; no R2BF dependency.',
             'Descriptor: valid bit 18, width bits 17:10, base column bits 9:0.',
             'Advance index: (previous ASCII << 7) | current ASCII.',
             'Bitmap bit 0 is the top pixel. Regenerate with scripts/generate_uart_aa_font.py.',
             '"""', '']
    for name, values in [('DESCRIPTORS', descriptors), ('COLUMNS', columns), ('AA_COLUMNS', aa_columns), ('ADVANCES', advances)]:
        lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        lines.append(')\n')
    output = ROOT / 'examples/hardware/red2_aa_uart_data.py'
    output.write_text('\n'.join(lines))
    # Crop vertical blank margins and dictionary-code row-major scanout data.
    # Compute how far any future glyph can reach back from this glyph's origin.
    # Retain explicit guards even though this font now has nonnegative advances.
    future = {code: 0 for code in glyphs}
    for iteration in range(len(glyphs)):
        bounds = {left: min(0, min(advances[(left << 7) | right] + future[right]
                                   for right in glyphs)) for left in glyphs}
        if bounds == future:
            break
        future = bounds
    else:
        raise ValueError('Kerning has a negative cycle; finite streaming lookahead is impossible')
    row_indices, dictionary = [], [0]
    row_ids = {0: 0}
    metadata, kerns = [0] * 128, [0] * 16384
    for code, glyph in sorted(glyphs.items()):
        if glyph.width > 21 or -future[code] > 7:
            raise ValueError('Row renderer expects glyphs <=21 pixels and backtracking <=7')
        aa = aa_glyphs[code]
        bounds = aa.getbbox()
        top_y, height = (bounds[1], bounds[3] - bounds[1]) if bounds else (0, 0)
        base = len(row_indices)
        if base >= 2048:
            raise ValueError('Glyph base exceeds eleven-bit addresses')
        metadata[code] = ((base << 20) | (top_y << 15) | (height << 9)
                          | (1 << 8) | (-future[code] << 5) | glyph.width)
        for y in range(top_y, top_y + height):
            bits = sum(aa.getpixel((x, y)) << (2 * x) for x in range(glyph.width))
            if bits not in row_ids:
                row_ids[bits] = len(dictionary)
                dictionary.append(bits)
            row_indices.append(row_ids[bits])
        for right in glyphs:
            kern = glyph.width + 4 - advances[(code << 7) | right]
            if not 0 <= kern <= 15:
                raise ValueError('Kerning adjustment must fit four unsigned bits')
            kerns[(code << 7) | right] = kern
    # Group full kerning rows and columns independently, over supported glyphs.
    codes = sorted(glyphs)
    left_groups, right_groups = {}, {}
    left_ids, right_ids = {}, {}
    for code in codes:
        row_key = tuple(kerns[(code << 7) | right] for right in codes)
        col_key = tuple(kerns[(left << 7) | code] for left in codes)
        left_ids[code] = left_groups.setdefault(row_key, len(left_groups))
        right_ids[code] = right_groups.setdefault(col_key, len(right_groups))
    left_count, right_count = len(left_groups), len(right_groups)
    if left_count > 64 or right_count > 64:
        raise ValueError('Kerning classes exceed six-bit IDs')
    class_kerns = [None] * (left_count * right_count)
    for left in codes:
        for right in codes:
            address = left_ids[left] * right_count + right_ids[right]
            value = kerns[(left << 7) | right]
            if class_kerns[address] is not None and class_kerns[address] != value:
                raise ValueError('Kerning classes do not preserve pair adjustments')
            class_kerns[address] = value
        metadata[left] |= (left_ids[left] << 31) | (right_ids[left] << 37)
    if any(value is None for value in class_kerns):
        raise ValueError('Kerning class table contains an unmapped pair')
    print(f'Kerning classes: {left_count} left x {right_count} right, '
          f'{len(class_kerns)} four-bit entries')
    if len(dictionary) > 512:
        raise ValueError('AA row dictionary exceeds nine-bit indices')
    if len(row_indices) > 2048:
        raise ValueError('Cropped rows exceed eleven-bit addresses')
    dictionary_count, cropped_count = len(dictionary), len(row_indices)
    dictionary.extend([0] * (512 - len(dictionary)))
    row_indices.extend([0] * (2048 - len(row_indices)))
    print(f'AA font: {dictionary_count} distinct 42-bit patterns, '
          f'{cropped_count} cropped rows with nine-bit indices')
    row_lines = ['"""Raw RED2 row-major font ROMs for the streaming pixel engine.',
                 'Row address = base + glyph_y - top_y, only within cropped height.',
                 'ROW_DICTIONARY[ROW_INDICES[address]] packs two-bit pixels, left pixel in bits 1:0.',
                 'Palette indices 0..3 use fitted sRGB levels 0, 59, 198, 255.',
                 'Metadata: right class[42:37], left class[36:31], base[30:20],',
                 'top_y[19:15], height[14:9],',
                 'valid[8], future backtrack[7:5], width[4:0].',
                 'KERNING[left_class * KERNING_RIGHT_COUNT + right_class] is a four-bit adjustment.',
                 'Pair step = previous width + 4 - adjustment.',
                 'Regenerate with scripts/generate_uart_aa_font.py.', '"""', '',
                 f'KERNING_LEFT_COUNT = {left_count}', f'KERNING_RIGHT_COUNT = {right_count}',
                 f'FONT_DICTIONARY_COUNT = {dictionary_count}',
                 f'FONT_ROW_COUNT = {cropped_count}', f'FONT_PALETTE = {FITTED_PALETTE!r}', '']
    for name, values in [('ROW_DICTIONARY', dictionary), ('ROW_INDICES', row_indices),
                         ('METADATA', metadata), ('KERNING', class_kerns)]:
        row_lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            row_lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        row_lines.append(')\n')
    (ROOT / 'examples/hardware/red2_aa_row_data.py').write_text('\n'.join(row_lines))
    # Copy the exact README sample, without importing its tests at runtime.
    tree = ast.parse((args.font_dir / 'test_render_font.py').read_text())
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EXAMPLE_TEXT'
                                                     for t in statement.targets):
            text = ast.literal_eval(statement.value)
            (ROOT / 'assets/red2-readme-example.txt').write_text(text)
            break
    else:
        raise ValueError('Could not find the README example text')
    print(f'Generated {len(glyphs)} glyphs, {len(columns)} columns and ASCII pair advances: {output}')


if __name__ == '__main__':
    main()
