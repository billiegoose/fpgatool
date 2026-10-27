#!/usr/bin/env bash
set -euo pipefail

# Follow symlinks so ~/bin/fpgatool works regardless of the working directory.
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
    DIR="$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd -P)"
    LINK="$(readlink "$SOURCE")"
    if [[ "$LINK" = /* ]]; then
        SOURCE="$LINK"
    else
        SOURCE="$DIR/$LINK"
    fi
done
ROOT="$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "fpgatool: missing virtual environment: $PYTHON" >&2
    echo "Initialize it with: uv venv --python 3.12 '$ROOT/.venv'" >&2
    exit 1
fi
exec "$PYTHON" "$ROOT/fpgatool.py" "$@"
