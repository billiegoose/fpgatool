"""Exercise the board boundary rewrite without requiring a synthesis install."""

import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pixel_clock", ROOT / "examples/fpgatool_board/basys3/clock_148p5.py"
)
pixel_clock = importlib.util.module_from_spec(SPEC)
with mock.patch.dict("sys.modules", {"pypeline": SimpleNamespace(final=lambda **kw: lambda fn: fn)}):
    SPEC.loader.exec_module(pixel_clock)


TOP = """entity top is
port(
clk_148p5 : in std_logic;
VGA_HS : out unsigned(0 downto 0)
);
end top;
architecture arch of top is
begin
design : entity work.design port map (
clk_148p5,
to_unsigned(1,1),
VGA_HS);
end arch;
"""


class PixelClockTests(unittest.TestCase):
    def test_oscillator_is_external_and_pixel_clock_is_internal(self):
        result = pixel_clock._rewrite_final_top_text(TOP)
        ports = result.split("end top;")[0]
        self.assertIn("clk_100p0 : in std_logic;", ports)
        self.assertNotIn("clk_148p5", ports)
        self.assertIn("signal clk_148p5,", result)
        self.assertIn("CLKIN1 => clk_100p0", result)
        self.assertIn("O => clk_148p5", result)
        self.assertIn("clk_148p5,\nunsigned'(0 => pixel_ready),", result)
        self.assertIn("VGA_HS : out unsigned(0 downto 0)", result)

    def test_repeated_hook_does_not_duplicate_clock_hardware(self):
        once = pixel_clock._rewrite_final_top_text(TOP)
        self.assertEqual(pixel_clock._rewrite_final_top_text(once), once)

    def test_unexpected_clock_fails_instead_of_producing_wrong_hardware(self):
        with self.assertRaisesRegex(RuntimeError, "clock port"):
            pixel_clock._rewrite_final_top_text(TOP.replace("clk_148p5", "clk_100p0"))

    def test_missing_main_enable_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "MAIN instance"):
            pixel_clock._rewrite_final_top_text(TOP.replace("to_unsigned(1,1)", "other_enable"))

    def test_input_clock_constraint_is_local_and_hook_can_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "top.vhd"
            board = Path(tmp) / "board.xdc"
            top.write_text(TOP)
            original_xdc = "set_property LOC W5 [get_ports clk_100p0]\n"
            board.write_text(original_xdc)
            syn = SimpleNamespace(PIN_CONSTRAINTS_FILE=str(board))
            with mock.patch.dict("sys.modules", {"SYN": syn}), mock.patch.dict(
                os.environ, {"FPGATOOL_FINAL_TOP_VHDL": str(top)}
            ):
                pixel_clock._bind_basys3_pixel_clock()
                first_top = top.read_text()
                # --comb regenerates the unbound top before the second hook.
                top.write_text(TOP)
                pixel_clock._bind_basys3_pixel_clock()
            self.assertEqual(top.read_text(), first_top)
            self.assertEqual(board.read_text(), original_xdc)
            self.assertNotEqual(syn.PIN_CONSTRAINTS_FILE, str(board))
            constraints = Path(syn.PIN_CONSTRAINTS_FILE).read_text()
            self.assertEqual(constraints.count("create_clock"), 1)
            self.assertIn("-period 10.0 [get_ports clk_100p0]", constraints)


if __name__ == "__main__":
    unittest.main()
