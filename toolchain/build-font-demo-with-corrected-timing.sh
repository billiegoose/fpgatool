#!/usr/bin/env bash
# Build the 1080p font-v2 FPGA demo with an isolated corrected timing database.
# Require a passing final route. This produces a bitstream; it does not load it.
# Run inside ./fpgatool.sh shell; retain the normal pinned timing database.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/build/basys3/vga_uart_1920_1080_font_v2_demo"
export FPGA_TOOL_CHIPDB_DIR="$ROOT/build/font-v2-timingdb"
# The reusable live-flash service is validated with placement seed 4.
export PIPELINEC_OPEN_TOOLS_SEED="${PIPELINEC_OPEN_TOOLS_SEED:-4}"
python3 scripts/build_font_v2_timing_db.py --output "$FPGA_TOOL_CHIPDB_DIR"
bash toolchain/build-pipelinec.sh /opt/PipelineC \
    "$ROOT/examples/vga_uart_1920_1080_font_v2_demo.py" "$OUT" \
    boards/basys3/pins.xdc xc7a35tcpg236-1 xc7a35tcpg236.bin --comb
timing_log="$OUT/pipelinec/top/open_tools_final"
if [ "$PIPELINEC_OPEN_TOOLS_SEED" != 1 ]; then
  timing_log="${timing_log}_seed${PIPELINEC_OPEN_TOOLS_SEED}"
fi
python3 - "${timing_log}.log" <<'PY'
from pathlib import Path
import re
import sys
from fpgatool import validate_final_timing
log = Path(sys.argv[1])
if not re.search(r"Max frequency for clock\s+'clk_148p5':", log.read_text()):
    raise SystemExit(f'Missing final pixel-clock timing report: {log}')
validate_final_timing(log)
print('Final font-v2 route passes timing.')
PY
