"""Timing snapshots must isolate choices without duplicating compiled logic."""

import copy
import unittest

try:
    from AUTO_PIPELINE import TimingParams
except ImportError:
    TimingParams = None


class SharedLogic:
    def __deepcopy__(self, memo):
        raise AssertionError("a timing snapshot must not copy the compiled logic graph")


@unittest.skipIf(TimingParams is None, "requires the patched PipelineC environment")
class TimingSnapshotTests(unittest.TestCase):
    def test_snapshot_shares_logic_and_isolates_timing_choices(self):
        logic = SharedLogic()
        original = TimingParams("cursor", logic)
        original._slices = [0.25, 0.75]
        original._exact_bit_boundaries = [4, 8]
        original._has_input_regs = True
        original.calcd_total_latency = 3
        snapshot = copy.deepcopy({"cursor": original, "alias": original})
        saved = snapshot["cursor"]
        self.assertIs(saved, snapshot["alias"])
        self.assertIsNot(saved, original)
        self.assertIs(saved.logic, logic)
        self.assertEqual(saved._slices, [0.25, 0.75])
        self.assertEqual(saved._exact_bit_boundaries, [4, 8])
        self.assertTrue(saved._has_input_regs)
        self.assertEqual(saved.calcd_total_latency, 3)
        saved._slices.append(0.9)
        saved._exact_bit_boundaries.append(12)
        saved._has_input_regs = False
        self.assertEqual(original._slices, [0.25, 0.75])
        self.assertEqual(original._exact_bit_boundaries, [4, 8])
        self.assertTrue(original._has_input_regs)

    def test_snapshot_preserves_unset_boundaries(self):
        original = TimingParams("cursor", SharedLogic())
        saved = copy.deepcopy(original)
        self.assertIsNone(saved._exact_bit_boundaries)
        self.assertEqual(saved._slices, [])
        self.assertIsNot(saved._slices, original._slices)


if __name__ == "__main__":
    unittest.main()
