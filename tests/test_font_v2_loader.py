"""The flash ABI loads header registers and exactly one BRAM, including stalls."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
from hardware.font_v2_format import HEADER_WORDS, CHECKSUM_WORD
from hardware import red2_font_v2_data as font
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.font_v2_loader import (consume_font_word, load_font_from_qspi,
                                        font_v2_config_t, FONT_FLASH_OFFSET)
    from hardware import QSPI
    from hardware.font_v2_map import lookup_unicode_page


def fixture():
    return list(font.FONT_HEADER_WORDS + font.FONT_WORDS)


def fix_checksum(words):
    words[CHECKSUM_WORD] = 0
    words[CHECKSUM_WORD] = -sum(words) & 0xffffffff


class FontV2ImageTests(unittest.TestCase):
    def test_header_and_little_endian_payload(self):
        data = struct.pack('<1064I', *(font.FONT_HEADER_WORDS + font.FONT_WORDS))
        words = fixture()
        self.assertEqual(data[:4], b'RFV2')
        self.assertEqual(words[1:5], [2, 160, 1024, font.USED_BYTES])
        self.assertEqual(sum(words) & 0xffffffff, 0)
        self.assertEqual(tuple(words[HEADER_WORDS:]), font.FONT_WORDS)


@unittest.skipIf(p is None, 'requires Pypeline')
class FontV2LoaderTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()

    def load(self, words, stalls=False):
        writes = []
        for i, word in enumerate(words):
            if stalls:
                for _ in range(i % 4):
                    idle = p.sim_call(consume_font_word, 0xbad, 0, 0)
                    self.assertFalse(idle.write_enable)
            out = p.sim_call(consume_font_word, word, 1, 0)
            if out.write_enable:
                writes.append((int(out.write_address), int(out.write_data)))
            if i != len(words)-1:
                self.assertFalse(out.ready)
        p.sim_call(consume_font_word, 0, 0, 0)
        out = p.sim_call(consume_font_word, 0, 0, 0)
        return out, writes

    def test_header_registers_payload_and_stalls(self):
        out, writes = self.load(fixture(), stalls=True)
        self.assertTrue(out.ready)
        self.assertFalse(out.error)
        self.assertEqual(writes, list(enumerate(font.FONT_WORDS)))
        cfg = out.config
        self.assertEqual(tuple(int(getattr(cfg, name)) for name in
                               ('metadata_base', 'crop_base', 'rows_base', 'kerning_base', 'patterns_base', 'spacing')),
                         (font.METADATA_BASE, font.CROP_BASE, font.ROWS_BASE,
                          font.KERNING_BASE, font.PATTERNS_BASE, font.SPACING))
        self.assertEqual(int(cfg.page_count), len(font.PAGES))
        for i, (prefix, base, first, count, overlay) in enumerate(font.PAGES):
            self.assertEqual(int(cfg.pages_a[i]), prefix | (base << 16) | (overlay << 26))
            self.assertEqual(int(cfg.pages_b[i]), first | (count << 8))
        done = p.sim_call(consume_font_word, 0xdeadbeef, 1, 0)
        self.assertTrue(done.ready)
        self.assertFalse(done.write_enable)

    def test_font_specific_bases_and_unicode_pages_are_loaded(self):
        words = fixture()
        # Relocate every table and map by eight words inside the same BRAM.
        words[HEADER_WORDS:] = [0]*8 + words[HEADER_WORDS:-8]
        words[4] += 32
        for i in range(5, 10):
            words[i] += 8
        for i in range(words[15]):
            words[24+2*i] += 8 << 16
        words[14] = 7
        words[24] = (words[24] & ~65535) | 0x123
        fix_checksum(words)
        out, _ = self.load(words)
        self.assertTrue(out.ready)
        self.assertEqual(out.config.spacing, 7)
        self.assertEqual(out.config.rows_base, font.ROWS_BASE+8)
        self.assertEqual(out.config.patterns_base, font.PATTERNS_BASE+8)
        self.assertEqual(int(out.config.pages_a[0]) & 65535, 0x123)

    def test_page_selection_register_keeps_codepoint_and_directory_aligned(self):
        out, _ = self.load(fixture())
        points = [0x2500, 65, 0x1f600, 255, 10, 0x25ff, 0x10ffff] * 3
        previous = None
        for cp in points + [0]:
            page = p.sim_call(lookup_unicode_page, cp, out.config)
            if previous is not None:
                self.assertEqual(page.codepoint, previous)
                match = next((entry for entry in font.PAGES if entry[0] == previous >> 8), None)
                self.assertEqual(page.present, int(match is not None))
                if match:
                    _, base, first, count, overlay = match
                    self.assertEqual(tuple(int(v) for v in (page.map_base, page.glyph_base,
                                                           page.glyph_count, page.overlay)),
                                     (base, first, count, overlay))
                    low = previous & 255
                    self.assertEqual(page.map_address, base + (low if overlay else low >> 2))
            previous = cp

    def test_blank_non_ascii_image_is_loadable(self):
        # Hand-built wire fixture; asset compilation belongs to red2-font.
        payload = [0]*1024
        payload[0] = payload[1] = 3 << 26
        payload[132:196] = [0xffffffff]*64
        payload[132] = 0xffffff00  # U+2500 maps to global glyph 1.
        header = [0]*40
        header[:16] = [0x32564652, 2, 160, 1024, 196*4, 0, 2, 3, 3, 131,
                       2, 1, 0, 1, 4, 1]
        header[24:26] = [0x25 | (132 << 16), 1 | (1 << 8)]
        words = header + payload
        fix_checksum(words)
        out, writes = self.load(words)
        self.assertTrue(out.ready)
        self.assertFalse(out.error)
        self.assertEqual(writes, list(enumerate(payload)))

    def test_all_eight_directory_slots_and_absent_pages(self):
        prefixes = (0, 0x25, 0x1f6, 1, 2, 3, 4, 0x10ff)
        entries = {prefix: (i*64, i+1, i+2, int(i == 0))
                   for i, prefix in enumerate(prefixes)}
        cfg = font_v2_config_t(metadata_base=0, crop_base=0, rows_base=0,
            kerning_base=0, patterns_base=0, spacing=4, page_count=8,
            pages_a=[prefix | (base << 16) | (overlay << 26)
                     for prefix, (base, first, count, overlay) in entries.items()],
            pages_b=[first | (count << 8) for base, first, count, overlay in entries.values()])
        previous = None
        points = [(prefix << 8) | low for prefix in (*prefixes, 0xab, 0x100) for low in (0, 255)]
        for cp in points + [0]:
            out = p.sim_call(lookup_unicode_page, cp, cfg)
            if previous is not None:
                self.assertEqual(out.codepoint, previous)
                self.assertEqual(tuple(int(v) for v in (out.map_base, out.glyph_base,
                                                       out.glyph_count, out.overlay)),
                                 entries.get(previous >> 8, (0, 0, 0, 0)))
                self.assertEqual(out.present, int(previous >> 8 in entries))
                entry = entries.get(previous >> 8)
                address = 0
                if entry:
                    base, _, _, overlay = entry
                    low = previous & 255
                    address = base + (low if overlay else low >> 2)
                self.assertEqual(out.map_address, address)
            previous = cp

    def test_invalid_headers_never_write_payload(self):
        for index, value in ((0, 0xffffffff), (1, 3), (2, 128), (3, 1025),
                             (4, 4097), (4, 508), (5, 1024), (8, 0xffffffff), (10, 257),
                             (11, 33), (12, 2049), (13, 513), (14, 32),
                             (15, 9), (17, 1), (24, 0xffffffff), (25, 0),
                             (5, 839), (6, 839), (7, 839), (9, 839), (8, 713),
                             (24, (585 << 16) | (1 << 26)),
                             (26, (777 << 16) | 0x25), (25, 84 | (2 << 8))):
            with self.subTest(index=index):
                p.sim_reset()
                words = fixture()
                words[index] = value
                fix_checksum(words)
                out, writes = self.load(words)
                self.assertTrue(out.error)
                self.assertFalse(out.ready)
                self.assertEqual(writes, [])

    def test_corrupt_or_truncated_payload_never_becomes_ready(self):
        for words in (fixture()[:-1], fixture()[:-8] + [0xffffffff]*8,
                      fixture()[:-1] + [fixture()[-1] ^ 1]):
            p.sim_reset()
            out, _ = self.load(words)
            self.assertFalse(out.ready)
            if len(words) == 1064:
                self.assertTrue(out.error)
        p.sim_reset()
        p.sim_call(consume_font_word, 0, 0, 1)
        out = p.sim_call(consume_font_word, 0, 0, 0)
        self.assertTrue(out.error)
        self.assertFalse(out.ready)



if __name__ == '__main__':
    unittest.main()
