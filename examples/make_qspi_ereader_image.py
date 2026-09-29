#!/usr/bin/env python3
"""Pack a text file into the Basys 3 worst-e-reader 64 KiB flash image."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SECTOR_SIZE = 64 * 1024
MAGIC = b"ERDR"
HEADER_SIZE = 6
MAX_TEXT = SECTOR_SIZE - HEADER_SIZE


def normalize_text(text: str) -> bytes:
    # The seven-segment renderer intentionally targets a compact ASCII subset.
    text = text.upper().replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text).strip()
    data = text.encode("ascii", errors="replace")
    if len(data) > MAX_TEXT:
        raise ValueError(f"text is {len(data)} bytes; maximum is {MAX_TEXT}")
    if not data:
        raise ValueError("text is empty after normalization")
    return data


def build_image(text: str) -> bytes:
    data = normalize_text(text)
    image = bytearray(b"\xff" * SECTOR_SIZE)
    image[0:4] = MAGIC
    image[4:6] = len(data).to_bytes(2, "big")
    image[6 : 6 + len(data)] = data
    return bytes(image)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    image = build_image(args.input.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    length = int.from_bytes(image[4:6], "big")
    print(f"wrote {len(image)} bytes; text length={length}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
