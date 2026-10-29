#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/run-tests.py" "$@"
