"""Configure I0 BUFG route-throughs omitted by the pinned Xilinx FASM writer.

The router can traverse an unused BUFGCTRL I0->O as a data-routing resource.
Its FASM writer emits the input/output routing but configures BUFGCTRL only for
placed cells. Without IN_USE, a legal-looking route therefore carries zero.
Use the same static I0 mode as an instantiated BUFG. Existing cells, including
gated clocks, are preserved. Reject modes this workaround has not qualified.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

OUTPUT = re.compile(
    r"(CLK_BUFG_(?:BOT|TOP)_R_X\d+Y\d+)\.CLK_BUFG_CK_GCLK(\d+)"
    r"\.CLK_BUFG_BUFGCTRL(\d+)_O"
)
MODE = ("IN_USE", "IS_IGNORE1_INVERTED", "ZINV_CE0", "ZINV_S0")


def complete(source):
    features = {
        line.split("#", 1)[0].strip()
        for line in source.splitlines()
        if line.split("#", 1)[0].strip()
    }
    additions, buffers = set(), []
    for feature in sorted(features):
        match = OUTPUT.fullmatch(feature)
        if not match:
            continue
        tile, clock, index = match.groups()
        if clock != index or not 0 <= int(index) < 16:
            raise ValueError(f"unexpected BUFG output route: {feature}")
        prefix = f"{tile}.BUFGCTRL.BUFGCTRL_X0Y{index}."
        if prefix + "IN_USE" in features:
            continue
        if any(f.startswith(prefix) for f in features):
            raise ValueError(f"partially configured BUFG: {prefix}")
        inputs = set()
        controls = []
        for line in features:
            pin = re.match(
                re.escape(tile) + rf"\.CLK_BUFG_(?:R_)?BUFGCTRL{index}_(\w+)\.",
                line,
            )
            if not pin:
                continue
            if pin[1] in {"I0", "I1"}:
                inputs.add(pin[1])
            elif pin[1] in {"CE0", "CE1", "S0", "S1", "IGNORE0", "IGNORE1"}:
                controls.append(line)
        if inputs != {"I0"} or controls:
            raise ValueError(
                f"unsupported implicit BUFG {prefix}: inputs={sorted(inputs)}, "
                f"control routes={controls}"
            )
        added = [prefix + mode for mode in MODE]
        additions.update(added)
        buffers.append(
            {"tile": tile, "index": int(index), "mode": "static I0", "features": added}
        )
    if not additions:
        return source, buffers
    return source.rstrip("\n") + "\n" + "\n".join(sorted(additions)) + "\n", buffers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    before = args.input.read_bytes()
    result, buffers = complete(before.decode("ascii"))
    after = result.encode("ascii")
    args.output.write_bytes(after)
    args.report.write_text(
        json.dumps(
            {
                "input_sha256": hashlib.sha256(before).hexdigest(),
                "output_sha256": hashlib.sha256(after).hexdigest(),
                "configured_route_throughs": buffers,
                "scope": (
                    "Static I0 BUFG route-through configuration only; "
                    "existing cells and routing unchanged"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"BUFG_ROUTE_THROUGH_CONFIG_PASS {len(buffers)}")


if __name__ == "__main__":
    main()
