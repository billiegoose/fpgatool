"""Crop/address extraction preserves ink, wrapping and byte selection."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'examples'))
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.font_v2.row_address import (calculate_row_address, row_address,
                                                  capture_row_address, row_address_input_t)
    from hardware import red2_font_v2_data as font


@unittest.skipIf(p is None, 'requires Pypeline')
class FontV2RowAddressTests(unittest.TestCase):
    def check_address(self, crop, select, base, y, rows_base):
        # The unused half deliberately differs, exercising the word selector.
        word = (crop << 16) | (crop ^ 0xFFF) if select else crop | ((crop ^ 0xFFF) << 16)
        value = row_address_input_t(crop_word=word, crop_select=select,
                                    y=y, glyph_base=base, rows_base=rows_base)
        actual = p.sim_call(calculate_row_address, value)
        top, height = crop & 31, (crop >> 5) & 63
        relative = (y-top) & 63
        folded = min(relative, (height-1-relative) & 63) if crop & 2048 else relative
        byte = (base+folded) & 2047
        self.assertEqual(int(actual.address), (rows_base+(byte >> 2)) & 1023)
        self.assertEqual(int(actual.byte_select), byte & 3)
        self.assertEqual(int(actual.ink), int(y >= top and relative < height))

    def test_every_glyph_and_scanline(self):
        p.sim_reset()
        for meta in font.FONT_WORDS[font.METADATA_BASE:font.METADATA_BASE+font.GLYPH_COUNT]:
            cc = (meta >> 11) & 31
            crop = (font.FONT_WORDS[font.CROP_BASE+cc//2] >> (16*(cc&1))) & 65535
            for y in range(64):
                for select in range(2):
                    self.check_address(crop,select,meta & 2047,y,font.ROWS_BASE)

    def test_empty_crops_and_address_carry_boundaries(self):
        for top,height in ((0,0),(31,0),(0,32),(31,1),(0,63)):
            for mirror in range(2):
                crop = top | (height << 5) | (mirror << 11)
                for base in (0,1,2,3,4,1023,1024,2044,2045,2046,2047):
                    for y in (0,1,15,31,32,63):
                        self.check_address(crop,mirror,base,y,1023)

    def test_mirror_rows_for_every_height(self):
        for height in range(64):
            for row in range(64):
                self.check_address((height << 5) | 2048,0,2047,row,1023)

    def test_pipeline_keeps_result_fields_aligned(self):
        inputs = [row_address_input_t(crop_word=top | (height << 5) | (mirror << 11),
                                      crop_select=0, y=y, glyph_base=base, rows_base=100)
                  for top,height,mirror,y,base in
                  ((0,32,0,3,0),(12,14,1,24,17),(20,4,1,21,31),
                   (31,0,0,0,2047),(0,32,1,31,1023))]
        expected = []
        for i in inputs:
            result = p.sim_call(calculate_row_address,i)
            expected.append(tuple(int(x) for x in result))
        p.sim_reset()
        actual = [tuple(int(x) for x in p.sim_call(row_address,i))
                  for i in inputs+[inputs[-1]]]
        self.assertEqual(actual, [(0,0,0)]+expected)

    def test_capture_holds_all_fields_through_publication_stalls(self):
        inputs = [row_address_input_t(crop_word=top | (height << 5) | (mirror << 11),
                                      crop_select=0, y=y, glyph_base=base, rows_base=100)
                  for top,height,mirror,y,base in
                  ((0,32,0,3,0),(12,14,1,24,17),(20,4,1,21,31),
                   (31,0,0,0,2047),(0,32,1,31,1023))]
        expected = [tuple(int(x) for x in p.sim_call(calculate_row_address,i))
                    for i in inputs]
        p.sim_reset()
        previous = (0,0,0)
        for i,result in zip(inputs,expected):
            self.assertEqual(tuple(int(x) for x in p.sim_call(capture_row_address,i,1)), previous)
            for junk in inputs*7:
                self.assertEqual(tuple(int(x) for x in p.sim_call(capture_row_address,junk,0)), result)
            previous = result


if __name__ == '__main__':
    unittest.main()
