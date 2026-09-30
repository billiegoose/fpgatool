# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 configuration-flash physical interface.

Pypeline sees each QSPI data pad as ordinary split unidirectional signals:
``*_I`` samples the resolved pad, ``*_O`` is the push-pull output value, and
``*_T`` is the IOBUF-style tristate control (1 = high-Z, 0 = drive ``*_O``).
A synthesis-final hook rewrites those logical ports into the four real
bidirectional package pins.

The flash clock is the Artix-7 configuration CCLK pin, which user logic can
only drive through STARTUPE2. Important OpenXC7 detail: USRCCLKTS must be
routed from fabric, not tied to a constant. ``drive_clock_and_cs`` therefore
takes an explicit, non-constant ``cclk_ts`` input. cclk_ts=0 enables CCLK;
cclk_ts=1 tri-states it.
"""

import os
import re
from pathlib import Path

from pypeline import Input, Output, final, hw_func, sim_model, uint1_t, vhdl

QspiCSn: Output[uint1_t]

QspiDQ0_I: Input[uint1_t]
QspiDQ0_O: Output[uint1_t]
QspiDQ0_T: Output[uint1_t]
QspiDQ1_I: Input[uint1_t]
QspiDQ1_O: Output[uint1_t]
QspiDQ1_T: Output[uint1_t]
QspiDQ2_I: Input[uint1_t]
QspiDQ2_O: Output[uint1_t]
QspiDQ2_T: Output[uint1_t]
QspiDQ3_I: Input[uint1_t]
QspiDQ3_O: Output[uint1_t]
QspiDQ3_T: Output[uint1_t]


_STARTUPE2_VHDL = r"""
component STARTUPE2 is
  generic(
    PROG_USR : string := "FALSE";
    SIM_CCLK_FREQ : real := 0.0
  );
  port(
    CFGCLK : out std_logic;
    CFGMCLK : out std_logic;
    EOS : out std_logic;
    PREQ : out std_logic;
    CLK : in std_logic;
    GSR : in std_logic;
    GTS : in std_logic;
    KEYCLEARB : in std_logic;
    PACK : in std_logic;
    USRCCLKO : in std_logic;
    USRCCLKTS : in std_logic;
    USRDONEO : in std_logic;
    USRDONETS : in std_logic
  );
end component;
begin
qspi_startup : STARTUPE2
  port map(
    CFGCLK => open,
    CFGMCLK => open,
    EOS => open,
    PREQ => open,
    CLK => '0',
    GSR => '0',
    GTS => '0',
    KEYCLEARB => '1',
    PACK => '0',
    USRCCLKO => cclk(0),
    USRCCLKTS => cclk_ts(0),
    USRDONEO => '1',
    USRDONETS => '1'
  );
return_output <= cs_n;
"""


@hw_func
def drive_clock_and_cs(cclk: uint1_t, cs_n: uint1_t, cclk_ts: uint1_t) -> uint1_t:
    """Drive configuration CCLK through STARTUPE2 and pass CS# through unchanged."""
    vhdl(_STARTUPE2_VHDL)


@sim_model(drive_clock_and_cs)
@hw_func
def _drive_clock_and_cs_sim(cclk: uint1_t, cs_n: uint1_t, cclk_ts: uint1_t) -> uint1_t:
    return cs_n


