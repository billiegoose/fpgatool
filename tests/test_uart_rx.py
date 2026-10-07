"""Exercise serial framing and byte strobes, including identical consecutive bytes."""
from pathlib import Path
import sys
import unittest

try:
    import pypeline as p
except ImportError:
    PYPELINE_AVAILABLE = False
else:
    PYPELINE_AVAILABLE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
    from hardware.uart_rx import make_uart_rx


@unittest.skipUnless(PYPELINE_AVAILABLE, 'requires the Pypeline runtime')
class UartReceiverTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()
        self.receiver = make_uart_rx(1.0, baud=100000)
        self.bytes = []

    def hold(self, level, clocks):
        for _ in range(clocks):
            result = p.sim_call(self.receiver, p.uint1_t(level))
            if result.valid:
                self.bytes.append(int(result.data))

    def send(self, byte, stop=1, gap=10):
        self.hold(0, 10)
        for bit in range(8):
            self.hold((byte >> bit) & 1, 10)
        self.hold(stop, 10)
        self.hold(1, gap)

    def test_back_to_back_bytes_without_extra_idle_bits(self):
        self.hold(1, 30)
        expected = list(b'ABCABC THE QUICK BROWN FOX\n')
        for byte in expected:
            self.send(byte, gap=0)
        self.hold(1, 30)
        self.assertEqual(self.bytes, expected)

    def test_repeated_bytes_and_all_bit_patterns(self):
        self.hold(1, 30)
        expected = [65, 65, 0, 255, 0x55, 0xAA, 10]
        for byte in expected:
            self.send(byte)
        self.hold(1, 30)
        self.assertEqual(self.bytes, expected)

    def test_false_start_and_bad_stop_are_rejected(self):
        self.hold(1, 30)
        self.hold(0, 2)
        self.hold(1, 30)
        self.send(42, stop=0)
        self.send(90)
        self.assertEqual(self.bytes, [90])


if __name__ == '__main__':
    unittest.main()
