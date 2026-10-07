#!/usr/bin/env python3
"""Compare a VGA capture with an independent column-major RED2 renderer."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES


def expected_pixels(text, width=1920, height=1080, margin_x=5, margin_y=2):
    # Apply the UART storage edits before independently laying out font columns.
    buffered = bytearray()
    for code in text:
        if code in (8, 127):
            if buffered:
                buffered.pop()
        elif len(buffered) < 8192:
            buffered.append(code)
    text = buffered
    pixels = bytearray(width * height)
    right, bottom = width - margin_x, height - margin_y
    y, history = margin_y, []
    for code in text:
        if code == 10:
            y += 36
            history = []
            continue
        if code >= 128 or not DESCRIPTORS[code] & (1 << 18):
            continue
        descriptor = DESCRIPTORS[code]
        base, glyph_width = descriptor & 1023, (descriptor >> 10) & 255
        x = max((left_x + ADVANCES[(left << 7) | code]
                 for left, left_x in history), default=margin_x)
        if x + glyph_width > right:
            y += 36
            x = margin_x
            history = []
        if y >= bottom:
            break
        for dx in range(glyph_width):
            if margin_x <= x + dx < right:
                column = COLUMNS[base + dx]
                for dy in range(min(32, bottom - y)):
                    if column & (1 << dy):
                        pixels[(y + dy) * width + x + dx] = 255
        history.append((code, x))
    return bytes(pixels)


def main():
    from PIL import Image, ImageChops
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('text', type=Path)
    args = parser.parse_args()
    actual = Image.open(args.capture).convert('RGB')
    expected = Image.frombytes('L', actual.size,
                              expected_pixels(args.text.read_bytes(), *actual.size)).convert('RGB')
    diff = ImageChops.difference(actual, expected)
    if diff.getbbox():
        path = args.capture.with_name(args.capture.stem + '-diff.png')
        diff.save(path)
        mismatches = sum(a != b for a, b in zip(actual.getdata(), expected.getdata()))
        raise SystemExit(f'{mismatches} mismatched pixels; bounds {diff.getbbox()}; {path}')
    print(f'Exact match: {actual.width}x{actual.height}, {len(args.text.read_bytes())} input bytes')


if __name__ == '__main__':
    main()
