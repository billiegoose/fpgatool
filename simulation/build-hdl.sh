#!/usr/bin/env bash
set -euo pipefail
pipelinec_dir="$1"
source_file="$2"
out_dir="$3"
mkdir -p "$out_dir/compat/src"
for module in pypeline.py PY_TO_LOGIC.py OPEN_TOOLS.py pypeline_sim.py; do
  cp "$pipelinec_dir/src/$module" "$out_dir/compat/src/$module"
done
patch --batch --forward -p1 -d "$out_dir/compat" < /workspace/toolchain/patches/pypeline-native-clock-wires.patch
patch --batch --forward -p1 -d "$out_dir/compat" < /workspace/toolchain/patches/pypeline-sim-factory-annotations.patch
export PYTHONPATH="$out_dir/compat/src:$pipelinec_dir/src:$pipelinec_dir/include/pypeline:/workspace/examples${PYTHONPATH:+:$PYTHONPATH}"
export PYPELINEC_CACHE_DIR="$out_dir/pipelinec-cache"
"$FPGA_TOOL_PIPELINEC_PYTHON" /workspace/simulation/elaborate.py "$source_file" "$out_dir"
