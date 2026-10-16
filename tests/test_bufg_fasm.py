import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "toolchain/compat/complete-bufg-fasm.py"
spec = importlib.util.spec_from_file_location("bufg_fasm", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

TILE = "CLK_BUFG_BOT_R_X60Y48"
ROUTE = (
    f"{TILE}.CLK_BUFG_BUFGCTRL12_I0.CLK_BUFG_IMUX28_3\n"
    f"{TILE}.CLK_BUFG_CK_GCLK12.CLK_BUFG_BUFGCTRL12_O\n"
)
PREFIX = f"{TILE}.BUFGCTRL.BUFGCTRL_X0Y12."


class BufgFasmTests(unittest.TestCase):
    def test_completes_routed_buffer_and_preserves_original_features(self):
        result, buffers = module.complete(ROUTE)
        self.assertTrue(result.startswith(ROUTE))
        self.assertEqual(len(buffers), 1)
        self.assertEqual(
            set(result.splitlines()) - set(ROUTE.splitlines()),
            {
                PREFIX + "IN_USE",
                PREFIX + "IS_IGNORE1_INVERTED",
                PREFIX + "ZINV_CE0",
                PREFIX + "ZINV_S0",
            },
        )
        self.assertEqual(module.complete(result), (result, []))

    def test_existing_gated_buffer_is_untouched(self):
        source = ROUTE + PREFIX + "IN_USE\n" + PREFIX + "ZINV_CE1\n"
        self.assertEqual(module.complete(source), (source, []))

    def test_rejects_unqualified_input_or_control_mode(self):
        for source in [
            ROUTE.replace("_I0.", "_I1."),
            ROUTE + f"{TILE}.CLK_BUFG_R_BUFGCTRL12_CE0.IMUX0\n",
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                module.complete(source)

    def test_rejects_incomplete_configuration_or_missing_input(self):
        for source in [ROUTE + PREFIX + "ZINV_CE0\n", ROUTE.splitlines()[1] + "\n"]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                module.complete(source)

    def test_rejects_mismatched_output_index(self):
        with self.assertRaises(ValueError):
            module.complete(ROUTE.replace("GCLK12.", "GCLK11."))


if __name__ == "__main__":
    unittest.main()
