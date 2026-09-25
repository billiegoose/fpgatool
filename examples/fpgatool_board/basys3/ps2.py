# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 PS/2 physical clock/data pins.

Pypeline sees ordinary unidirectional signals: ``*_I`` samples the resolved
pad and ``*_T`` is the IOBUF-style tristate control (1 = release/high-Z,
0 = pull low).  A synthesis-final hook rewrites only the generated board-facing
VHDL boundary into the two real bidirectional package pins.
"""

import os
import re
from pathlib import Path

from pypeline import Input, Output, final, uint1_t

PS2Clk_I: Input[uint1_t]
PS2Clk_T: Output[uint1_t]
PS2Data_I: Input[uint1_t]
PS2Data_T: Output[uint1_t]


def _rewrite_pad(text: str, pad: str, sample: str, tristate: str) -> str:
    """Lower one split open-drain interface into a physical inout top port."""
    sample_decl = re.compile(
        rf"(?m)^(?P<indent>\s*){re.escape(sample)}\s*:\s*in\s+unsigned\(0 downto 0\);?\s*$"
    )
    tristate_decl = re.compile(
        rf"(?m)^\s*{re.escape(tristate)}\s*:\s*out\s+unsigned\(0 downto 0\);?\s*$"
    )
    sample_match = sample_decl.search(text)
    if sample_match is None or tristate_decl.search(text) is None:
        raise RuntimeError(
            f"Basys 3 PS/2 final-top rewrite could not find {sample}/{tristate} ports"
        )

    text = sample_decl.sub(
        rf"\g<indent>{pad} : inout unsigned(0 downto 0);", text, count=1
    )
    text = tristate_decl.sub("", text, count=1)

    readback = re.compile(
        rf"(?m)^(?P<lhs>\s*global_to_module\.[^.]+\.{re.escape(sample)})\s*<=\s*{re.escape(sample)};\s*$"
    )
    text, n_read = readback.subn(rf"\g<lhs> <= {pad};", text, count=1)

    drive = re.compile(
        rf"(?m)^\s*{re.escape(tristate)}\s*<=\s*(?P<intent>module_to_global\.[^;]+);\s*$"
    )
    drive_match = drive.search(text)
    if drive_match is None:
        raise RuntimeError(
            f"Basys 3 PS/2 final-top rewrite could not find {tristate} drive assignment"
        )
    intent = drive_match.group("intent")
    physical_drive = (
        f"{pad} <= to_unsigned(0, 1) when {intent} = unsigned'(0 => '0') "
        "else (others => 'Z');"
    )
    text, n_drive = drive.subn(physical_drive, text, count=1)
    if n_read != 1 or n_drive != 1:
        raise RuntimeError(
            f"Basys 3 PS/2 final-top rewrite expected one read/write for {pad}, "
            f"got read={n_read} drive={n_drive}"
        )
    return text


def _normalize_top_port_semicolons(text: str) -> str:
    """Keep the generated entity port list valid after removing logical ports."""
    entity = re.search(r"(?s)(entity\s+top\s+is\s*\nport\(\n)(.*?)(\n\s*\);\s*\nend\s+top;)", text)
    if entity is None:
        raise RuntimeError("Basys 3 PS/2 final-top rewrite could not find entity top port list")
    body = entity.group(2)
    lines = body.splitlines()
    decl_indexes = [
        i for i, line in enumerate(lines)
        if ":" in line and not line.lstrip().startswith("--") and line.strip()
    ]
    if not decl_indexes:
        raise RuntimeError("Basys 3 PS/2 final-top rewrite found an empty top port list")
    for i in decl_indexes[:-1]:
        lines[i] = lines[i].rstrip().rstrip(";") + ";"
    i = decl_indexes[-1]
    lines[i] = lines[i].rstrip().rstrip(";")
    replacement = entity.group(1) + "\n".join(lines) + entity.group(3)
    return text[: entity.start()] + replacement + text[entity.end() :]


def _rewrite_final_top_text(text: str) -> str:
    text = _rewrite_pad(text, "PS2Clk", "PS2Clk_I", "PS2Clk_T")
    text = _rewrite_pad(text, "PS2Data", "PS2Data_I", "PS2Data_T")
    return _normalize_top_port_semicolons(text)


@final(syn=True)
def _bind_basys3_ps2_pads():
    top_path = os.environ.get("FPGATOOL_FINAL_TOP_VHDL")
    if not top_path:
        raise RuntimeError(
            "Basys 3 PS/2 synthesis requires FPGATOOL_FINAL_TOP_VHDL to identify "
            "the generated board-facing top"
        )
    path = Path(top_path)
    text = path.read_text()
    path.write_text(_rewrite_final_top_text(text))
