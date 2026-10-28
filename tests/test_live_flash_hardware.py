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


@unittest.skipIf(p is None, 'requires Pypeline')
class LiveFlashProxyTests(unittest.TestCase):
    def setUp(self):
        from fpgatool_board.basys3 import live_flash, jtag_flash
        from hardware.QSPI import qspi_flash_byte_io_t
        p.sim_reset()
        self.proxy = live_flash.proxy
        self.command = 0
        self.last_miso = None
        self.application = live_flash_application_t(ready=1, busy=0, quiescent=1, done=0, error=0)
        self.pins = qspi_flash_byte_io_t(cclk=0, cs_n=1, dq0=0, dq0_t=0,
            dq1=1, dq1_t=1, dq2=0, dq2_t=1, dq3=1, dq3_t=0,
            read_data=42, ready=1, busy=0, done=0, error=0, quad_enabled=1,
            quad_activity=0, quad_write_activity=0)
        self.host = self.pins._replace(cclk=1, cs_n=0, dq0=1, dq2=1, busy=1, ready=0)
        self.cells = []
        owner = self

        class Command:
            def __call__(self, status):
                return owner.command

        class Bridge:
            def __call__(self, miso, granted):
                owner.last_miso = int(miso)
                return owner.host

        for function, model in ((jtag_flash.live_command, Command), (jtag_flash.spi_bridge, Bridge)):
            self.cells.append((function._sim_model_cell, function._sim_model_cell.copy()))
            function._sim_model_cell[0] = None
            p.sim_model(function)(model)

    def tearDown(self):
        for cell, original in self.cells:
            cell[:] = original

    def tick(self, command=0, miso=0):
        self.command = command
        return p.sim_call(self.proxy, self.pins, self.application, miso)

    def test_routes_complete_bus_and_explicit_miso_without_owning_pins(self):
        self.assertEqual(tuple(self.tick(miso=1).flash), tuple(self.pins))
        self.assertEqual(self.last_miso, 1)
        self.tick(BEGIN)
        self.tick()
        selected = self.tick(miso=0)
        self.assertTrue(selected.control.granted)
        self.assertEqual(tuple(selected.flash), tuple(self.host))
        self.assertEqual(self.last_miso, 0)
        self.tick(RELEASE)
        selected = self.tick()
        self.assertFalse(selected.control.granted)
        self.assertEqual(tuple(selected.flash), tuple(self.pins))

    def test_waits_for_idle_application_pins_before_switching(self):
        self.pins = self.pins._replace(cs_n=0)
        self.tick(BEGIN)
        for _ in range(8):
            self.assertFalse(self.tick().control.granted)
        self.pins = self.pins._replace(cs_n=1, cclk=1)
        for _ in range(8):
            self.assertFalse(self.tick().control.granted)
        self.pins = self.pins._replace(cclk=0)
        self.tick()
        self.assertTrue(self.tick().control.granted)


if __name__ == '__main__':
    unittest.main()
