"""Check cropped dictionary rows and the kerning bound for settled pixels."""
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
sys.path.insert(0, str(ROOT / 'scripts'))
from kerning_history import verify_two_glyph_history
from hardware.red2_row_data import ROW_DICTIONARY, ROW_INDICES, METADATA, KERNING
from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES


class Red2RowsTests(unittest.TestCase):
    def test_two_glyph_history_dominates_all_older_constraints(self):
        codes = [c for c in range(128) if METADATA[c] & 256]
        self.assertEqual(verify_two_glyph_history(ADVANCES, codes), len(codes) ** 4)

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
            width, base = (desc >> 10) & 255, desc & 1023
            meta = METADATA[code]
            row_base, top_y, height = meta >> 20, (meta >> 15) & 31, (meta >> 9) & 63
            self.assertEqual(bool(meta & 256), bool(desc & (1 << 18)))
            self.assertEqual(meta & 31, width)
            self.assertLessEqual(top_y + height, 32)
            self.assertLessEqual(row_base + height, len(ROW_INDICES))
            for y in range(32):
                expected = sum(((COLUMNS[base + x] >> y) & 1) << x for x in range(width))
                actual = 0
                if top_y <= y < top_y + height:
                    actual = ROW_DICTIONARY[ROW_INDICES[row_base + y - top_y]]
                self.assertEqual(actual, expected, (chr(code), y))
            if height:
                self.assertNotEqual(ROW_DICTIONARY[ROW_INDICES[row_base]], 0)
                self.assertNotEqual(ROW_DICTIONARY[ROW_INDICES[row_base + height - 1]], 0)

    def test_dictionary_and_cropped_storage_bounds(self):
        self.assertEqual(ROW_DICTIONARY[0], 0)
        self.assertEqual(len(ROW_DICTIONARY), 253)
        self.assertEqual(len(set(ROW_DICTIONARY)), len(ROW_DICTIONARY))
        self.assertTrue(all(0 <= bits < (1 << 21) for bits in ROW_DICTIONARY))
        self.assertTrue(all(0 <= index < len(ROW_DICTIONARY) for index in ROW_INDICES))
        self.assertEqual(len(ROW_INDICES), 2048)
        end = 0
        for meta in METADATA:
            if meta & 256:
                self.assertEqual(meta >> 20, end)
                end += (meta >> 9) & 63
        self.assertEqual(end, 1253)
        self.assertTrue(all(index == 0 for index in ROW_INDICES[end:]))

    def test_future_kerning_cannot_reach_emitted_prefix(self):
        codes = [c for c in range(128) if METADATA[c] & 256]
        for left in codes:
            guard = (METADATA[left] >> 5) & 7
            for right in codes:
                advance = ADVANCES[(left << 7) | right]
                self.assertEqual((METADATA[left] & 31) + 4 - KERNING[(left << 7) | right], advance)
                next_guard = (METADATA[right] >> 5) & 7
                self.assertGreaterEqual(advance - next_guard, -guard)


if __name__ == '__main__':
    unittest.main()
