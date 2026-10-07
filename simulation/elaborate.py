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
SYN.SYN_OUTPUT_DIRECTORY = str(out / 'vhdl')
SYN.TOP_LEVEL_MODULE = 'top'
state = PY_TO_LOGIC.PARSE_FILE(str(source))
C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(state)
SYN.WRITE_FINAL_FILES(None, state)
files = shlex.split((out / 'vhdl/vhdl_files.txt').read_text())
# Preserve explicit register behavior, while removing hierarchy preservation
# attributes that otherwise defeat optimization in the generated HDL.
if any(any(c.isspace() for c in f) for f in files):
    raise ValueError('GHDL import requires source paths without whitespace')
script = 'ghdl --std=08 -frelaxed ' + ' '.join(files) + ' -e top\n'
script += 'setattr -unset keep\nsetattr -unset syn_keep\nsetattr -unset dont_touch\n'
# Preserve BRAM as behavioral memories rather than expanding every bit into gates.
script += 'hierarchy -check -top top\nproc\nflatten\nopt\nmemory -nomap\nopt\ntechmap\nopt\ncheck -assert\nrename -hide\n'
script += f'write_verilog -noattr "{out / "top.v"}"\n'
(out / 'translate.ys').write_text(script)
subprocess.run(['yosys', '-m', os.environ['PYPELINEC_YOSYS_GHDL_PLUGIN'],
                '-s', str(out / 'translate.ys')], check=True)
