#!/usr/bin/env python3
"""Small host-side orchestrator for reproducible FPGA builds and programming.

The synthesis toolchain runs inside Podman + Nix.  Programming intentionally
stays on the host so USB/JTAG passthrough is not part of the build environment.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".fpgatool"
CACHE_DIR = STATE_DIR / "cache"
PIPELINEC_DIR = CACHE_DIR / "PipelineC"
ADJACENT_PIPELINEC_DIR = ROOT.parent / "PipelineC"
BUILD_ROOT = ROOT / "build"
LOCK_FILE = ROOT / "toolchain.lock.toml"
TOOLCHAIN_DIR = ROOT / "toolchain"
NIX_VOLUME = "fpgatool-nix"
DEFAULT_BOARD = "basys3"
DEFAULT_SOURCE = ROOT / "examples" / "blink.py"
VERBOSE = False


class FPGAToolError(RuntimeError):
    pass


def run(
    cmd: list[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess:
    if VERBOSE:
        print("+ " + shlex.join(str(x) for x in cmd), flush=True)
        return subprocess.run(cmd, check=check, cwd=cwd)
    if log_path is None:
        return subprocess.run(cmd, check=check, cwd=cwd)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        return subprocess.run(
            cmd,
            check=check,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
        )


def output(cmd: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def load_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def lock_config() -> dict:
    return load_toml(LOCK_FILE)


def board_config(name: str) -> dict:
    path = ROOT / "boards" / f"{name}.toml"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ROOT / "boards").glob("*.toml"))) or "none"
        raise FPGAToolError(f"unknown board {name!r}; available boards: {known}")
    cfg = load_toml(path)
    cfg["_name"] = name
    return cfg


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FPGAToolError(f"required host tool not found on PATH: {name}")
    return path


def ensure_podman() -> None:
    require_tool("podman")
    # On Linux this is a harmless no-op/failure; on macOS it starts the VM.
    subprocess.run(
        ["podman", "machine", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    probe = subprocess.run(
        ["podman", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        raise FPGAToolError("Podman is installed but its engine is not available")


def ensure_nix_volume() -> None:
    probe = subprocess.run(
        ["podman", "volume", "inspect", NIX_VOLUME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        run(["podman", "volume", "create", NIX_VOLUME])


def checkout_matches_pipelinec_pin(path: Path, repo: str, rev: str) -> bool:
    # .git is a directory for ordinary clones and a file for Git worktrees.
    if not (path / ".git").exists():
        return False
    try:
        actual_repo = output(["git", "remote", "get-url", "origin"], cwd=path)
        current = output(["git", "rev-parse", "HEAD"], cwd=path)
        dirty = output(["git", "status", "--porcelain"], cwd=path)
    except subprocess.CalledProcessError:
        return False
    normalized_actual = actual_repo.rstrip("/").removesuffix(".git")
    normalized_expected = repo.rstrip("/").removesuffix(".git")
    return normalized_actual == normalized_expected and current == rev and not dirty


def ensure_pipelinec() -> Path:
    require_tool("git")
    cfg = lock_config()["pipelinec"]
    repo = cfg["repo"]
    rev = cfg["rev"]

    # Reuse a sibling checkout when it is exactly the pinned revision and clean.
    # This is only an optimization; correctness still comes from the lock file.
    if checkout_matches_pipelinec_pin(ADJACENT_PIPELINEC_DIR, repo, rev):
        if VERBOSE:
            print(f"Using pinned PipelineC checkout: {ADJACENT_PIPELINEC_DIR}")
        return ADJACENT_PIPELINEC_DIR

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not (PIPELINEC_DIR / ".git").is_dir():
        run(["git", "clone", "--filter=blob:none", "--no-checkout", repo, str(PIPELINEC_DIR)])
    else:
        actual_repo = output(["git", "remote", "get-url", "origin"], cwd=PIPELINEC_DIR)
        if actual_repo.rstrip("/").removesuffix(".git") != repo.rstrip("/").removesuffix(".git"):
            raise FPGAToolError(
                f"cached PipelineC checkout has unexpected origin {actual_repo!r}; expected {repo!r}"
            )

    have = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
        cwd=PIPELINEC_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not have:
        run(["git", "fetch", "--depth", "1", "origin", rev], cwd=PIPELINEC_DIR)

    current = ""
    try:
        current = output(["git", "rev-parse", "HEAD"], cwd=PIPELINEC_DIR)
    except subprocess.CalledProcessError:
        pass
    if current != rev:
        run(["git", "checkout", "--detach", rev], cwd=PIPELINEC_DIR)

    dirty = output(["git", "status", "--porcelain"], cwd=PIPELINEC_DIR)
    if dirty:
        raise FPGAToolError(f"cached PipelineC checkout is dirty: {PIPELINEC_DIR}")
    return PIPELINEC_DIR


def normalize_source(path: str | Path) -> Path:
    source = Path(path).expanduser()
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    else:
        source = source.resolve()
    if not source.is_file():
        raise FPGAToolError(f"design source does not exist: {source}")
    try:
        source.relative_to(ROOT)
    except ValueError as exc:
        raise FPGAToolError(
            "this first fpgatool version requires the design source to live under the fpgatool checkout"
        ) from exc
    return source


def build_dir(board: str, source: Path) -> Path:
    return BUILD_ROOT / board / source.stem


def bitstream_path(board: str, source: Path) -> Path:
    return build_dir(board, source) / f"{source.stem}.bit"


def podman_base(*, pipelinec_dir: Path, interactive: bool = False) -> list[str]:
    cmd = ["podman", "run", "--rm"]
    if interactive:
        cmd += ["-it"]
    cmd += [
        "-v", f"{NIX_VOLUME}:/nix",
        "-v", f"{ROOT}:/workspace",
        "-v", f"{pipelinec_dir}:/opt/PipelineC:ro",
        "-w", "/workspace",
        lock_config()["container"]["nix_image"],
    ]
    return cmd


def container_design_path(source: Path) -> str:
    return "/workspace/" + source.relative_to(ROOT).as_posix()


def container_build_dir(board: str, source: Path) -> str:
    return "/workspace/" + build_dir(board, source).relative_to(ROOT).as_posix()


def cmd_build(args: argparse.Namespace) -> Path:
    source = normalize_source(args.source)
    if source.suffix.lower() == ".bit":
        raise FPGAToolError("build expects a design source; use load or program for an existing .bit file")
    board = board_config(args.board)
    if board["backend"]["type"] != "pipelinec-openxc7":
        raise FPGAToolError(f"unsupported backend type: {board['backend']['type']}")

    print("Preparing toolchain...")
    ensure_podman()
    ensure_nix_volume()
    pipelinec_dir = ensure_pipelinec()

    out_dir = build_dir(args.board, source)
    out_dir.mkdir(parents=True, exist_ok=True)
    final_bit = bitstream_path(args.board, source)
    if final_bit.exists():
        final_bit.unlink()

    pc_constraints = board["backend"]["constraints"]
    container_cmd = podman_base(pipelinec_dir=pipelinec_dir) + [
        "nix",
        "--extra-experimental-features", "nix-command flakes",
        "develop", "path:/workspace/toolchain",
        "--command", "bash", "/workspace/toolchain/build-pipelinec.sh",
        "/opt/PipelineC",
        container_design_path(source),
        container_build_dir(args.board, source),
        pc_constraints,
        board["fpga"]["part"],
        board["fpga"]["chipdb"],
    ]
    if getattr(args, "comb", False):
        container_cmd.append("--comb")
    build_log = out_dir / "build.log"
    print(f"Building {source.relative_to(ROOT)} for {board['name']}...")
    try:
        run(container_cmd, log_path=build_log)
    except subprocess.CalledProcessError as exc:
        raise FPGAToolError(f"build failed; see {build_log}") from exc

    generated = out_dir / "pipelinec" / "top" / "top.bit"
    if not generated.is_file():
        raise FPGAToolError(f"PipelineC completed without producing expected bitstream: {generated}")
    shutil.copy2(generated, final_bit)
    print(f"✓ Built {final_bit.relative_to(ROOT)}")
    return final_bit


def parse_offset(value: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid offset: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be non-negative")
    return parsed


def flash_layout(board: dict) -> tuple[int, int, int]:
    flash = board.get("flash")
    if not isinstance(flash, dict):
        raise FPGAToolError(f"board {board.get('name', '<unknown>')!r} does not define a flash layout")
    try:
        size = int(flash["size_bytes"])
        user_start = int(flash["user_data_offset"])
        erase_block = int(flash["erase_block_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FPGAToolError("invalid board flash layout") from exc
    if not (0 <= user_start < size) or erase_block <= 0:
        raise FPGAToolError("invalid board flash layout bounds")
    if erase_block & (erase_block - 1):
        raise FPGAToolError("flash erase block size must be a power of two")
    if user_start % erase_block:
        raise FPGAToolError("user-data start must be erase-block aligned")
    if size % erase_block:
        raise FPGAToolError("flash size must be erase-block aligned")
    return size, user_start, erase_block


def validate_data_flash_write(board: dict, binary: Path, offset: int | None) -> tuple[int, int, int]:
    if not binary.is_file():
        raise FPGAToolError(f"binary file does not exist: {binary}")
    size, user_start, erase_block = flash_layout(board)
    if offset is None:
        offset = user_start
    length = binary.stat().st_size
    if length <= 0:
        raise FPGAToolError(f"binary file is empty: {binary}")
    if offset < user_start:
        raise FPGAToolError(
            f"offset 0x{offset:x} overlaps the FPGA configuration region; "
            f"user data starts at 0x{user_start:x}"
        )
    end = offset + length
    if end > size:
        raise FPGAToolError(
            f"binary does not fit in flash: 0x{offset:x} + 0x{length:x} "
            f"extends past 0x{size:x}"
        )
    return offset, length, erase_block


def openfpgaloader_data_command(board: dict, binary: Path, offset: int) -> list[str]:
    programmer = board["programmer"]
    if programmer["type"] != "openfpgaloader":
        raise FPGAToolError(f"unsupported programmer type: {programmer['type']}")
    if programmer.get("program_mode") != "flash":
        raise FPGAToolError(
            f"unsupported program_mode: {programmer.get('program_mode')!r}; expected 'flash'"
        )
    exe = require_tool("openFPGALoader")
    return [
        exe,
        "--board", programmer["board"],
        "-f",
        "--file-type", "bin",
        "--offset", str(offset),
        "--verify",
        "--bitstream", str(binary),
    ]


def openfpgaloader_command(board: dict, bitstream: Path, *, persistent: bool) -> list[str]:
    programmer = board["programmer"]
    if programmer["type"] != "openfpgaloader":
        raise FPGAToolError(f"unsupported programmer type: {programmer['type']}")
    expected_mode = "flash" if persistent else "sram"
    mode_key = "program_mode" if persistent else "load_mode"
    if programmer.get(mode_key) != expected_mode:
        raise FPGAToolError(
            f"unsupported {mode_key}: {programmer.get(mode_key)!r}; expected {expected_mode!r}"
        )
    exe = require_tool("openFPGALoader")
    cmd = [exe, "--board", programmer["board"]]
    if persistent:
        cmd.append("-f")
    cmd += ["--bitstream", str(bitstream)]
    return cmd


def require_bitstream(path: str | Path) -> Path:
    bitstream = normalize_source(path)
    if bitstream.suffix.lower() != ".bit":
        raise FPGAToolError(f"expected a .bit file: {bitstream}")
    return bitstream


def load_bitstream(board_name: str, bitstream: Path) -> None:
    board = board_config(board_name)
    if not bitstream.is_file():
        raise FPGAToolError(f"bitstream does not exist: {bitstream}")
    load_log = bitstream.parent / "load.log"
    print(f"Loading {board['name']} (volatile SRAM)...")
    try:
        run(openfpgaloader_command(board, bitstream, persistent=False), log_path=load_log)
    except subprocess.CalledProcessError as exc:
        raise FPGAToolError(f"load failed; see {load_log}") from exc
    print(f"✓ Loaded {board['name']}")


def program_bitstream(board_name: str, bitstream: Path) -> None:
    board = board_config(board_name)
    if not bitstream.is_file():
        raise FPGAToolError(f"bitstream does not exist: {bitstream}")
    program_log = bitstream.parent / "program.log"
    print(f"Programming {board['name']} flash (persistent)...")
    try:
        run(openfpgaloader_command(board, bitstream, persistent=True), log_path=program_log)
    except subprocess.CalledProcessError as exc:
        raise FPGAToolError(f"programming failed; see {program_log}") from exc
    print(f"✓ Programmed {board['name']} flash")


def cmd_load(args: argparse.Namespace) -> None:
    load_bitstream(args.board, require_bitstream(args.source))


def cmd_program(args: argparse.Namespace) -> None:
    program_bitstream(args.board, require_bitstream(args.source))


def cmd_program_data(args: argparse.Namespace) -> None:
    board = board_config(args.board)
    # Unlike design sources, host-side asset files do not need to live under the
    # fpgatool checkout: they are consumed directly by the native programmer.
    binary = Path(args.source).expanduser().resolve()
    offset, length, erase_block = validate_data_flash_write(board, binary, args.offset)
    touched_start = offset & ~(erase_block - 1)
    touched_end = (offset + length + erase_block - 1) & ~(erase_block - 1)
    log = ROOT / "build" / args.board / "program-data.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Programming {length} bytes to {board['name']} user flash "
        f"at 0x{offset:06x}..0x{offset + length - 1:06x}..."
    )
    if touched_start != offset or touched_end != offset + length:
        print(
            f"Note: SPI flash erase granularity is 0x{erase_block:x}; "
            f"the programmer may erase 0x{touched_start:06x}..0x{touched_end - 1:06x}."
        )
    try:
        run(openfpgaloader_data_command(board, binary, offset), log_path=log)
    except subprocess.CalledProcessError as exc:
        raise FPGAToolError(f"data programming failed; see {log}") from exc
    print(f"✓ Programmed and verified {binary} at 0x{offset:06x}")


def cmd_run(args: argparse.Namespace) -> None:
    source = normalize_source(args.source)
    if source.suffix.lower() == ".bit":
        raise FPGAToolError("run expects a design source; use load for an existing .bit file")
    bitstream = cmd_build(args)
    load_bitstream(args.board, bitstream)


def positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if n <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return n


def cmd_sim(args: argparse.Namespace) -> None:
    source = normalize_source(args.source)
    if source.suffix.lower() != ".py":
        raise FPGAToolError("sim expects a Pypeline .py design")
    if args.board != "basys3":
        raise FPGAToolError("VGA simulation currently supports the basys3 board")
    pipelinec = ensure_pipelinec()
    if args.sim_backend == "hdl":
        from simulation.compiled import simulate
        simulate(args, source, pipelinec)
        return
    compat = STATE_DIR / "sim-runtime"
    (compat / "src").mkdir(parents=True, exist_ok=True)
    for name in ("pypeline.py", "PY_TO_LOGIC.py", "OPEN_TOOLS.py", "pypeline_sim.py"):
        shutil.copy2(pipelinec / "src" / name, compat / "src" / name)
    run([require_tool("patch"), "--batch", "--forward", "-p1", "-d", str(compat),
         "-i", str(TOOLCHAIN_DIR / "patches" / "pypeline-native-clock-wires.patch")],
        log_path=compat / "patch.log")
    run([require_tool("patch"), "--batch", "--forward", "-p1", "-d", str(compat),
         "-i", str(TOOLCHAIN_DIR / "patches" / "pypeline-sim-factory-annotations.patch")],
        log_path=compat / "sim-patch.log")
    cmd = [sys.executable, str(ROOT / "simulation" / "run.py"), str(source),
           "--pipelinec", str(pipelinec), "--compat", str(compat / "src"),
           "--out", str(build_dir(args.board, source) / "sim"),
           "--frames", str(args.frames or 1)]
    if args.cycles:
        cmd += ["--cycles", str(args.cycles)]
    if args.vga_mode:
        cmd += ["--vga-mode", args.vga_mode]
    if args.no_open:
        cmd.append("--no-open")
    if args.screenshot:
        cmd += ["--screenshot", str(Path(args.screenshot).expanduser().resolve())]
    run(cmd)


def status_line(label: str, ok: bool, detail: str) -> None:
    mark = "✓" if ok else "✗"
    print(f"{label:<14} {mark} {detail}")


def cmd_doctor(args: argparse.Namespace) -> None:
    board = board_config(args.board)
    print(f"Board: {board['name']}\n")

    podman = shutil.which("podman")
    status_line("Podman", bool(podman), podman or "not found")
    if podman:
        subprocess.run(["podman", "machine", "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        info = subprocess.run(["podman", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        status_line("Podman engine", info.returncode == 0, "available" if info.returncode == 0 else "not running")

    git = shutil.which("git")
    status_line("Git", bool(git), git or "not found")

    loader = shutil.which("openFPGALoader")
    status_line("Programmer", bool(loader), loader or "openFPGALoader not found (build-only is still possible)")

    lock = lock_config()
    print(f"\nPipelineC     {lock['pipelinec']['rev']}")
    print(f"OpenXC7       {lock['openxc7']['rev']}")
    print(f"FPGA           {board['fpga']['part']}")
    print(f"Build output   {bitstream_path(args.board, normalize_source(args.source))}")


def cmd_shell(args: argparse.Namespace) -> None:
    ensure_podman()
    ensure_nix_volume()
    pipelinec_dir = ensure_pipelinec()
    cmd = podman_base(pipelinec_dir=pipelinec_dir, interactive=True) + [
        "nix",
        "--extra-experimental-features", "nix-command flakes",
        "develop", "path:/workspace/toolchain",
        "--command", "bash",
    ]
    run(cmd)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fpgatool.sh",
        description="Build or simulate FPGA designs, load volatile SRAM, or program persistent flash.",
    )
    p.add_argument("command", nargs="?", choices=("build", "load", "run", "sim", "program", "program-data", "doctor", "shell"))
    p.add_argument("source", nargs="?", help="design source, .bit file, or binary data file depending on command")
    p.add_argument("--board", default=DEFAULT_BOARD, help=f"board profile (default: {DEFAULT_BOARD})")
    p.add_argument("--offset", type=parse_offset, default=None, help="flash byte offset for program-data (default: board user-data start)")
    p.add_argument("--comb", action="store_true", help="disable PipelineC auto-pipelining and build the design as written")
    p.add_argument("-v", "--verbose", action="store_true", help="stream full toolchain output")
    p.add_argument("--frames", type=positive_int, default=None, help="sim: stop after N complete frames (default: continuous, or 1 with --no-open)")
    p.add_argument("--sim-backend", choices=("hdl", "python"), default="hdl", help="sim: compiled hardware (default) or native Python debugging")
    p.add_argument("--cycles", type=positive_int, help="sim: maximum clock events before stopping")
    p.add_argument("--vga-mode", choices=("640x480", "800x600", "1280x720", "1920x1080"), help="sim: override automatically discovered VGA timing")
    p.add_argument("--no-open", action="store_true", help="sim: save frames and exit without opening the monitor")
    p.add_argument("--screenshot", help="sim: also save the last complete frame to this PNG path")
    return p


def main() -> int:
    global VERBOSE
    p = parser()
    args = p.parse_args()
    VERBOSE = args.verbose
    if args.command is None:
        p.print_help()
        return 0
    if args.command in {"build", "load", "run", "sim", "program", "program-data"} and args.source is None:
        if args.command in {"load", "program"}:
            p.error(f"{args.command} requires a .bit file, e.g. build/basys3/blink/blink.bit")
        if args.command == "program-data":
            p.error("program-data requires a binary file")
        p.error(f"{args.command} requires a design source, e.g. examples/blink.py")
    if args.source is None:
        args.source = str(DEFAULT_SOURCE)
    try:
        {
            "build": cmd_build,
            "load": cmd_load,
            "run": cmd_run,
            "sim": cmd_sim,
            "program": cmd_program,
            "program-data": cmd_program_data,
            "doctor": cmd_doctor,
            "shell": cmd_shell,
        }[args.command](args)
        return 0
    except (FPGAToolError, subprocess.CalledProcessError) as exc:
        print(f"fpgatool: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    # Helpers share this orchestrator's configuration and exception type.
    sys.modules["fpgatool"] = sys.modules[__name__]
    raise SystemExit(main())
