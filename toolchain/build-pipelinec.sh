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
export PYTHONPATH="$pipelinec_dir/src:$pipelinec_dir/include/pypeline${PYTHONPATH:+:$PYTHONPATH}"

# PipelineC currently treats @final(syn) as one-shot even though a --comb
# synthesis build rewrites the final top after its throughput sweep.  Board
# boundary hooks (PS/2, QSPI) must therefore run again on the regenerated
# top.vhd immediately before final implementation.  Keep the pinned compiler
# checkout read-only: patch only a per-build driver copy.
pipelinec_driver="$out_dir/pipelinec-driver.py"
cp "$pipelinec_dir/src/pipelinec" "$pipelinec_driver"
"$FPGA_TOOL_PIPELINEC_PYTHON" - "$pipelinec_driver" <<'PYDRIVER'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
old = 'if _syn_final_hooks_ran or not src_file.endswith(".py"):'
new = 'if not src_file.endswith(".py"):'
if text.count(old) != 1:
    raise SystemExit(f"expected one PipelineC final-hook guard, found {text.count(old)}")
path.write_text(text.replace(old, new, 1))
PYDRIVER

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

"$FPGA_TOOL_PIPELINEC_PYTHON" "$pipelinec_driver" "${pipelinec_args[@]}"

# OpenXC7 compatibility workaround for the Basys 3 configuration-flash SO pin.
# Legacy nextpnr-xilinx accepts the XDC PULLUP constraint but can emit
# PULLTYPE.NONE for QspiDQ1 (D19 / IOB_X0Y47.Y1).  Only inspect/patch that
# feature when the synthesized board-facing design actually contains QspiDQ1;
# the Basys 3 board XDC also names pins unused by ordinary designs such as blink.
# Modern Himbächel with XDC pull normalization emits PULLTYPE.PULLUP directly,
# in which case this compatibility block is intentionally a no-op.
final_top_dir="$out_dir/pipelinec/top"
final_fasm="$final_top_dir/top.fasm"
final_json="$final_top_dir/top.json"
dq1_in_design=0
if grep -Fq 'set_property PULLUP true [get_ports QspiDQ1]' "$constraints" \
    && [ -f "$final_fasm" ]; then
  [ -f "$final_json" ] || { echo "final Yosys JSON missing while checking Basys 3 QspiDQ1 workaround" >&2; exit 1; }
  dq1_in_design=$("$FPGA_TOOL_PIPELINEC_PYTHON" - "$final_json" <<'PYJSON'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
modules = data.get("modules", {})
top = modules.get("top")
if top is None:
    if len(modules) != 1:
        raise SystemExit("could not identify final top module while checking QspiDQ1")
    top = next(iter(modules.values()))
print(1 if "QspiDQ1" in top.get("ports", {}) else 0)
PYJSON
  )
fi
if [ "$dq1_in_design" -eq 1 ]; then
  dq1_none='LIOB33_X0Y47.IOB_Y1.PULLTYPE.NONE'
  dq1_pullup='LIOB33_X0Y47.IOB_Y1.PULLTYPE.PULLUP'
  if grep -Fqx "$dq1_none" "$final_fasm"; then
    echo "Applying OpenXC7 Basys 3 QspiDQ1 pull-up workaround..."
    sed -i "s/^${dq1_none}$/${dq1_pullup}/" "$final_fasm"
    (
      cd "$final_top_dir"
      fasm2frames \
        --part "$part" \
        --db-root "$PRJXRAY_DB_DIR/artix7" \
        top.fasm > top.frames
      xc7frames2bit \
        --part_file "$PRJXRAY_DB_DIR/artix7/$part/part.yaml" \
        --part_name "$part" \
        --frm_file top.frames \
        --output_file top.bit
    )
  elif ! grep -Fqx "$dq1_pullup" "$final_fasm"; then
    echo "expected Basys 3 QspiDQ1 PULLTYPE feature missing from final FASM" >&2
    exit 1
  fi
fi
