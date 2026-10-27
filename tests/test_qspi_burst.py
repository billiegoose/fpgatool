"""Exercise wire edges, byte order, pad turnaround, abort, and vblank budget."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.qspi_burst import read_burst


@unittest.skipIf(p is None, 'requires Pypeline')
class BurstTests(unittest.TestCase):
    def run_read(self, payload):
        p.sim_reset()
        previous_clock, previous_cs = 0, 1
        rising_edges = 0
        command = 0
        received = []
        dq = 0
        for cycle in range(100000):
            out = p.sim_call(read_burst, dq, int(cycle == 0), 0x220000,
                             len(payload), 0)
            pins = out.pins
            if previous_cs and not pins.cs_n:
                rising_edges = 0
            if not previous_clock and pins.cclk:
                if rising_edges < 40:
                    command = (command << 1) | int(pins.dq0)
                else:
                    self.assertEqual((pins.dq0_t, pins.dq1_t, pins.dq2_t, pins.dq3_t),
                                     (1, 1, 1, 1))
                rising_edges += 1
            if previous_clock and not pins.cclk and not pins.cs_n:
                nibble = rising_edges - 40
                if nibble >= 0 and nibble < 2 * len(payload):
                    dq = (payload[nibble // 2] >> (4 if nibble % 2 == 0 else 0)) & 15
            if out.valid:
                received.append(int(pins.read_data))
            if pins.done:
                self.assertEqual(command, (0x6b << 32) | (0x220000 << 8))
                self.assertEqual(received, list(payload))
                self.assertEqual(rising_edges, 40 + 2 * len(payload))
                self.assertTrue(pins.cs_n)
                return cycle
            previous_clock, previous_cs = int(pins.cclk), int(pins.cs_n)
        self.fail('burst did not finish')

    def test_byte_order_and_turnaround(self):
        self.run_read(bytes([0x12, 0xa5, 0, 0xff, 0x37]))

    def test_full_font_fits_vertical_blank_with_margin(self):
        cycles = self.run_read(bytes((n * 131 + 9) & 255 for n in range(4256)))
        self.assertLess(cycles, 44 * 2200)  # reserve last blank line for renderer
        self.assertLess(cycles / 148500, 0.58)

    def test_abort_releases_pins_and_allows_restart(self):
        p.sim_reset()
        p.sim_call(read_burst, 0, 1, 0, 32, 0)
        for _ in range(100):
            p.sim_call(read_burst, 0, 0, 0, 32, 0)
        out = p.sim_call(read_burst, 0, 0, 0, 32, 1)
        self.assertTrue(out.pins.cs_n)
        self.assertFalse(out.pins.cclk)
        self.assertFalse(out.valid)
        out = p.sim_call(read_burst, 0, 0, 0, 32, 0)
        self.assertTrue(out.pins.ready)


if __name__ == '__main__':
    unittest.main()
