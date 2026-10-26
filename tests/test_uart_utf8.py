"""Native Pypeline checks for byte-by-byte UART UTF-8 to glyph-ID decoding."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from font_glyph_ids import assign_glyph_ids, edited_glyph_ids

try:
    import pypeline as p
except ImportError:
    PYPELINE_AVAILABLE = False
else:
    PYPELINE_AVAILABLE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
    from hardware.uart_utf8 import make_uart_utf8_decoder
    from hardware.uart_rx import uart_rx_t
    from hardware.red2_row_data import UNICODE_CODEPOINTS


class GlyphMappingTests(unittest.TestCase):
    def test_ascii_is_unchanged_and_unicode_ids_are_sorted(self):
        remapped, extra = assign_glyph_ids({0x25C0: 'left', 65: 'A', 0x25B2: 'up', 0x25B6: 'right', 0x25BC: 'down'})
        self.assertEqual(extra, (0x25B2, 0x25B6, 0x25BC, 0x25C0))
        self.assertEqual(remapped, {131: 'left', 65: 'A', 128: 'up', 129: 'right', 130: 'down'})

    def test_reference_edits_whole_glyphs(self):
        cps = (0x25B2, 0x25B6, 0x25BC, 0x25C0)
        self.assertEqual(edited_glyph_ids('A▲▶▼◀Z'.encode(), cps), b'A\x80\x81\x82\x83Z')
        self.assertEqual(edited_glyph_ids('A▶\b◀Z'.encode(), cps), b'A\x83Z')
        self.assertEqual(edited_glyph_ids('A►Z'.encode(), cps), b'AZ')
        self.assertEqual(edited_glyph_ids('▲▶'.encode(), cps, capacity=1), b'\x80')


@unittest.skipUnless(PYPELINE_AVAILABLE, 'requires the Pypeline runtime')
class UartUtf8DecoderTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()
        self.decoder = make_uart_utf8_decoder(UNICODE_CODEPOINTS)

    def glyph(self, character):
        return 128 + UNICODE_CODEPOINTS.index(ord(character))

    def send(self, incoming):
        output = []
        for byte in incoming:
            event = p.sim_call(self.decoder, uart_rx_t(data=byte, valid=1))
            if int(event.valid):
                output.append(int(event.data))
        # UART input is registered before decoding; flush the final event.
        event = p.sim_call(self.decoder, uart_rx_t(data=0, valid=0))
        if int(event.valid):
            output.append(int(event.data))
        return output

    def test_all_triangles_ascii_and_newline(self):
        self.assertEqual(self.send('A▲▶▼◀Z\n'.encode()), [65, *(self.glyph(c) for c in '▲▶▼◀'), 90, 10])

    def test_all_box_drawing_characters(self):
        text = '─│┌┐└┘├┤┬┴┼'
        self.assertEqual(self.send(text.encode()), [self.glyph(c) for c in text])

    def test_unsupported_unicode_and_recovery(self):
        self.assertEqual(self.send('A►B☃C'.encode()), [65, 66, 67])

    def test_interrupted_and_malformed_sequences(self):
        self.assertEqual(self.send(b'\xe2\x96A\xe2\x96\xb6'), [65, self.glyph('▶')])
        self.assertEqual(self.send(b'\xf0\x82\x96\xb6Z'), [90])  # Overlong 4-byte ▶ rejected.

    def test_backspace_after_unicode(self):
        self.assertEqual(self.send('▲\bZ'.encode()), [self.glyph('▲'), 8, 90])

    def test_invalid_strobe_does_not_consume_input(self):
        event = p.sim_call(self.decoder, uart_rx_t(data=ord('A'), valid=0))
        self.assertEqual(int(event.valid), 0)
        self.assertEqual(self.send('▶'.encode()), [self.glyph('▶')])


if __name__ == '__main__':
    unittest.main()
