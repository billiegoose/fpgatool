"""Live reload preserves active pointers until a validated, blank-only copy."""
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from hardware.font_v2_format import HEADER_WORDS
from hardware import red2_font_v2_data as reference
try:
    import pypeline as p
except ImportError:
    p = None
else:
    from hardware import QSPI
    from hardware.font_v2_loader import load_font_from_qspi
    from hardware.live_flash import live_flash_control, live_flash_application_t
    from hardware.live_flash_protocol import BEGIN, RELOAD, RELEASE
    from hardware.qspi_burst import read_burst, qspi_burst_t


def image(spacing=None, corrupt=False):
    words = list(reference.FONT_HEADER_WORDS + reference.FONT_WORDS)
    if spacing is not None:
        words[14] = spacing
        words[40 + reference.PATTERNS_BASE] ^= 1
        words[16] = 0
        words[16] = -sum(words) & 0xffffffff
    if corrupt:
        words[-1] ^= 1
    return struct.pack('<1064I', *words)


@unittest.skipIf(p is None, 'requires Pypeline')
class LiveReloadTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()
        self.data = image()
        self.starts = 0
        self.writes = []
        self.ticks = 0
        self.reload_request = 0
        self.clear_error = 0
        owner = self

        def pins(**overrides):
            values = dict(cclk=0, cs_n=1, dq0=0, dq0_t=1, dq1=1, dq1_t=1,
                dq2=1, dq2_t=1, dq3=1, dq3_t=1, read_data=0, ready=1,
                busy=0, done=0, error=0, quad_enabled=1,
                quad_activity=0, quad_write_activity=0)
            values.update(overrides)
            return QSPI.qspi_flash_byte_io_t(**values)

        class Init:
            def __call__(self, dq, op, address, data, reset=0):
                return pins(ready=1-int(reset), busy=int(reset))

        class Burst:
            def __init__(self):
                self.data = None
                self.index = 0

            def __call__(self, dq, start, address, length, abort):
                if abort:
                    self.data = None
                    return qspi_burst_t(pins=pins(), valid=0)
                if start:
                    if self.data is not None:
                        raise AssertionError('overlapping bursts')
                    self.data = owner.data
                    self.index = 0
                    owner.starts += 1
                    self.assert_length = int(length)
                    assert int(address) == 0x220000
                    assert int(length) == len(self.data)
                    return qspi_burst_t(pins=pins(), valid=0)
                if self.data is not None:
                    byte = self.data[self.index]
                    self.index += 1
                    done = self.index == len(self.data)
                    if done:
                        self.data = None
                    return qspi_burst_t(pins=pins(read_data=byte, ready=0,
                        busy=1, done=int(done)), valid=1)
                return qspi_burst_t(pins=pins(), valid=0)

        self.cells = []
        for function, model in ((QSPI.flash_byte_io, Init), (read_burst, Burst)):
            self.cells.append((function._sim_model_cell, function._sim_model_cell.copy()))
            p.sim_model(function)(model)

    def tearDown(self):
        for cell, original in self.cells:
            cell[:] = original

    def tick(self, start=0, deadline=0, command=0):
        self.ticks += 1
        boot = p.sim_call(load_font_from_qspi, 0, start, deadline,
                          self.reload_request, self.clear_error)
        control = p.sim_call(live_flash_control, command, live_flash_application_t(
            ready=boot.font.ready, busy=boot.busy, quiescent=int(not boot.busy),
            done=boot.done, error=boot.font.error))
        self.reload_request = int(control.reload)
        self.clear_error = int(control.clear_error)
        out = SimpleNamespace(font=boot.font, flash=boot.flash,
                              granted=control.granted, busy=control.busy,
                              generation=control.generation)
        if out.font.write_enable:
            self.assertFalse(out.font.ready, 'BRAM read/write ownership overlap')
            self.writes.append((int(out.font.write_address), int(out.font.write_data)))
        return out

    def until(self, predicate):
        for _ in range(20000):
            out = self.tick()
            if predicate(out):
                return out
        self.fail('loader timeout')

    def boot(self):
        out = self.until(lambda o: o.font.ready and not o.busy)
        self.assertEqual(len(self.writes), 1024)
        self.assertEqual(out.generation, 1)
        self.assertEqual(out.font.config.spacing, reference.SPACING)
        self.writes.clear()

    def begin(self, ready=True):
        self.tick(command=BEGIN)
        out = self.until(lambda o: o.granted)
        self.assertTrue(out.granted)
        self.assertEqual(bool(out.font.ready), ready)

    def test_verified_copy_waits_for_blank_and_commits_config_together(self):
        self.boot()
        self.begin()
        self.data = image(9)
        for _ in range(100):
            self.assertTrue(self.tick().font.ready)
        self.assertFalse(self.writes)
        self.tick(command=RELOAD)
        self.until(lambda o: self.starts == 3)
        for _ in range(4400):
            out = self.tick()
            self.assertTrue(out.font.ready)
            self.assertEqual(out.font.config.spacing, reference.SPACING)
            self.assertFalse(self.writes)
        self.assertEqual(self.starts, 3, 'copy must wait for blank start')
        self.tick(start=1)
        out = self.until(lambda o: o.font.ready and not o.busy)
        self.assertEqual(out.font.config.spacing, 9)
        self.assertEqual(out.generation, 2)
        self.assertFalse(out.font.error)
        words = struct.unpack('<1064I', self.data)[HEADER_WORDS:]
        self.assertEqual(self.writes, list(enumerate(words)))

    def test_bad_preflight_preserves_old_bram_and_active_header(self):
        self.boot()
        self.begin()
        self.data = image(9, corrupt=True)
        self.tick(command=RELOAD)
        out = self.until(lambda o: o.font.error and not o.busy)
        self.assertTrue(out.font.ready)
        self.assertEqual(out.font.config.spacing, reference.SPACING)
        self.assertEqual(out.generation, 1)
        self.assertFalse(self.writes)
        for _ in range(10):
            self.tick(start=1)
        self.assertFalse(self.writes)

    def test_missed_deadline_disables_partial_image_until_retry(self):
        self.boot()
        self.begin()
        self.data = image(9)
        self.tick(command=RELOAD)
        self.until(lambda o: self.starts == 3)
        for _ in range(4400):
            self.tick()
        self.tick(start=1)
        for _ in range(500):
            self.tick()
        self.assertTrue(self.writes)
        self.tick(deadline=1)
        out = self.tick()
        self.assertTrue(out.font.error)
        self.assertFalse(out.font.ready)
        count = len(self.writes)
        for _ in range(500):
            self.assertFalse(self.tick().font.ready)
        self.assertEqual(len(self.writes), count)
        self.begin(ready=False)
        self.tick(command=RELOAD)
        out = self.until(lambda o: o.font.ready and not o.busy)
        self.assertFalse(out.font.error)
        self.assertEqual(out.font.config.spacing, 9)

    def test_abort_upload_keeps_current_font_and_does_not_reload(self):
        self.boot()
        self.begin()
        self.data = image(9)
        self.tick(command=RELEASE)
        out = self.tick()
        self.assertFalse(out.granted)
        self.assertFalse(out.busy)
        self.assertTrue(out.font.ready)
        self.assertEqual(self.starts, 2)
        self.assertFalse(self.writes)


if __name__ == '__main__':
    unittest.main()
