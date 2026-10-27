"""Independent fallback pixels and codepoint editing for the font-v2 renderer."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_uart_pixels import expected_pixels


class NotdefReferenceTests(unittest.TestCase):
    def render(self, text):
        return expected_pixels(text, width=320, height=120, notdef=True)

    def test_missing_characters_share_notdef_ink_and_advance(self):
        self.assertEqual(self.render('a━😀z'.encode()), self.render(b'\0' * 4))
        self.assertTrue(any(self.render(b'a')))

    def test_backspace_removes_unknown_unicode_without_erasing_previous_glyph(self):
        self.assertEqual(self.render('W😀\bA'.encode()), self.render(b'WA'))
        self.assertEqual(self.render(b'Wa\x7fA'), self.render(b'WA'))

    def test_controls_preserve_line_breaks_and_spacing_history(self):
        self.assertEqual(self.render(b'W\r\na'), self.render(b'W\n\0'))
        self.assertEqual(self.render(b'W\raA'), self.render(b'W\0A'))


if __name__ == '__main__':
    unittest.main()
