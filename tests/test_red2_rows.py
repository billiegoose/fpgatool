"""Check row ROM transposition and the safety bound used to emit settled pixels."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from hardware.red2_row_data import ROW_BITMAPS, METADATA, KERNING
from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES


class Red2RowsTests(unittest.TestCase):
    def test_each_row_matches_independent_column_data(self):
        for code, desc in enumerate(DESCRIPTORS):
            width, base = (desc >> 10) & 255, desc & 1023
            for y in range(32):
                expected = sum(((COLUMNS[base + x] >> y) & 1) << x for x in range(width))
                self.assertEqual(ROW_BITMAPS[(code << 5) | y], expected)

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
