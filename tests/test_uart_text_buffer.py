"""Exercise editing against the actual synchronous character BRAM and tail."""
from pathlib import Path
import sys
import unittest
import tempfile
import os

try:
    import pypeline as p
except ImportError:
    PYPELINE_AVAILABLE = False
else:
    PYPELINE_AVAILABLE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
    import SYN
    from hardware.uart_rx import uart_rx_t
    from hardware.uart_text_buffer import make_uart_text_buffer


@unittest.skipUnless(PYPELINE_AVAILABLE, 'requires the Pypeline runtime')
class UartTextBufferTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = SYN.SYN_OUTPUT_DIRECTORY
        self.addCleanup(setattr, SYN, 'SYN_OUTPUT_DIRECTORY', previous)
        SYN.SYN_OUTPUT_DIRECTORY = directory.name
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(directory.name)
        self.buffer = make_uart_text_buffer(4)

    def tick(self, byte=0, valid=0, address=0):
        return p.sim_call(self.buffer, uart_rx_t(data=byte, valid=valid),
                          p.uint14_t(address))

    def send(self, byte):
        return self.tick(byte=byte, valid=1)

    def contents(self, count):
        values = []
        for address in range(count):
            for _ in range(3):
                result = self.tick(address=address)
            values.append(int(result.data))
        return bytes(values)

    def test_backspace_erases_bram_and_reuses_slot(self):
        for byte in b'ABC':
            self.send(byte)
        out = self.send(8)
        self.assertTrue(out.committed)
        self.assertEqual(int(out.tail), 3)  # The same-cycle snapshot sees old tail.
        self.assertEqual(int(self.tick().tail), 2)
        self.assertEqual(self.contents(3), b'AB\x00')
        self.send(ord('D'))
        self.assertEqual(self.contents(3), b'ABD')

    def test_delete_can_remove_newline_and_join_lines(self):
        for byte in b'A\n':
            self.send(byte)
        self.send(127)
        self.assertEqual(self.contents(2), b'A\x00')
        self.send(ord('B'))
        self.assertEqual(self.contents(2), b'AB')

    def test_repeated_backspaces_stop_at_empty(self):
        self.send(ord('A'))
        for code in (8, 127, 8, 127):
            self.send(code)
        out = self.tick()
        self.assertEqual(int(out.tail), 0)
        self.assertFalse(out.full)
        self.assertFalse(self.send(8).committed)
        self.assertEqual(self.contents(1), b'\x00')

    def test_full_buffer_accepts_backspace_then_replacement(self):
        for byte in b'ABCD':
            self.send(byte)
        self.assertTrue(self.tick().full)
        self.assertFalse(self.send(ord('E')).committed)
        self.assertEqual(self.contents(4), b'ABCD')
        out = self.send(127)
        self.assertTrue(out.committed)
        self.assertFalse(out.full)
        self.send(ord('F'))
        self.assertTrue(self.tick().full)
        self.assertEqual(self.contents(4), b'ABCF')

    def test_invalid_strobe_does_not_edit(self):
        self.send(ord('A'))
        self.tick(byte=8, valid=0)
        self.assertEqual(int(self.tick().tail), 1)
        self.assertEqual(self.contents(1), b'A')


if __name__ == '__main__':
    unittest.main()
