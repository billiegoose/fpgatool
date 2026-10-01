"""Pattern checks using Pypeline's native hardware-function simulator."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
import sys
import unittest

try:
    from pypeline import sim_call
    from vga.types import vga_pos_t, vga_timing_signals_t
    from vga.timing import VGA_640_480, VGA_800_600, VGA_1280_720, VGA_1920_1080
except ImportError:
    PYPELINE_AVAILABLE = False
else:
    PYPELINE_AVAILABLE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from hardware.vga_test_bars import make_vga_test_bars


@unittest.skipUnless(PYPELINE_AVAILABLE, "requires the Pypeline runtime and VGA library")
class VgaTestBarsTests(unittest.TestCase):
    MODES = (VGA_640_480, VGA_800_600, VGA_1920_1080, VGA_1280_720) if PYPELINE_AVAILABLE else ()
    COLORS = ((15, 15, 15), (15, 15, 0), (0, 15, 15), (0, 15, 0),
              (15, 0, 15), (15, 0, 0), (0, 0, 15))

    def pixel(self, draw, x, y, active=1, hs=0, vs=0):
        sig = vga_timing_signals_t(
            pos=vga_pos_t(x=x, y=y), active=active, hsync=hs, vsync=vs,
            start_of_frame=0, end_of_frame=0,
        )
        px = sim_call(draw, sig)
        self.assertEqual((px.hs, px.vs), (hs, vs))
        return (px.r, px.g, px.b)

    def test_seven_even_bars_in_color_order(self):
        for timing in self.MODES:
            width, height, marker = timing.frame_width, timing.frame_height, 5
            with self.subTest(width=width):
                draw = make_vga_test_bars(timing)
                row = [self.pixel(draw, x, height // 4) for x in range(width)]
                runs = [rgb for x, rgb in enumerate(row) if x == 0 or rgb != row[x - 1]]
                self.assertEqual(runs, list(self.COLORS))
                widths = Counter(row).values()
                self.assertLessEqual(max(widths) - min(widths), 1)

    def test_640_bar_boundaries_are_unchanged(self):
        draw = make_vga_test_bars(VGA_640_480)
        for i, boundary in enumerate((91, 183, 274, 366, 457, 549)):
            self.assertEqual(self.pixel(draw, boundary - 1, 120), self.COLORS[i])
            self.assertEqual(self.pixel(draw, boundary, 120), self.COLORS[i + 1])

    def test_blanking_and_sync_passthrough(self):
        for timing in self.MODES:
            width, height, marker = timing.frame_width, timing.frame_height, 5
            draw = make_vga_test_bars(timing)
            for hs in (0, 1):
                for vs in (0, 1):
                    self.assertEqual(self.pixel(draw, 10, 50, 0, hs, vs), (0, 0, 0))
                    self.assertEqual(self.pixel(draw, 10, height // 4, 1, hs, vs), self.COLORS[0])

    def test_marker_edges_and_center_x(self):
        for timing in self.MODES:
            width, height, marker = timing.frame_width, timing.frame_height, 5
            with self.subTest(width=width):
                draw = make_vga_test_bars(timing)
                # Both legs of every corner, including their last black pixel.
                for x, y in ((6 * marker - 1, marker - 1), (marker - 1, 6 * marker - 1)):
                    for px in (x, width - 1 - x):
                        for py in (y, height - 1 - y):
                            self.assertEqual(self.pixel(draw, px, py), (0, 0, 0))
                self.assertNotEqual(self.pixel(draw, marker, marker), (0, 0, 0))
                self.assertNotEqual(self.pixel(draw, 6 * marker, 0), (0, 0, 0))
                cx, cy = width // 2, height // 2
                for dx in (-2, 1):
                    for y in (0, 4 * marker - 1, height - 4 * marker, height - 1):
                        self.assertEqual(self.pixel(draw, cx + dx, y), (0, 0, 0))
                for dy in (-2, 1):
                    for x in (0, 4 * marker - 1, width - 4 * marker, width - 1):
                        self.assertEqual(self.pixel(draw, x, cy + dy), (0, 0, 0))
                self.assertNotEqual(self.pixel(draw, cx - 3, 0), (0, 0, 0))
                # Inspect the entire square and its border: only the two
                # diagonals are black, with equal horizontal/vertical reach.
                for dy in range(-11, 12):
                    for dx in range(-11, 12):
                        black = self.pixel(draw, cx + dx, cy + dy) == (0, 0, 0)
                        self.assertEqual(black, abs(dx) == abs(dy) and abs(dx) <= 10,
                                         (width, dx, dy))

    def test_factories_do_not_share_dimensions(self):
        small = make_vga_test_bars(VGA_640_480)
        large = make_vga_test_bars(VGA_1920_1080)
        for _ in range(2):
            self.assertEqual(self.pixel(small, 320, 240), (0, 0, 0))
            self.assertEqual(self.pixel(large, 320, 240), self.COLORS[1])

    def test_invalid_geometry_rejected(self):
        for width, height in ((0, 480), (640, -1), (640.5, 480),
                              (4097, 480), (640, 4097), (20, 20)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                make_vga_test_bars(replace(VGA_640_480, frame_width=width, frame_height=height))



if __name__ == "__main__":
    unittest.main()
