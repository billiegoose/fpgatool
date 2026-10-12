"""Opt-in regression for both data sides of a RAMB36E1 72-bit SDP write.

Uses the same NEXTPNR_RESUME_TEST_BIN/CHIPDB environment as the resume test.
The old backend legally routes this design but omits WRITE_WIDTH_A_18.
"""

import json
import os
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
class Sdp72WriteWidthTests(unittest.TestCase):
    def test_both_ram_halves_configure_both_write_sides(self):
        with tempfile.TemporaryDirectory(prefix="nextpnr-sdp72-") as directory:
            root = Path(directory)
            (root / "ram.v").write_text("""module top(
input clk, input we, input serial_bit, input [8:0] addr, output led);
reg [63:0] data = 0;
(* ram_style = "block" *) reg [63:0] memory [0:511];
reg [63:0] q;
always @(posedge clk) begin
  data <= {data[62:0], serial_bit};
  if (we) memory[addr] <= data;
  q <= memory[addr];
end
assign led = ^q;
endmodule
""")
            (root / "ram.xdc").write_text("""set_property LOC W5 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]
set_property LOC U16 [get_ports led]
set_property IOSTANDARD LVCMOS33 [get_ports led]
create_clock -period 100 [get_ports clk]
""")
            pins = ["V17", "V16", "W16", "W17", "W15", "V15", "W14", "W13", "V2"]
            with (root / "ram.xdc").open("a") as xdc:
                for port, pin in [
                    *[(f"addr[{i}]", pin) for i, pin in enumerate(pins)],
                    ("we", "T3"),
                    ("serial_bit", "T2"),
                ]:
                    xdc.write(f"set_property LOC {pin} [get_ports {{{port}}}]\n")
                    xdc.write(
                        f"set_property IOSTANDARD LVCMOS33 [get_ports {{{port}}}]\n"
                    )

            def run(command, name):
                result = subprocess.run(
                    command, cwd=root, capture_output=True, text=True
                )
                output = result.stdout + result.stderr
                (root / name).write_text(output)
                self.assertEqual(result.returncode, 0, output[-4000:])
                return output

            run(
                [
                    "yosys",
                    "-Q",
                    "-T",
                    "-p",
                    "read_verilog ram.v; synth_xilinx -family xc7 -top top; "
                    "write_json mapped.json",
                ],
                "map.log",
            )
            mapped = json.loads((root / "mapped.json").read_text())
            brams = [
                cell
                for cell in mapped["modules"]["top"]["cells"].values()
                if cell["type"] == "RAMB36E1"
            ]
            self.assertEqual(len(brams), 1)
            self.assertEqual(int(brams[0]["parameters"]["WRITE_WIDTH_B"], 2), 72)
            self.assertEqual(int(brams[0]["parameters"]["WRITE_WIDTH_A"], 2), 0)
            output = run(
                [
                    os.environ["NEXTPNR_RESUME_TEST_BIN"],
                    "--chipdb",
                    os.environ["NEXTPNR_RESUME_TEST_CHIPDB"],
                    "--device",
                    "xc7a35tcpg236",
                    "-o",
                    "xdc=ram.xdc",
                    "-o",
                    "fasm=ram.fasm",
                    "--json",
                    "mapped.json",
                    "--seed",
                    "1",
                ],
                "route.log",
            )
            self.assertIn("Program finished normally.", output)
            self.assertIn("PASS at 10.00 MHz", output)
            features = set((root / "ram.fasm").read_text().splitlines())
            for side in ("A", "B"):
                matches = [
                    feature
                    for feature in features
                    if feature.endswith(f".WRITE_WIDTH_{side}_18")
                ]
                self.assertEqual(len(matches), 2, (side, matches))
                self.assertTrue(any(".RAMB18_Y0." in value for value in matches))
                self.assertTrue(any(".RAMB18_Y1." in value for value in matches))


if __name__ == "__main__":
    unittest.main()
