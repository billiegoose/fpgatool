"""Opt-in hardware-backend regression for the saved-placement routing path.

Run inside the fpgatool shell with NEXTPNR_RESUME_TEST_BIN pointing at the raw
nextpnr-himbaechel executable and NEXTPNR_RESUME_TEST_CHIPDB at the Basys 3 DB.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    os.environ.get("NEXTPNR_RESUME_TEST_BIN")
    and os.environ.get("NEXTPNR_RESUME_TEST_CHIPDB")
    and shutil.which("yosys"),
    "requires explicit nextpnr/chipdb paths and yosys",
)
class ResumeDelayMatrixTests(unittest.TestCase):
    @classmethod
    def run_tool(cls, command, name):
        result = subprocess.run(command, cwd=cls.root, capture_output=True, text=True)
        output = result.stdout + result.stderr
        (cls.root / name).write_text(output)
        if result.returncode:
            raise RuntimeError(f"{name}: exit {result.returncode}\n{output[-4000:]}")
        return output

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="nextpnr-resume-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        (cls.root / "counter.v").write_text("""module top(input clk, output led);
reg [7:0] counter = 0;
always @(posedge clk) counter <= counter + 1;
assign led = counter[7];
endmodule
""")
        (cls.root / "counter.xdc").write_text("""set_property LOC W5 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]
set_property LOC U16 [get_ports led]
set_property IOSTANDARD LVCMOS33 [get_ports led]
create_clock -period 10 [get_ports clk]
""")
        cls.run_tool(
            [
                "yosys",
                "-Q",
                "-T",
                "-p",
                "read_verilog counter.v; synth_xilinx -family xc7 -top top; "
                "write_json mapped.json",
            ],
            "map.log",
        )
        cls.base = [
            os.environ["NEXTPNR_RESUME_TEST_BIN"],
            "--chipdb",
            os.environ["NEXTPNR_RESUME_TEST_CHIPDB"],
            "--device",
            os.environ.get("NEXTPNR_RESUME_TEST_DEVICE", "xc7a35tcpg236"),
            "-o",
            "xdc=counter.xdc",
        ]
        cls.run_tool(
            [
                *cls.base,
                "--json",
                "mapped.json",
                "--no-route",
                "--write",
                "placed.json",
                "--seed",
                "1",
            ],
            "place.log",
        )
        cls.placed_hash = hashlib.sha256(
            (cls.root / "placed.json").read_bytes()
        ).hexdigest()

    def resume(self, name, options=()):
        output = self.run_tool(
            [
                *self.base,
                "--json",
                "placed.json",
                "--no-pack",
                "--no-place",
                "--write",
                f"{name}.json",
                "--report",
                f"{name}-report.json",
                *options,
            ],
            f"{name}.log",
        )
        self.assertIn("Program finished normally.", output)
        routed = json.loads((self.root / f"{name}.json").read_text())
        self.assertEqual(int(routed["modules"]["top"]["settings"]["route"], 2), 1)
        clocks = re.findall(
            r"Max frequency for clock\s+'([^']+)': ([0-9.]+) MHz "
            r"\((PASS|FAIL) at ([0-9.]+) MHz\)",
            output,
        )
        self.assertTrue(clocks, output[-4000:])
        self.assertTrue(all(row[2] == "PASS" for row in clocks), clocks)
        self.assertEqual(
            hashlib.sha256((self.root / "placed.json").read_bytes()).hexdigest(),
            self.placed_hash,
        )
        return output

    def test_resumed_route_initializes_model(self):
        output = self.resume("default")
        self.assertRegex(
            output, r"Delay matrix: [1-9][0-9]* of [0-9]+ offsets measured"
        )

    def test_resumed_route_honors_explicit_disable(self):
        output = self.resume("disabled", ["-o", "delay-matrix=off"])
        self.assertNotIn("Delay matrix:", output)


if __name__ == "__main__":
    unittest.main()
