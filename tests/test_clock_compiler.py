"""Compiler regression tests; run in fpgatool shell with patched PYTHONPATH."""

from pathlib import Path
import tempfile
import textwrap
import unittest

try:
    import PY_TO_LOGIC
    import C_TO_LOGIC
    import SYN
    import OPEN_TOOLS
except ImportError:
    COMPILER_AVAILABLE = False
else:
    COMPILER_AVAILABLE = True


@unittest.skipUnless(COMPILER_AVAILABLE, "requires the patched Pypeline build environment")
class ClockCompilerTests(unittest.TestCase):
    def parse(self, source):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "design.py"
        path.write_text(textwrap.dedent(source))
        SYN.SYN_OUTPUT_DIRECTORY = str(Path(tmp.name) / "out")
        SYN.TOP_LEVEL_MODULE = "top"
        return PY_TO_LOGIC.PARSE_FILE(str(path))

    def crossing(self, annotation):
        return self.parse(f"""
            from pypeline import *
            PART("xc7a35tcpg236-1")
            async_state: {annotation}[uint1_t]
            result: Output[uint1_t]
            @MAIN(100.0)
            def sender():
                state: Reg[uint1_t] = 0
                state = ~state
                async_state = state
            @MAIN(50.0)
            def receiver():
                result = async_state
        """)

    def test_explicit_async_crossing_emits_vhdl(self):
        state = self.crossing("AsyncWire")
        self.assertIn("async_state", state.async_wires)
        C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)

    def test_ordinary_wire_crossing_remains_rejected(self):
        state = self.crossing("Wire")
        self.assertNotIn("async_state", state.async_wires)
        with self.assertRaisesRegex(Exception, "multiple clock domains"):
            C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)

    def test_async_wire_initializer_rejected(self):
        with self.assertRaisesRegex(PY_TO_LOGIC.ElaborationError, "initializer"):
            self.parse("""
                from pypeline import *
                async_state: AsyncWire[uint1_t] = 1
                @MAIN(100.0)
                def main():
                    return 0
            """)

    def test_async_wire_local_declaration_rejected(self):
        with self.assertRaises(PY_TO_LOGIC.ElaborationError):
            self.parse("""
                from pypeline import *
                @MAIN(100.0)
                def main():
                    async_state: AsyncWire[uint1_t]
                    return 0
            """)

    def test_clock_primitive_without_interior_paths(self):
        report = OPEN_TOOLS.ParsedTimingReport(
            "Info: No Fmax available; no interior timing paths found in design."
        )
        self.assertEqual(len(report.path_reports), 1)
        self.assertEqual(next(iter(report.path_reports.values())).path_delay_ns, 0)

    def test_distinct_factory_configs_and_native_clock_ports(self):
        examples = str(Path(__file__).resolve().parents[1] / "examples")
        state = self.parse(f"""
            import sys
            sys.path.insert(0, {examples!r})
            from pypeline import *
            from hardware.xilinx7_clock import make_mmcm_clock, MmcmStage
            PART("xc7a35tcpg236-1")
            gen25 = make_mmcm_clock(100.0, MmcmStage(8, 1, 32))
            gen40 = make_mmcm_clock(100.0, MmcmStage(8, 1, 20))
            clock25: Wire[uint1_t] = make_clock(25.0)
            clock40: Wire[uint1_t] = make_clock(40.0)
            out25: Output[uint1_t]
            out40: Output[uint1_t]
            @MAIN(100.0)
            def clocks():
                a = gen25(0)
                b = gen40(0)
                clock25 = a.clock
                clock40 = b.clock
            @MAIN(25.0)
            def slow():
                counter: Reg[uint1_t] = 0
                counter = ~counter
                out25 = counter
            @MAIN(40.0)
            def fast():
                counter: Reg[uint1_t] = 0
                counter = ~counter
                out40 = counter
        """)
        bodies = [logic.vhdl_module_text for logic in state.FuncLogicLookupTable.values()
                  if logic.vhdl_module_text is not None]
        self.assertTrue(any('CLKOUT0_DIVIDE_F => "32.0"' in body for body in bodies))
        self.assertTrue(any('CLKOUT0_DIVIDE_F => "20.0"' in body for body in bodies))
        C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)
        top_files = list((Path(SYN.SYN_OUTPUT_DIRECTORY) / "top").glob("top*.vhd"))
        self.assertEqual(len(top_files), 1)
        top = top_files[0].read_text()
        ports = top.split("architecture", 1)[0]
        self.assertIn("clk_100p0 : in std_logic", ports)
        self.assertNotIn("clk_25p0 : in", ports)
        self.assertNotIn("clk_40p0 : in", ports)

    def test_malformed_timing_report_still_rejected(self):
        with self.assertRaisesRegex(Exception, "Bad synthesis log"):
            OPEN_TOOLS.ParsedTimingReport("not a timing report")


if __name__ == "__main__":
    unittest.main()
