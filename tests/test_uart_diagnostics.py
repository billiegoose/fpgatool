"""Diagnostics must distinguish wire activity, decoded bytes and text writes."""
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
    from hardware.uart_diagnostics import uart_diagnostics
    from hardware.uart_rx import uart_rx_t


@unittest.skipUnless(PYPELINE_AVAILABLE, 'requires the Pypeline runtime')
class UartDiagnosticsTests(unittest.TestCase):
    def test_activity_decode_write_and_display(self):
        p.sim_reset()

        def tick(rx=1, byte=0, valid=0, committed=0, full=0):
            return p.sim_call(uart_diagnostics, p.uint1_t(rx), p.uint1_t(1),
                              uart_rx_t(data=byte, valid=valid),
                              p.uint1_t(committed), p.uint1_t(full))

        # Raw activity persists without claiming a successfully framed byte.
        tick(rx=0)
        tick(rx=0)
        tick(rx=0)
        out = tick()
        self.assertTrue(int(out.leds) & (1 << 11))
        self.assertFalse(int(out.leds) & (1 << 12))
        tick(byte=65, valid=1)
        tick(byte=65, valid=1, committed=1)
        out = tick(full=1)
        self.assertEqual(int(out.leds) & 255, 65)
        self.assertTrue(int(out.leds) & (1 << 12))
        self.assertFalse(int(out.leds) & (1 << 13))  # Two byte strobes.
        self.assertTrue(int(out.leds) & (1 << 14))
        self.assertTrue(int(out.leds) & (1 << 15))
        # CCBB=0241: count two, last byte ASCII A. Check all scan phases.
        segments = {}
        for _ in range(65536):
            out = tick()
            segments[int(out.anodes)] = int(out.segments)
        self.assertEqual(segments, {0xe: 0x79, 0xd: 0x19, 0xb: 0x24, 0x7: 0x40})


if __name__ == '__main__':
    unittest.main()
