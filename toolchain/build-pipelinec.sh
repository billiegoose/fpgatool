#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 5 ]; then
  echo "usage: build-pipelinec.sh PIPELINEC_DIR SOURCE OUT_DIR CONSTRAINTS CHIPDB_NAME" >&2
  exit 2
fi

pipelinec_dir="$1"
source_file="$2"
out_dir="$3"
constraints_rel="$4"
chipdb_name="$5"

: "${FPGA_TOOL_PIPELINEC_PYTHON:?missing pinned PipelineC Python from Nix shell}"
: "${FPGA_TOOL_CHIPDB_DIR:?missing generated chipdb from Nix shell}"
: "${PRJXRAY_DB_DIR:?missing Project X-Ray DB from OpenXC7 Nix shell}"

chipdb="$FPGA_TOOL_CHIPDB_DIR/$chipdb_name"
constraints="$pipelinec_dir/$constraints_rel"

[ -f "$source_file" ] || { echo "design not found: $source_file" >&2; exit 1; }
[ -f "$constraints" ] || { echo "constraints not found: $constraints" >&2; exit 1; }
[ -f "$chipdb" ] || { echo "chipdb not found: $chipdb" >&2; exit 1; }

rm -rf "$out_dir/pipelinec"
mkdir -p "$out_dir/pipelinec"

export OPENXC7_CHIPDB="$chipdb"

# The source lives outside PipelineC, so make its reusable Pypeline library and
# board modules importable without making host PYTHONPATH part of the contract.
export PYTHONPATH="$pipelinec_dir/include/pypeline${PYTHONPATH:+:$PYTHONPATH}"

"$FPGA_TOOL_PIPELINEC_PYTHON" "$pipelinec_dir/src/pipelinec" \
  "$source_file" \
  --syn_tool openxc7 \
  --no_sweep \
  --pins "$constraints" \
  --out_dir "$out_dir/pipelinec"
