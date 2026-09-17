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
        "develop", "/workspace/toolchain",
        "--command", "bash", "/workspace/toolchain/build-pipelinec.sh",
        "/opt/PipelineC",
        container_design_path(source),
        container_build_dir(args.board, source),
        pc_constraints,
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


def cmd_run(args: argparse.Namespace) -> None:
    source = normalize_source(args.source)
    if source.suffix.lower() == ".bit":
        raise FPGAToolError("run expects a design source; use load for an existing .bit file")
    bitstream = cmd_build(args)
    load_bitstream(args.board, bitstream)


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
        "develop", "/workspace/toolchain",
        "--command", "bash",
    ]
    run(cmd)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fpgatool.sh",
        description="Build FPGA designs, load them into volatile SRAM, or program persistent flash.",
    )
    p.add_argument("command", nargs="?", choices=("build", "load", "run", "program", "doctor", "shell"))
    p.add_argument("source", nargs="?", help="design source for build/run, or an existing .bit file for load/program")
    p.add_argument("--board", default=DEFAULT_BOARD, help=f"board profile (default: {DEFAULT_BOARD})")
    p.add_argument("--comb", action="store_true", help="disable PipelineC auto-pipelining and build the design as written")
    p.add_argument("-v", "--verbose", action="store_true", help="stream full toolchain output")
    return p


def main() -> int:
    global VERBOSE
    p = parser()
    args = p.parse_args()
    VERBOSE = args.verbose
    if args.command is None:
        p.print_help()
        return 0
    if args.command in {"build", "load", "run", "program"} and args.source is None:
        if args.command in {"load", "program"}:
            p.error(f"{args.command} requires a .bit file, e.g. build/basys3/blink/blink.bit")
        p.error(f"{args.command} requires a design source, e.g. examples/blink.py")
    if args.source is None:
        args.source = str(DEFAULT_SOURCE)
    try:
        {
            "build": cmd_build,
            "load": cmd_load,
            "run": cmd_run,
            "program": cmd_program,
            "doctor": cmd_doctor,
            "shell": cmd_shell,
        }[args.command](args)
        return 0
    except (FPGAToolError, subprocess.CalledProcessError) as exc:
        print(f"fpgatool: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
