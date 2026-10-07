"""A successful nextpnr exit must not hide a failing final routed clock."""
import tempfile
from pathlib import Path
import unittest
from test_fpgatool import fpgatool


class FinalTimingTests(unittest.TestCase):
    def check(self, text):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'open_tools_final.log'
            report.write_text(text)
            fpgatool.validate_final_timing(report)

    def test_final_failure_overrides_placement_pass(self):
        with self.assertRaisesRegex(fpgatool.FPGAToolError, '143.72 MHz vs 148.50 MHz'):
            self.check("Info: Max frequency for clock 'pixel': 190.91 MHz (PASS at 148.50 MHz)\n"
                       "Warning: Max frequency for clock 'pixel': 143.72 MHz (FAIL at 148.50 MHz)\n")

    def test_final_pass_overrides_placement_failure(self):
        self.check("Warning: Max frequency for clock 'pixel': 140.00 MHz (FAIL at 148.50 MHz)\n"
                   "Info: Max frequency for clock 'pixel': 158.03 MHz (PASS at 148.50 MHz)\n")

    def test_each_clock_must_pass(self):
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'uart:'):
            self.check("Info: Max frequency for clock 'pixel': 158.03 MHz (PASS at 148.50 MHz)\n"
                       "Warning: Max frequency for clock 'uart': 99.00 MHz (FAIL at 100.00 MHz)\n")

    def test_missing_final_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(fpgatool.FPGAToolError, 'missing'):
                fpgatool.validate_final_timing(Path(directory) / 'missing.log')


if __name__ == '__main__':
    unittest.main()
