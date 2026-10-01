"""Test clock planning without requiring the synthesis toolchain.

The full example build additionally checks real Pypeline elaboration and routing.
"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import NamedTuple
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "clock_under_test", ROOT / "examples/hardware/xilinx7_clock.py"
)
clock = importlib.util.module_from_spec(SPEC)
# Stub only the decorators/types; clock parameter validation runs unchanged.
runtime = SimpleNamespace(
    NamedTuple=NamedTuple, hw_func=lambda fn: fn, struct=lambda cls: cls,
    uint1_t=int, vhdl=lambda text: text,
)
with mock.patch.dict(sys.modules, {"pypeline": runtime, SPEC.name: clock}):
    SPEC.loader.exec_module(clock)


class PixelClockTests(unittest.TestCase):
    def test_hardware_proven_1080p_ratios(self):
        gen = clock.make_mmcm_clock(100, clock.MmcmStage(27, 4, 5), clock.MmcmStage(11, 2, 5))
        self.assertEqual(gen.input_mhz, 100)
        self.assertEqual(gen.output_mhz, 148.5)

    def test_other_integer_pixel_rates(self):
        for divide, expected in [(32, 25), (20, 40), (16, 50)]:
            with self.subTest(expected=expected):
                gen = clock.make_mmcm_clock(100, clock.MmcmStage(8, 1, divide))
                self.assertEqual(gen.output_mhz, expected)

    def test_invalid_input_frequencies(self):
        for rate in [0, -1, float("nan"), float("inf"), 801]:
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                clock.make_mmcm_clock(rate, clock.MmcmStage(8, 1, 8))

    def test_empty_chain_rejected(self):
        with self.assertRaises(ValueError):
            clock.make_mmcm_clock(100)

    def test_invalid_dividers_rejected(self):
        for stage in [clock.MmcmStage(8.5, 1, 8), clock.MmcmStage(65, 1, 8),
                      clock.MmcmStage(8, 0, 8), clock.MmcmStage(8, 1, 129),
                      clock.MmcmStage(True, 1, 8)]:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                clock.make_mmcm_clock(100, stage)

    def test_invalid_vco_rejected(self):
        for multiplier in [5, 13]:
            with self.subTest(multiplier=multiplier), self.assertRaisesRegex(ValueError, "VCO"):
                clock.make_mmcm_clock(100, clock.MmcmStage(multiplier, 1, 8))

    def test_stage_two_is_validated_against_stage_one_output(self):
        with self.assertRaisesRegex(ValueError, "stage 1 VCO"):
            clock.make_mmcm_clock(100, clock.MmcmStage(8, 1, 32), clock.MmcmStage(8, 1, 8))

    def test_output_too_fast_rejected(self):
        with self.assertRaisesRegex(ValueError, "output"):
            clock.make_mmcm_clock(100, clock.MmcmStage(12, 1, 1))

    def test_phase_detector_too_fast_rejected(self):
        with self.assertRaisesRegex(ValueError, "PFD"):
            clock.make_mmcm_clock(600, clock.MmcmStage(2, 1, 4))


if __name__ == "__main__":
    unittest.main()
