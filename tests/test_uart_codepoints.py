"""Unicode decoding is independent of the selected font's supported glyphs."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'examples'))
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.uart_rx import uart_rx_t
    from hardware.uart_codepoints import uart_codepoints


@unittest.skipIf(p is None, 'requires Pypeline')
class UartCodepointTests(unittest.TestCase):
    def decode(self, data):
        p.sim_reset()
        result=[]
        for b in data:
            event=p.sim_call(uart_codepoints,uart_rx_t(data=b,valid=1))
            if event.valid:
                result.append(int(event.data))
        for _ in range(2):
            event=p.sim_call(uart_codepoints,uart_rx_t(data=0,valid=0))
            if event.valid:
                result.append(int(event.data))
        return result

    def test_ascii_bmp_astral_and_edit_controls(self):
        text='A▶😀\bZ\n'
        self.assertEqual(self.decode(text.encode()),list(map(ord,text)))

    def test_invalid_scalars_and_overlong_forms_are_rejected(self):
        self.assertEqual(self.decode(b'\xed\xa0\x80\xf4\x90\x80\x80\xf0\x82\x96\xb6Z'),[90])

    def test_interrupted_sequence_recovers(self):
        self.assertEqual(self.decode(b'\xe2\x96A\xe2\x96\xb6'),[65,0x25b6])


if __name__ == '__main__':
    unittest.main()
