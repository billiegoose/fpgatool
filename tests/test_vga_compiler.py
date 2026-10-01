"""Elaborate every consumer of the parametric VGA pattern."""

from pathlib import Path
import tempfile
import unittest

try:
    import PY_TO_LOGIC
    import C_TO_LOGIC
    import SYN
except ImportError:
    COMPILER_AVAILABLE = False
else:
    COMPILER_AVAILABLE = True


@unittest.skipUnless(COMPILER_AVAILABLE, "requires the patched Pypeline build environment")
class VgaCompilerTests(unittest.TestCase):
    def test_all_pattern_consumers_elaborate(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        for name in ("vga_test_bars.py", "vga_800_600_test_bars.py",
                     "vga_1920_1080_test_bars.py", "kitchen_sink_demo.py"):
            with self.subTest(example=name), tempfile.TemporaryDirectory() as tmp:
                SYN.SYN_OUTPUT_DIRECTORY = tmp
                SYN.TOP_LEVEL_MODULE = "top"
                state = PY_TO_LOGIC.PARSE_FILE(str(examples / name))
                C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)
                self.assertTrue(list((Path(tmp) / "top").glob("top*.vhd")))


if __name__ == "__main__":
    unittest.main()
