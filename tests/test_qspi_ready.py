"""Ready reflects the state that accepts an operation, before FSM forwarding."""
from pathlib import Path
import inspect
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware import QSPI


@unittest.skipIf(p is None, 'requires Pypeline')
class QspiReadyTests(unittest.TestCase):
    def test_read_acceptance_and_completion_use_cycle_start_ready(self):
        timers = dict(_BYTE_POWERUP_CYCLES=4, _HALF_PERIOD_CYCLES=1,
                      _STARTUP_PRIME_CYCLES=2, _BYTE_NORMAL_CS_HIGH_CYCLES=1,
                      _BYTE_RECOVERY_CS_HIGH_CYCLES=1, _BYTE_RES_CYCLES=1)
        # All-one input emulates an already quad-enabled flash and FF data.
        # Pypeline freezes module constants into its generated simulation body.
        body = inspect.getclosurevars(QSPI.flash_byte_io).nonlocals['_run_body']
        simulation = inspect.getclosurevars(body).nonlocals['sim_body_fn']
        with patch.dict(simulation.__globals__, timers):
            p.sim_reset()
            for _ in range(1000):
                out = p.sim_call(QSPI.flash_byte_io, 15, 0, 0, 0)
                if out.ready:
                    break
            self.assertTrue(out.ready)
            self.assertTrue(out.quad_enabled)
            launched = p.sim_call(QSPI.flash_byte_io, 15, QSPI.FLASH_OP_READ, 0x220000, 0)
            self.assertTrue(launched.ready)
            for _ in range(1000):
                out = p.sim_call(QSPI.flash_byte_io, 15, 0, 0, 0)
                if out.done:
                    break
            self.assertTrue(out.done)
            self.assertFalse(out.error)
            self.assertEqual(out.read_data, 255)
            self.assertTrue(out.quad_activity)
            self.assertFalse(out.ready)
            out = p.sim_call(QSPI.flash_byte_io, 15, 0, 0, 0)
            self.assertTrue(out.ready)
            reset = p.sim_call(QSPI.flash_byte_io, 15, 0, 0, 0, 1)
            self.assertFalse(reset.ready)
            self.assertTrue(reset.cs_n)
            self.assertFalse(reset.cclk)
            self.assertFalse(reset.quad_enabled)
            for _ in range(1000):
                out = p.sim_call(QSPI.flash_byte_io, 15, 0, 0, 0)
                if out.ready:
                    break
            self.assertTrue(out.ready)
            self.assertTrue(out.quad_enabled)


if __name__ == '__main__':
    unittest.main()
