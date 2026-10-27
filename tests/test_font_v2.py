"""The new font image reconstructs the independent column-major reference."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'examples'), str(ROOT/'scripts')]
from hardware import red2_font_v2_data as font
from hardware import red2_row_data as old
from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES
from generate_font_v2 import compile_font


def field(base, index, bits):
    per_word = 32//bits
    return (font.FONT_WORDS[base+index//per_word] >> (bits*(index%per_word))) & ((1<<bits)-1)


def pattern(p):
    return font.FONT_WORDS[font.PATTERNS_BASE+p] & ((1<<21)-1)


class FontV2Tests(unittest.TestCase):
    def test_all_glyph_rows_match_columns(self):
        for gid, code in enumerate(font.SOURCE_CODES):
            meta = font.FONT_WORDS[font.METADATA_BASE+gid]
            crop = field(font.CROP_BASE, (meta >> 11) & 31, 16)
            top, height, mirror = crop & 31, (crop >> 5) & 63, bool(crop & 2048)
            bank, base = meta >> 31, meta & 2047
            desc = DESCRIPTORS[code]
            width, column = (desc >> 11) & 255, desc & 2047
            self.assertEqual((meta >> 26) & 31, width)
            for y in range(32):
                actual = 0
                if top <= y < top+height:
                    row = y-top
                    if mirror:
                        row = min(row, height-1-row)
                    self.assertLess(base+row, font.ROW_BYTE_COUNT)
                    row_id = field(font.ROWS_BASE, base+row, 8)
                    self.assertLess((bank << 8) | row_id, font.PATTERN_COUNT)
                    actual = pattern((bank << 8) | row_id)
                expected = sum(((COLUMNS[column+x] >> y) & 1) << x for x in range(width))
                self.assertEqual(actual, expected, (code,y))

    def test_unicode_pages_including_all_holes(self):
        expected = {code if code < 128 else old.UNICODE_CODEPOINTS[code-128]: gid
                    for gid, code in enumerate(font.SOURCE_CODES) if code != 0}
        for prefix, base, first, count, overlay in font.PAGES:
            for low in range(256):
                local = ((font.FONT_WORDS[base+low] >> 21) & 255
                         if overlay else field(base, low, 8))
                self.assertEqual(first+local if local < count else 0,
                                 expected.get((prefix << 8) | low, 0))

    def test_every_kerning_pair_matches_independent_advances(self):
        for left_gid, left_code in enumerate(font.SOURCE_CODES):
            lm = font.FONT_WORDS[font.METADATA_BASE+left_gid]
            for right_gid, right_code in enumerate(font.SOURCE_CODES):
                rm = font.FONT_WORDS[font.METADATA_BASE+right_gid]
                k = 32*((lm >> 16) & 31) + ((rm >> 21) & 31)
                self.assertEqual(((lm >> 26) & 31)+font.SPACING-field(font.KERNING_BASE,k,4),
                                 ADVANCES[(left_code << 8) | right_code])

    def test_pattern_and_unicode_fields_do_not_overlap(self):
        self.assertEqual(font.PAGES[0], (0, font.PATTERNS_BASE, 1, 69, 1))
        for i in range(font.PATTERN_COUNT):
            word = font.FONT_WORDS[font.PATTERNS_BASE+i]
            self.assertEqual(word >> 29, 0)
            if i >= 256:
                self.assertEqual(word >> 21, 0)

    def test_small_ascii_font_explicitly_reserves_overlay_words(self):
        source = SimpleNamespace(**vars(old))
        source.METADATA = tuple(meta if code in (0, ord('A')) else meta & ~256
                                for code, meta in enumerate(old.METADATA))
        small = compile_font(source)
        self.assertEqual(small['PATTERN_COUNT'], 256)
        self.assertLess(small['USED_BYTES'], 4096)
        prefix, base, first, count, overlay = small['PAGES'][0]
        self.assertEqual((prefix, base, first, count, overlay),
                         (0, small['PATTERNS_BASE'], 1, 1, 1))
        for low in range(256):
            self.assertEqual((small['FONT_WORDS'][base+low] >> 21) & 255,
                             0 if low == ord('A') else 255)

    def test_reproducible_export_and_one_block_capacity(self):
        generated = compile_font(old)
        self.assertEqual(generated['FONT_WORDS'], font.FONT_WORDS)
        self.assertEqual(font.USED_BYTES, 3360)
        self.assertEqual(font.KERNING_BASE % 128, 0)
        self.assertEqual(font.PATTERNS_BASE % 512, 0)
        self.assertEqual(len(font.FONT_WORDS),1024)
        self.assertEqual((font.GLYPH_COUNT,font.CROP_COUNT,font.PATTERN_COUNT),(85,29,264))


if __name__ == '__main__':
    unittest.main()
