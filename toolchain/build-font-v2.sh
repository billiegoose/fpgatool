#!/usr/bin/env bash
# Run inside ./fpgatool.sh shell; retain the normal pinned timing database.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/build/basys3/vga_uart_1920_1080_font_v2_demo"
export FPGA_TOOL_CHIPDB_DIR="$ROOT/build/font-v2-timingdb"
python3 scripts/build_font_v2_timing_db.py --output "$FPGA_TOOL_CHIPDB_DIR"
bash toolchain/build-pipelinec.sh /opt/PipelineC \
    "$ROOT/examples/vga_uart_1920_1080_font_v2_demo.py" "$OUT" \
    boards/basys3/pins.xdc xc7a35tcpg236-1 xc7a35tcpg236.bin --comb
python3 - "$OUT/pipelinec/top/open_tools_final.log" <<'PY'
from pathlib import Path
import sys
from fpgatool import validate_final_timing
log = Path(sys.argv[1])
if "Max frequency for clock 'clk_148p5':" not in log.read_text():
    raise SystemExit(f'Missing final pixel-clock timing report: {log}')
validate_final_timing(log)
print('Final font-v2 route passes timing.')
PY
