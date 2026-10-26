"""Decode the shared font/kerning ROM against the independent column renderer."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
sys.path.insert(0, str(ROOT / 'scripts'))
from hardware import red2_row_data as row
from hardware import red2_uart_data as column
from generate_uart_font import pack_kerning


class UartFontTests(unittest.TestCase):
    def test_all_pair_advances_match_shared_kerning(self):
        for left, lm in enumerate(row.METADATA):
            if not lm & 256:
                continue
            for right, rm in enumerate(row.METADATA):
                if not rm & 256:
                    continue
                lc, rc = (lm >> 31) & 63, (rm >> 37) & 63
                address = row.FONT_KERNING_BASE | (lc << row.KERNING_RIGHT_BITS) | rc
                adjustment = row.FONT_WORDS[address] >> 12
                self.assertEqual(adjustment, row.KERNING[lc * row.KERNING_RIGHT_COUNT + rc])
                self.assertEqual((lm & 31) + row.SPACING - adjustment,
                                 column.ADVANCES[(left << 8) | right], (left, right))

    def test_fixed_cells_and_unicode_mapping(self):
        for cp in (0x2500, 0x2502, 0x250c, 0x2510, 0x2514, 0x2518,
                   0x251c, 0x2524, 0x252c, 0x2534, 0x253c,
                   0x25b2, 0x25b6, 0x25bc, 0x25c0):
            code = 128 + row.UNICODE_CODEPOINTS.index(cp)
            self.assertEqual(row.METADATA[code] & 31, 17)
            self.assertEqual(column.ADVANCES[(code << 8) | code], 17)

    def test_padded_entries_are_zero_and_dictionary_is_separate(self):
        self.assertGreaterEqual(row.FONT_KERNING_BASE, row.FONT_INDEX_BASE)
        for left in range(1 << row.KERNING_LEFT_BITS):
            for right in range(row.KERNING_STRIDE):
                if left >= row.KERNING_LEFT_COUNT or right >= row.KERNING_RIGHT_COUNT:
                    address = row.FONT_KERNING_BASE | (left << row.KERNING_RIGHT_BITS) | right
                    self.assertEqual(row.FONT_WORDS[address] >> 12, 0)

    def test_rejects_class_table_that_cannot_share_font(self):
        data = vars(row).copy()
        data['KERNING_LEFT_BITS'] = data['KERNING_RIGHT_BITS'] = 6
        with self.assertRaisesRegex(ValueError, 'cannot share'):
            pack_kerning(data)

    def test_rejects_overwriting_font_data(self):
        data = vars(row).copy()
        words = list(row.FONT_WORDS)
        # Clear the overlay before asking the packer to write it again.
        words[row.FONT_KERNING_BASE:] = [word & 511 for word in words[row.FONT_KERNING_BASE:]]
        words[row.FONT_KERNING_BASE] |= 1 << 9
        data['FONT_WORDS'] = words
        with self.assertRaisesRegex(ValueError, 'occupied font bits'):
            pack_kerning(data)


if __name__ == '__main__':
    unittest.main()
