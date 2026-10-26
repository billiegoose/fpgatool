"""Check cropped dictionary rows and the kerning bound for settled pixels."""
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
sys.path.insert(0, str(ROOT / 'scripts'))
from kerning_history import verify_two_glyph_history
from hardware.red2_row_data import (FONT_WORDS, FONT_DICTIONARY_COUNT, FONT_INDEX_BASE, FONT_ROW_COUNT, UNICODE_CODEPOINTS, METADATA, KERNING,
                                    KERNING_LEFT_COUNT, KERNING_RIGHT_COUNT)
from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES


FONT_BYTES = tuple(byte for word in FONT_WORDS for byte in (word & 255, word >> 8))
DICTIONARY = tuple(sum(FONT_BYTES[3 * index + b] << (8 * b) for b in range(3))
                   for index in range(FONT_DICTIONARY_COUNT))


class Red2RowsTests(unittest.TestCase):
    def test_two_glyph_history_dominates_all_older_constraints(self):
        codes = [c for c in range(256) if METADATA[c] & 256]
        self.assertEqual(verify_two_glyph_history(ADVANCES, codes, stride=256), len(codes) ** 4)

    def test_negative_advance_counterexample_is_rejected(self):
        advances = [0] * 16384
        a, b, c = map(ord, '#,4')
        advances[(a << 7) | b] = 12
        advances[(a << 7) | c] = 16
        advances[(b << 7) | b] = 7
        advances[(b << 7) | c] = -4
        with self.assertRaisesRegex(ValueError, 'Two-glyph history is insufficient'):
            verify_two_glyph_history(advances, [a, b, c])

    def test_each_row_matches_independent_column_data(self):
        for code, desc in enumerate(DESCRIPTORS):
            width, base = (desc >> 11) & 255, desc & 2047
            meta = METADATA[code]
            row_base, top_y, height = (meta >> 20) & 2047, (meta >> 15) & 31, (meta >> 9) & 63
            self.assertEqual(bool(meta & 256), bool(desc & (1 << 19)))
            self.assertEqual(meta & 31, width)
            self.assertLessEqual(top_y + height, 32)
            self.assertLessEqual(row_base + height, FONT_INDEX_BASE + FONT_ROW_COUNT)
            for y in range(32):
                expected = sum(((COLUMNS[base + x] >> y) & 1) << x for x in range(width))
                actual = 0
                if top_y <= y < top_y + height:
                    actual = DICTIONARY[FONT_WORDS[row_base + y - top_y] & 511]
                self.assertEqual(actual, expected, (chr(code), y))
            if height:
                self.assertNotEqual(DICTIONARY[FONT_WORDS[row_base] & 511], 0)
                self.assertNotEqual(DICTIONARY[FONT_WORDS[row_base + height - 1] & 511], 0)

    def test_dictionary_and_cropped_storage_bounds(self):
        self.assertEqual(FONT_DICTIONARY_COUNT, 264)
        self.assertEqual(FONT_INDEX_BASE, (3 * FONT_DICTIONARY_COUNT + 1) // 2)
        self.assertEqual(FONT_ROW_COUNT, 1542)
        self.assertEqual(len(FONT_WORDS), 2048)
        self.assertTrue(all(0 <= word < (1 << 16) for word in FONT_WORDS))
        self.assertEqual(DICTIONARY[0], 0)
        self.assertEqual(len(set(DICTIONARY)), FONT_DICTIONARY_COUNT)
        self.assertTrue(all(0 <= bits < (1 << 21) for bits in DICTIONARY))
        end = FONT_INDEX_BASE
        for meta in METADATA:
            if meta & 256:
                self.assertEqual((meta >> 20) & 2047, end)
                end += (meta >> 9) & 63
        self.assertEqual(end, 1938)
        self.assertTrue(all((index & 511) < FONT_DICTIONARY_COUNT for index in FONT_WORDS[FONT_INDEX_BASE:end]))
        self.assertTrue(all((word & 4095) == 0 for word in FONT_WORDS[end:]))

    def test_two_word_fetch_reconstructs_every_dictionary_pattern(self):
        for index, expected in enumerate(DICTIONARY):
            address = index + (index >> 1)
            joined = FONT_WORDS[address] | (FONT_WORDS[address + 1] << 16)
            actual = (joined >> (8 * (index & 1))) & ((1 << 21) - 1)
            self.assertEqual(actual, expected)

    def test_independent_left_and_right_kerning_classes(self):
        self.assertEqual((KERNING_LEFT_COUNT, KERNING_RIGHT_COUNT), (29, 29))
        self.assertEqual(UNICODE_CODEPOINTS, (0x2500, 0x2502, 0x250c, 0x2510, 0x2514, 0x2518,
                                             0x251c, 0x2524, 0x252c, 0x2534, 0x253c,
                                             0x25b2, 0x25b6, 0x25bc, 0x25c0))
        self.assertTrue(all(METADATA[128+i] & 256 for i in range(len(UNICODE_CODEPOINTS))))
        self.assertEqual(len(KERNING), 29 * 29)
        self.assertTrue(all(0 <= value < 16 for value in KERNING))
        codes = [c for c in range(256) if METADATA[c] & 256]
        left_ids = [(METADATA[c] >> 31) & 63 for c in codes]
        right_ids = [(METADATA[c] >> 37) & 63 for c in codes]
        self.assertEqual(set(left_ids), set(range(29)))
        self.assertEqual(set(right_ids), set(range(29)))
        self.assertTrue(all(0 <= meta < (1 << 43) for meta in METADATA))
        rows = [tuple(KERNING[a * 29:(a + 1) * 29]) for a in range(29)]
        columns = [tuple(KERNING[a * 29 + b] for a in range(29)) for b in range(29)]
        self.assertEqual(len(set(rows)), 29)
        self.assertEqual(len(set(columns)), 29)
        self.assertEqual((METADATA[ord('A')] >> 31) & 63,
                         (METADATA[ord('Q')] >> 31) & 63)
        self.assertEqual(len({(METADATA[ord(c)] >> 37) & 63 for c in 'CGOQ'}), 1)

    def test_future_kerning_cannot_reach_emitted_prefix(self):
        codes = [c for c in range(256) if METADATA[c] & 256]
        for left in codes:
            guard = (METADATA[left] >> 5) & 7
            for right in codes:
                advance = ADVANCES[(left << 8) | right]
                self.assertEqual((METADATA[left] & 31) + 4 - KERNING[((METADATA[left] >> 31) & 63) * KERNING_RIGHT_COUNT
                                               + ((METADATA[right] >> 37) & 63)], advance)
                next_guard = (METADATA[right] >> 5) & 7
                self.assertGreaterEqual(advance - next_guard, -guard)


if __name__ == '__main__':
    unittest.main()