def _rewrite_pad(text: str, pad: str) -> str:
    """Lower one split push-pull interface into a physical inout top port."""
    sample = f"{pad}_I"
    output = f"{pad}_O"
    tristate = f"{pad}_T"
    sample_decl = re.compile(
        rf"(?m)^(?P<indent>\s*){re.escape(sample)}\s*:\s*in\s+unsigned\(0 downto 0\);?\s*$"
    )
    output_decl = re.compile(
        rf"(?m)^\s*{re.escape(output)}\s*:\s*out\s+unsigned\(0 downto 0\);?\s*$"
    )
    tristate_decl = re.compile(
        rf"(?m)^\s*{re.escape(tristate)}\s*:\s*out\s+unsigned\(0 downto 0\);?\s*$"
    )
    sample_match = sample_decl.search(text)
    if sample_match is None or output_decl.search(text) is None or tristate_decl.search(text) is None:
        raise RuntimeError(
            f"Basys 3 QSPI final-top rewrite could not find {sample}/{output}/{tristate} ports"
        )

    text = sample_decl.sub(
        rf"\g<indent>{pad} : inout unsigned(0 downto 0);", text, count=1
    )
    text = output_decl.sub("", text, count=1)
    text = tristate_decl.sub("", text, count=1)

    readback = re.compile(
        rf"(?m)^(?P<lhs>\s*global_to_module\.[^.]+\.{re.escape(sample)})\s*<=\s*{re.escape(sample)};\s*$"
    )
    text, n_read = readback.subn(rf"\g<lhs> <= {pad};", text, count=1)

    output_drive = re.compile(
        rf"(?m)^\s*{re.escape(output)}\s*<=\s*(?P<value>module_to_global\.[^;]+);\s*$"
    )
    tristate_drive = re.compile(
        rf"(?m)^\s*{re.escape(tristate)}\s*<=\s*(?P<enable>module_to_global\.[^;]+);\s*$"
    )
    output_match = output_drive.search(text)
    tristate_match = tristate_drive.search(text)
    if output_match is None or tristate_match is None:
        raise RuntimeError(
            f"Basys 3 QSPI final-top rewrite could not find {output}/{tristate} drive assignments"
        )
    value = output_match.group("value")
    enable = tristate_match.group("enable")
    text = output_drive.sub("", text, count=1)
    physical_drive = (
        f"{pad} <= {value} when {enable} = unsigned'(0 => '0') "
        "else (others => 'Z');"
    )
    text, n_drive = tristate_drive.subn(physical_drive, text, count=1)
    if n_read > 1 or n_drive != 1:
        raise RuntimeError(
            f"Basys 3 QSPI final-top rewrite expected zero/one read and one write for {pad}, "
            f"got read={n_read} drive={n_drive}"
        )
    return text


def _normalize_top_port_semicolons(text: str) -> str:
    """Keep the generated entity port list valid after removing logical ports."""
    entity = re.search(r"(?s)(entity\s+top\s+is\s*\nport\(\n)(.*?)(\n\s*\);\s*\nend\s+top;)", text)
    if entity is None:
        raise RuntimeError("Basys 3 QSPI final-top rewrite could not find entity top port list")
    body = entity.group(2)
    lines = body.splitlines()
    decl_indexes = [
        i for i, line in enumerate(lines)
        if ":" in line and not line.lstrip().startswith("--") and line.strip()
    ]
    if not decl_indexes:
        raise RuntimeError("Basys 3 QSPI final-top rewrite found an empty top port list")
    for i in decl_indexes[:-1]:
        lines[i] = lines[i].rstrip().rstrip(";") + ";"
    i = decl_indexes[-1]
    lines[i] = lines[i].rstrip().rstrip(";")
    replacement = entity.group(1) + "\n".join(lines) + entity.group(3)
    return text[: entity.start()] + replacement + text[entity.end() :]


def _rewrite_final_top_text(text: str) -> str:
    for index in range(4):
        text = _rewrite_pad(text, f"QspiDQ{index}")
    return _normalize_top_port_semicolons(text)


@final(syn=True)
def _bind_basys3_qspi_pads():
    top_path = os.environ.get("FPGATOOL_FINAL_TOP_VHDL")
    if not top_path:
        raise RuntimeError(
            "Basys 3 QSPI synthesis requires FPGATOOL_FINAL_TOP_VHDL to identify "
            "the generated board-facing top"
        )
    path = Path(top_path)
    text = path.read_text()
    path.write_text(_rewrite_final_top_text(text))
