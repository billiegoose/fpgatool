"""The reusable reader works with caller-owned RAMs and a stalled consumer."""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.font_v2.renderer import read_glyph_row
    from hardware.font_v2.types import font_v2_config_t
    from hardware import red2_font_v2_data as font, red2_row_data as old
    from hardware.red2_uart_data import COLUMNS, DESCRIPTORS, ADVANCES


@unittest.skipIf(p is None, 'requires Pypeline')
class GlyphReaderTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()
        self.config = font_v2_config_t(metadata_base=font.METADATA_BASE,
            crop_base=font.CROP_BASE, rows_base=font.ROWS_BASE,
            kerning_base=font.KERNING_BASE, patterns_base=font.PATTERNS_BASE,
            spacing=font.SPACING, page_count=len(font.PAGES),
            pages_a=[prefix | (base << 16) | (overlay << 26)
                     for prefix,base,first,count,overlay in font.PAGES] + [0]*6,
            pages_b=[first | (count << 8) for prefix,base,first,count,overlay in font.PAGES] + [0]*6)
        self.text_data = self.a = self.b = 0
        self.text = []
        self.y, self.origin, self.first = 0, 5, 0

    def tick(self, *, start=0, stop=0, take=1, ready=1):
        out = p.sim_call(read_glyph_row, self.config, ready, self.text_data,
            self.a, self.b, self.y, len(self.text), self.first, self.origin,
            start, stop, take)
        # Explicit synchronous memories. There are no UART/VGA/board actors.
        address = int(out.text_address)
        self.text_data = self.text[address] if address < len(self.text) else 0
        self.a = font.FONT_WORDS[int(out.font_address_a)]
        self.b = font.FONT_WORDS[int(out.font_address_b)]
        return out

    def expected(self):
        supported = {code if code < 128 else old.UNICODE_CODEPOINTS[code-128]: code
                     for code in font.SOURCE_CODES if code != 0}
        history = []
        result = []
        for index, cp in enumerate(self.text[self.first:], self.first):
            if cp == 10:
                result.append((1, index, index+1, 0, None, None))
                return result
            if cp < 32:
                continue
            code = supported.get(cp, 0)
            origin = self.origin
            if history:
                origin = max(x + ADVANCES[(previous << 8) | code] for previous,x in history[-2:])
            desc = DESCRIPTORS[code]
            width, column = (desc >> 11) & 255, desc & 2047
            bits = sum(((COLUMNS[column+x] >> self.y) & 1) << x for x in range(width)) if self.y < 32 else 0
            result.append((0, index, index+1, bits, width, origin))
            history.append((code,origin))
        result.append((2, len(self.text), len(self.text), 0, None, None))
        return result

    def collect(self, stalls=False):
        self.tick(start=1)
        result, held = [], None
        rng = random.Random(123)
        for cycle in range(3000):
            take = int(not stalls or rng.randrange(8) == 0)
            out = self.tick(take=take)
            row = tuple(int(v) for v in out.row)
            if held is not None:
                self.assertTrue(out.valid)
                self.assertEqual(row, held, 'unaccepted output changed')
            held = row if out.valid and not take else None
            if out.valid and take:
                r = out.row
                result.append((int(r.kind),int(r.index),int(r.after),int(r.bits) if r.kind == 0 else 0,
                               int(r.width) if r.kind == 0 else None,
                               int(r.origin) if r.kind == 0 else None))
                if r.kind != 0:
                    return result
        self.fail('reader did not finish')

    def test_glyphs_unicode_fallback_and_two_glyph_kerning(self):
        self.text = list(map(ord, 'AVATAR {W}')) + [0x2500,0x25ff,0x1f600,0x10ffff]
        for self.y in (0,13,26,31,35):
            self.assertEqual(self.collect(), self.expected())

    def test_every_reference_glyph_matches_independent_columns(self):
        self.text = [code if code < 128 else old.UNICODE_CODEPOINTS[code-128]
                     for code in font.SOURCE_CODES[1:]]
        # Exercise both pattern banks, cropped/mirrored rows, and all pages.
        for self.y in (0,13,26,31):
            self.assertEqual(self.collect(), self.expected())

    def test_backpressure_newline_and_nonzero_start_origin(self):
        self.text = [ord('X'),ord('A'),1,ord('V'),0x2500,10,ord('W')]
        self.y, self.first, self.origin = 13, 1, 123
        self.assertEqual(self.collect(stalls=True), self.expected())

    def test_stop_and_not_ready_discard_pending_rows_then_restart(self):
        self.text = list(map(ord, 'WAV'))
        self.tick(start=1)
        for _ in range(100):
            out = self.tick(take=0)
            if out.valid:
                break
        self.assertTrue(out.valid)
        self.assertFalse(self.tick(stop=1, take=0).valid)
        for _ in range(30):
            self.assertFalse(self.tick(take=0).valid)
        self.assertEqual(self.collect(), self.expected())
        self.assertFalse(self.tick(ready=0).valid)
        for _ in range(10):
            self.assertFalse(self.tick().valid)
        self.assertEqual(self.collect(stalls=True), self.expected())


if __name__ == '__main__':
    unittest.main()
