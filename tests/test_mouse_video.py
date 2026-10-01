"""Mouse packet and cursor checks across legacy and 1080p video modes."""

from pathlib import Path
import sys
import unittest

try:
    import pypeline as p
    from vga.timing import VGA_640_480, VGA_1920_1080
    from vga.types import vga_pos_t, vga_timing_signals_t, vga_12bpp_t
except ImportError:
    PYPELINE_AVAILABLE = False
else:
    PYPELINE_AVAILABLE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from hardware.ps2_mouse import make_ps2_mouse
    from hardware.mouse_cursor import make_mouse_cursor

    _raw_cursor = make_mouse_cursor(VGA_1920_1080)
    _cursor_pipeline = p.AUTO_PIPELINE(_raw_cursor, latency=2)

    @p.hw_func
    def pipelined_cursor(sig: vga_timing_signals_t, bg: vga_12bpp_t) -> vga_12bpp_t:
        return _cursor_pipeline(sig, bg, 960, 540, 0, 0, 0, 0, 0)


@unittest.skipUnless(PYPELINE_AVAILABLE, "requires the Pypeline runtime and VGA library")
class MouseVideoTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()

    def start_mouse(self, rate, width, height):
        self.mouse = make_ps2_mouse(rate, width, height)
        first = self.tick()
        # Seed only simulator registers to skip the long device negotiation and
        # reach timing boundaries quickly; packets still enter via PS/2 pins.
        self.regs = next(iter(p._sim_reg_state.values()))
        return first

    def tick(self, clk=1, data=1, cycles=1):
        for _ in range(cycles):
            result = p.sim_call(self.mouse, clk, data)
        return result

    def byte(self, value):
        bits = [0] + [(value >> i) & 1 for i in range(8)]
        bits += [1 ^ (value.bit_count() & 1), 1]
        for bit in bits:
            self.tick(1, bit, 5)
            self.tick(0, bit, 5)
        return self.tick(cycles=5)

    def move(self, dx, dy):
        self.byte(8 | (16 if dx < 0 else 0) | (32 if dy < 0 else 0))
        self.byte(dx & 255)
        return self.byte(dy & 255)

    def test_mouse_center_and_full_frame_clamping(self):
        for rate, width, height in ((100, 640, 480), (148.5, 1920, 1080), (100, 4096, 4096)):
            with self.subTest(width=width):
                p.sim_reset()
                first = self.start_mouse(rate, width, height)
                self.assertEqual((first.x, first.y), (width // 2, height // 2))
                self.regs.update(state=9, x=width - 10, y=height - 10)
                result = self.move(127, -127)
                self.assertEqual((result.x, result.y), (width - 1, height - 1))
                result = self.move(-127, 127)
                self.assertEqual((result.x, result.y), (width - 128, height - 128))
                self.regs.update(x=10, y=10)
                result = self.move(-127, 127)
                self.assertEqual((result.x, result.y), (0, 0))

    def test_protocol_durations_scale_with_clock(self):
        for rate in (100, 148.5):
            with self.subTest(rate=rate):
                p.sim_reset()
                self.start_mouse(rate, 1920, 1080)
                self.regs.update(state=0, timer=int(rate * 20_000) - 2)
                self.assertEqual(self.tick().clk_release, 1)
                self.assertEqual(self.tick().clk_release, 1)
                self.assertEqual(self.tick().clk_release, 0)
                self.regs.update(state=1, timer=int(rate * 120) - 2)
                self.assertEqual(self.tick().data_release, 1)
                self.assertEqual(self.tick().data_release, 1)
                self.assertEqual(self.tick().data_release, 0)

    def pixel(self, draw, x, y, mx, my, active=1, left=0):
        sig = vga_timing_signals_t(pos=vga_pos_t(x=x, y=y), active=active,
                                  hsync=1, vsync=0, start_of_frame=0, end_of_frame=0)
        bg = vga_12bpp_t(r=3, g=4, b=5, hs=1, vs=0)
        px = p.sim_call(draw, sig, bg, mx, my, left, 0, 0, 0, 0)
        self.assertEqual((px.hs, px.vs), (1, 0))
        return px.r, px.g, px.b

    def test_all_link_timeouts_transition_on_the_expected_clock(self):
        for rate in (100, 148.5):
            for state, duration_us, next_state in ((0, 20000, 1), (1, 120, 2), (2, 20, 3),
                                                  (3, 20000, 1), (4, 20000, 1),
                                                  (5, 20000, 1), (6, 20000, 1),
                                                  (7, 50000, 1), (8, 50000, 1)):
                with self.subTest(rate=rate, state=state):
                    p.sim_reset()
                    self.start_mouse(rate, 1920, 1080)
                    self.regs.update(state=state, timer=int(rate * duration_us) - 2,
                                     data_meta=0, data_sync=0)
                    self.tick(data=0)
                    self.assertEqual(self.regs['state'], state)
                    self.tick(data=0)
                    self.assertEqual(self.regs['state'], next_state)
                    self.assertEqual(self.regs['timer'], 0)

    def test_cursor_reaches_1080p_coordinates_without_wrapped_ghosts(self):
        draw = make_mouse_cursor(VGA_1920_1080)
        self.assertEqual(self.pixel(draw, 1800, 1000, 1800, 1000), (15, 15, 15))
        self.assertEqual(self.pixel(draw, 1800, 1000, 1800, 1000, left=1), (15, 0, 0))
        self.assertEqual(self.pixel(draw, 1800, 1000, 1800, 1000, active=0), (3, 4, 5))
        self.assertEqual(self.pixel(draw, 1800, 1000, 776, 1000), (3, 4, 5))
        self.assertEqual(self.pixel(draw, 1800, 1000, 1800, 488), (3, 4, 5))

    def test_cursor_center_reaches_every_corner(self):
        for spec in (VGA_640_480, VGA_1920_1080):
            draw = make_mouse_cursor(spec)
            for x, step_x in ((0, 1), (spec.frame_width - 1, -1)):
                for y, step_y in ((0, 1), (spec.frame_height - 1, -1)):
                    with self.subTest(width=spec.frame_width, x=x, y=y):
                        self.assertEqual(self.pixel(draw, x, y, x, y), (15, 15, 15))
                        self.assertEqual(self.pixel(draw, x + 3 * step_x, y, x, y), (15, 15, 15))
                        self.assertEqual(self.pixel(draw, x, y + 3 * step_y, x, y), (15, 15, 15))
                        self.assertEqual(self.pixel(draw, x + step_x, y + step_y, x, y), (0, 0, 0))

    def test_cursor_pipeline_delays_rgb_and_sync_together(self):
        previous = [(0, 0, 0, 0, 0)] * 2
        for x, y, active, hs, vs in ((960, 540, 1, 0, 1), (10, 10, 1, 1, 0),
                                      (960, 540, 0, 1, 1), (966, 540, 1, 0, 0)):
            sig = vga_timing_signals_t(pos=vga_pos_t(x=x, y=y), active=active,
                                      hsync=hs, vsync=vs, start_of_frame=0, end_of_frame=0)
            bg = vga_12bpp_t(r=3, g=4, b=5, hs=hs, vs=vs)
            expected = p.sim_call(_raw_cursor, sig, bg, 960, 540, 0, 0, 0, 0, 0)
            result = p.sim_call(pipelined_cursor, sig, bg)
            self.assertEqual(tuple(result), previous.pop(0))
            previous.append(tuple(expected))


if __name__ == "__main__":
    unittest.main()
