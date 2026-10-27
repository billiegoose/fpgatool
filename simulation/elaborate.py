"""Generate as-written VHDL and optimize it inside the pinned Nix environment."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

# This directory also contains our receiver vga.py; the design imports the
# pinned PipelineC vga package instead.
sys.path.remove(str(Path(__file__).resolve().parent))
source, out = map(Path, sys.argv[1:])
import PY_TO_LOGIC
import C_TO_LOGIC
import SYN
import AUTO_PIPELINE
SYN.SYN_OUTPUT_DIRECTORY = str(out / 'vhdl')
SYN.TOP_LEVEL_MODULE = 'top'
# As-written simulation needs no physical implementation tool. AUTO combinational
# rewrites and fixed pipeline cuts still need a timing model during elaboration;
# use the compiler's estimator rather than an unset synthesis backend.
SYN.SYN_TOOL = SYN.GET_TOOL_MODULE('pyrtl')
state = PY_TO_LOGIC.PARSE_FILE(str(source))
C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)
timing = AUTO_PIPELINE.BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS(state)
SYN.WRITE_FINAL_FILES(timing, state)
files = shlex.split((out / 'vhdl/vhdl_files.txt').read_text())
# Preserve explicit register behavior, while removing hierarchy preservation
# attributes that otherwise defeat optimization in the generated HDL.
if any(any(c.isspace() for c in f) for f in files):
    raise ValueError('GHDL import requires source paths without whitespace')
script = 'ghdl --std=08 -frelaxed ' + ' '.join(files) + ' -e top\n'
script += 'setattr -unset keep\nsetattr -unset syn_keep\nsetattr -unset dont_touch\n'
# Preserve BRAM as behavioral memories rather than expanding every bit into gates.
# Split packed aliases before Verilator sees them. AUTO pipeline cuts can
# connect different bits of the same temporary bus in opposite directions;
# these are acyclic per bit but otherwise force expensive UNOPTFLAT settling.
script += 'hierarchy -check -top top\nproc\nflatten\nopt\nmemory -nomap\nopt\ntechmap\nopt\nsplitnets -ports\ncheck -assert\nrename -hide\n'
script += f'write_verilog -noattr "{out / "top.v"}"\n'
(out / 'translate.ys').write_text(script)
subprocess.run(['yosys', '-m', os.environ['PYPELINEC_YOSYS_GHDL_PLUGIN'],
                '-s', str(out / 'translate.ys')], check=True)
