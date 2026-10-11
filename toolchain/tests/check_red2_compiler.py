#!/usr/bin/env python3
"""Compare the RED2 compiler regression's native and emitted VHDL traces."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--nvc-command", default="nvc")
    args = parser.parse_args()
    compiler = args.compiler.absolute()
    out = args.out.absolute()
    out.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).with_name("red2_elif_priority.py").absolute()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(compiler / "src"), str(compiler / "include" / "pypeline"),
        env.get("PYTHONPATH", ""),
    ])

    def run(command, log):
        with log.open("w") as stream:
            subprocess.run(command, cwd=out, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        return log.read_text()

    driver = [sys.executable, str(compiler / "src" / "pypelinec"), str(fixture), "--comb"]
    native = run(driver + ["--sim", "--run", "all", "--out_dir", str(out / "native")],
                 out / "native.log")
    assert "stopping early at cycle 31" in native, "native sim did not reach sim_finish"
    hdl = out / "hdl"
    run(driver + ["--no_synth", "--out_dir", str(hdl)], out / "frontend.log")
    files = [Path(p) for p in (hdl / "vhdl_files.txt").read_text().split()]
    texts = {p: p.read_text() for p in files}
    entities = {name.lower(): p for p, text in texts.items()
                for name in re.findall(r"\bentity\s+(\w+)\s+is", text, re.I)}
    ordered, seen = [], set()

    def visit(path):
        if path in seen:
            return
        seen.add(path)
        for name in re.findall(r"\bentity\s+work\.(\w+)", texts[path], re.I):
            if name.lower() in entities:
                visit(entities[name.lower()])
        ordered.append(path)

    for path in files:
        if "package " in texts[path].lower():
            visit(path)
    for path in files:
        visit(path)
    tb = out / "red2_elif_tb.vhd"
    tb.write_text("""library ieee;
use ieee.std_logic_1164.all;
entity red2_elif_tb is end;
architecture test of red2_elif_tb is
  signal clk : std_logic := '0';
begin
  clk <= not clk after 5 ns;
  dut: entity work.top port map(clk_None => clk);
end;
""")
    nvc = shlex.split(args.nvc_command) + ["--std=2008"]
    run(nvc + ["-a", *map(str, ordered), str(tb)], out / "analyze.log")
    run(nvc + ["-e", "red2_elif_tb"], out / "elaborate.log")
    vhdl = run(nvc + ["-r", "red2_elif_tb", "--stop-time=1us", "--exit-severity=error"],
               out / "vhdl.log")
    assert "FINISH called" in vhdl, "HDL did not reach sim_finish"
    pattern = r"^\[SIM DEBUG PRINT:.*?\]: (general_elif_priority.*)$"
    native_rows = re.findall(pattern, native, re.M)
    vhdl_rows = re.findall(pattern, vhdl, re.M)
    assert len(native_rows) == len(vhdl_rows) == 31, (len(native_rows), len(vhdl_rows))
    assert native_rows == vhdl_rows, "native/VHDL trace mismatch; inspect the saved logs"
    print("PASS: 31 native/VHDL trace rows match; both simulations reached sim_finish")


if __name__ == "__main__":
    main()
