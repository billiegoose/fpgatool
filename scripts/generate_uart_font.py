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
    glyphs = load_glyphs(args.font_dir / 'RED2 Font.aseprite', args.aseprite)
    kerning = AutoKerning(glyphs, spacing=4)
    columns, descriptors, advances = [], [0] * 128, [0] * 16384
    for code, glyph in sorted(glyphs.items()):
        if not 0 <= code < 128 or glyph.height > 32 or glyph.width > 255:
            raise ValueError('Expected ASCII glyphs at most 255 x 32 pixels')
        descriptors[code] = len(columns) | (glyph.width << 10) | (1 << 18)
        alpha = glyph.getchannel('A')
        columns.extend(sum(bool(alpha.getpixel((x, y))) << y for y in range(glyph.height))
                       for x in range(glyph.width))
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
             'Bitmap bit 0 is the top pixel. Regenerate with scripts/generate_uart_font.py.',
             '"""', '']
    for name, values in [('DESCRIPTORS', descriptors), ('COLUMNS', columns), ('ADVANCES', advances)]:
        lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        lines.append(')\n')
    output = ROOT / 'examples/hardware/red2_uart_data.py'
    output.write_text('\n'.join(lines))
    # Row-major scanout data: one horizontal glyph row per ROM word.
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
    rows, metadata, kerns = [0] * 4096, [0] * 128, [0] * 16384
    for code, glyph in glyphs.items():
        if glyph.width > 21 or -future[code] > 7:
            raise ValueError('Row renderer expects glyphs <=21 pixels and backtracking <=7')
        metadata[code] = (1 << 8) | (-future[code] << 5) | glyph.width
        alpha = glyph.getchannel('A')
        for y in range(glyph.height):
            rows[(code << 5) | y] = sum(bool(alpha.getpixel((x, y))) << x
                                        for x in range(glyph.width))
        for right in glyphs:
            kern = glyph.width + 4 - advances[(code << 7) | right]
            if not 0 <= kern <= 15:
                raise ValueError('Kerning adjustment must fit four unsigned bits')
            kerns[(code << 7) | right] = kern
    row_lines = ['"""Raw RED2 row-major font ROMs for the streaming pixel engine.',
                 'Row address = (ASCII << 5) | glyph_y; bit 0 is the left pixel.',
                 'Metadata: valid[8], future backtrack[7:5], width[4:0].',
                 'Pair step = current width + 4 - KERNING[(current << 7) | next].',
                 'Regenerate with scripts/generate_uart_font.py.', '"""', '']
    for name, values in [('ROW_BITMAPS', rows), ('METADATA', metadata), ('KERNING', kerns)]:
        row_lines.append(name + ' = (')
        for start in range(0, len(values), 16):
            row_lines.append('    ' + ', '.join(map(str, values[start:start+16])) + ',')
        row_lines.append(')\n')
    (ROOT / 'examples/hardware/red2_row_data.py').write_text('\n'.join(row_lines))
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
