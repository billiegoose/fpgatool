#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 6 ] || [ "$#" -gt 7 ]; then
  echo "usage: build-pipelinec.sh PIPELINEC_DIR SOURCE OUT_DIR CONSTRAINTS PART CHIPDB_NAME [--comb]" >&2
  exit 2
fi

pipelinec_dir="$1"
source_file="$2"
out_dir="$3"
constraints_rel="$4"
part="$5"
chipdb_name="$6"
comb_arg="${7:-}"
if [ -n "$comb_arg" ] && [ "$comb_arg" != "--comb" ]; then
  echo "unknown build-pipelinec.sh option: $comb_arg" >&2
  exit 2
fi

: "${FPGA_TOOL_PIPELINEC_PYTHON:?missing pinned PipelineC Python from Nix shell}"
: "${FPGA_TOOL_CHIPDB_DIR:?missing generated chipdb from Nix shell}"
: "${PRJXRAY_DB_DIR:?missing Project X-Ray DB from OpenXC7 Nix shell}"

chipdb="$FPGA_TOOL_CHIPDB_DIR/$chipdb_name"
constraints="/workspace/$constraints_rel"

[ -f "$source_file" ] || { echo "design not found: $source_file" >&2; exit 1; }
[ -f "$constraints" ] || { echo "constraints not found: $constraints" >&2; exit 1; }
[ -f "$chipdb" ] || { echo "chipdb not found: $chipdb" >&2; exit 1; }

rm -rf "$out_dir/pipelinec"
mkdir -p "$out_dir/pipelinec"

export OPENXC7_CHIPDB="$chipdb"
# PipelineC caches measured synthesis data under one cache root. Keep that
# cache in the writable per-design build tree because the pinned compiler
# checkout is mounted read-only.
export PYPELINEC_CACHE_DIR="$out_dir/cache"
export FPGATOOL_FINAL_TOP_VHDL="$out_dir/pipelinec/top/top.vhd"

# The source lives outside PipelineC, so make its reusable Pypeline library and
# board modules importable without making host PYTHONPATH part of the contract.
export PYTHONPATH="$pipelinec_dir/include/pypeline${PYTHONPATH:+:$PYTHONPATH}"

pipelinec_args=(
  "$source_file"
  --syn_tool open_tools
  --part "$part"
)
if [ "$comb_arg" = "--comb" ]; then
  pipelinec_args+=(--comb)
fi
pipelinec_args+=(
  --pins "$constraints"
  --out_dir "$out_dir/pipelinec"
)

"$FPGA_TOOL_PIPELINEC_PYTHON" "$pipelinec_dir/src/pipelinec" "${pipelinec_args[@]}"
