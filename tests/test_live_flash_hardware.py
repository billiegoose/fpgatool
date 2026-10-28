"""Reusable ownership/reload controller, independent of any font or board."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from hardware.live_flash_protocol import BEGIN, RELOAD, RELEASE, READY, GRANTED, BUSY, ERROR
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware.live_flash import live_flash_control, live_flash_application_t


@unittest.skipIf(p is None, 'requires Pypeline')
class LiveFlashControllerTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()

    def tick(self, command=0, *, ready=1, busy=0, quiescent=1, done=0, error=0):
        return p.sim_call(live_flash_control, command, live_flash_application_t(
            ready=ready, busy=busy, quiescent=quiescent, done=done, error=error))

    def grant(self):
        self.assertTrue(self.tick(BEGIN).clear_error)
        self.tick()
        out = self.tick()
        self.assertTrue(out.granted)
        return out

    def test_boot_busy_and_done_are_application_owned(self):
        out = self.tick(BEGIN, ready=0, busy=1)
        self.assertTrue(out.busy)
        self.assertFalse(out.granted or out.clear_error)
        self.tick(done=1)
        out = self.tick()
        self.assertEqual(out.status, READY | (1 << 16))

    def test_pause_waits_for_application_to_finish_its_transfer(self):
        self.tick(BEGIN, quiescent=0)
        for _ in range(20):
            out = self.tick(quiescent=0)
            self.assertTrue(out.pause and out.busy)
            self.assertFalse(out.granted or out.reload)
        self.tick(quiescent=1)
        out = self.tick()
        self.assertTrue(out.granted and out.pause)
        self.assertEqual(out.status & 15, READY | GRANTED | BUSY)

    def test_write_only_releases_without_reload_or_generation_change(self):
        self.grant()
        for _ in range(10):
            self.assertTrue(self.tick().granted)
        self.assertFalse(self.tick(RELEASE).reload)
        out = self.tick()
        self.assertFalse(out.granted or out.pause or out.busy)
        self.assertEqual(out.generation, 0)

    def test_reload_is_one_pulse_and_waits_for_explicit_completion(self):
        self.grant()
        self.assertTrue(self.tick(RELOAD).reload)
        for _ in range(10):
            out = self.tick()
            self.assertTrue(out.busy)
            self.assertFalse(out.granted or out.pause or out.reload)
        self.tick(done=1)
        out = self.tick()
        self.assertEqual(out.status, READY | (1 << 16))

    def test_reload_error_preserves_generation_and_can_be_retried(self):
        self.tick(done=1)
        self.grant()
        self.tick(RELOAD)
        self.tick(error=1)
        out = self.tick(error=1)
        self.assertFalse(out.busy)
        self.assertEqual(out.status, READY | ERROR | (1 << 16))
        self.assertTrue(self.tick(BEGIN, error=1).clear_error)
        self.tick(error=0)
        self.assertTrue(self.tick().granted)
        self.tick(RELOAD)
        self.tick(done=1)
        self.assertEqual(self.tick().generation, 2)

    def test_cancel_wait_and_ignore_reload_without_ownership(self):
        self.assertFalse(self.tick(RELOAD).reload)
        self.tick(BEGIN, quiescent=0)
        self.tick(RELOAD, quiescent=0)
        self.assertFalse(self.tick(RELEASE, quiescent=0).reload)
        out = self.tick()
        self.assertFalse(out.busy or out.pause or out.granted)


if __name__ == '__main__':
    unittest.main()
