"""Cached HDL compilation and live VGA playback; no Python gate simulation."""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import threading
import time

from simulation.vga import Frame


def cache_key(root, source, versions):
    digest = hashlib.sha256()
    digest.update(str(source.relative_to(root)).encode())
    digest.update(versions.encode())
    # Conservative invalidation includes imported local helpers, board modules,
    # compiler patches, the pinned toolchain and the monitor/driver implementation.
    paths = [root / 'toolchain.lock.toml', root / 'fpgatool.py']
    for folder in ('examples', 'simulation', 'toolchain'):
        paths.extend(p for p in (root / folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(p for p in root.rglob('*.py')
                 if not any(part in ('build', '.fpgatool', '.git', '__pycache__')
                            for part in p.relative_to(root).parts))
    for path in sorted(set(paths + [source])):
        digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()[:24]


def driver_source(verilog):
    ports = re.search(r'module top\((.*?)\);', verilog, re.S)
    if not ports:
        raise ValueError('generated HDL has no top module')
    clocks = re.findall(r'\binput (clk_\d+p\d+)\s*;', verilog)
    if len(clocks) != 1:
        raise ValueError('compiled VGA simulation currently requires one input clock; use --sim-backend python for multiple clock domains')
    clock = clocks[0]
    mhz = float(clock.removeprefix('clk_').replace('p', '.'))
    if mhz <= 0:
        raise ValueError('simulation clock frequency must be positive')
    pins = ['VGA_' + c + str(b) for c in 'RGB' for b in range(4)] + ['VGA_HS', 'VGA_VS']
    for pin in pins:
        if not re.search(r'\boutput ' + pin + r'\s*;', verilog):
            raise ValueError(f'design must expose the Basys 3 {pin} output')
    packed = ' | '.join(f'(unsigned(dut.{pin}) << {bit})' for bit, pin in enumerate(pins))
    return f'''#include "Vtop.h"
#include "verilated.h"
#include <cstdint>
#include <cstdlib>
extern "C" void* vga_monitor_open(const char*);
extern "C" void vga_monitor_event(void*,double,uint8_t,uint8_t,uint8_t,int,int);
extern "C" void vga_monitor_close(void*);
int main(int argc,char** argv) {{
 Verilated::commandArgs(argc,argv);
 Vtop dut;
 void* monitor=vga_monitor_open("fpgatool VGA");
 const char* cap=std::getenv("FPGATOOL_SIM_CYCLES");
 uint64_t limit=cap ? std::strtoull(cap,nullptr,10) : UINT64_MAX;
 unsigned previous=~0u;
 for(uint64_t cycle=0;cycle<limit && !Verilated::gotFinish();++cycle) {{
  dut.{clock}=0; dut.eval();
  dut.{clock}=1; dut.eval();
  unsigned value={packed};
  if(value!=previous) {{
   vga_monitor_event(monitor,(cycle+0.5)*{1000 / mhz:.17g},
    (value&15)*17,((value>>4)&15)*17,((value>>8)&15)*17,
    (value>>12)&1,(value>>13)&1);
   previous=value;
  }}
 }}
 vga_monitor_close(monitor); dut.final();
}}
'''


def build(source, pipelinec):
    import fpgatool as tool
    verilator = tool.require_tool('verilator')
    tool.require_tool('make')
    tool.require_tool('c++')
    # bash also handles older Verilator Perl launchers without a shebang.
    with open(verilator, 'rb') as launcher:
        compiler = ['bash', verilator] if launcher.read(2) == b': ' else [verilator]
    versions = tool.output(compiler + ['--version']) + tool.output(['c++', '--version'])
    key = cache_key(tool.ROOT, source, versions)
    out = tool.CACHE_DIR / 'hdl-sim' / key
    binary = out / 'obj' / 'Vtop'
    if binary.is_file() and (out / 'ready').is_file():
        print('Using cached hardware simulation.', flush=True)
        return binary
    tool.ensure_podman()
    tool.ensure_nix_volume()
    out.mkdir(parents=True, exist_ok=True)
    container_out = '/workspace/' + out.relative_to(tool.ROOT).as_posix()
    log = out / 'build.log'
    print('Compiling the design’s VHDL for simulation (first run or changed design)...', flush=True)
    cmd = tool.podman_base(pipelinec_dir=pipelinec) + [
        'nix', '--extra-experimental-features', 'nix-command flakes',
        'develop', 'path:/workspace/toolchain#simulation', '--command',
        'bash', '/workspace/simulation/build-hdl.sh', '/opt/PipelineC',
        tool.container_design_path(source), container_out]
    try:
        tool.run(cmd, log_path=log)
        driver = out / 'driver.cpp'
        driver.write_text(driver_source((out / 'top.v').read_text()))
        print('Building the fast simulator...', flush=True)
        # Rebuild from scratch after failure, avoiding a stale generated makefile.
        shutil.rmtree(out / 'obj', ignore_errors=True)
        tool.run(compiler + ['--cc', '--exe', '--top-module', 'top', '--Mdir',
                 str(out / 'obj'), '-Wno-fatal', '-O3', '-CFLAGS', '-O3 -std=c++14',
                 str(out / 'top.v'), str(driver),
                 str(tool.ROOT / 'simulation/vendor/vga-monitor-sim/vga_monitor.cpp')],
                 log_path=out / 'verilator.log')
        tool.run(['make', '-C', str(out / 'obj'), '-f', 'Vtop.mk', '-j',
                  str(min(os.cpu_count() or 2, 4))], log_path=out / 'make.log')
    except (subprocess.CalledProcessError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else 'Hardware simulation compilation failed'
        raise tool.FPGAToolError(f'{detail}; see build.log, verilator.log and make.log in {out}. For native simulation use --sim-backend python') from exc
    (out / 'ready').write_text(key + '\n')
    return binary


def read_stream(connection, frames, cancelled=None):
    """Read exact PPM frames without blocking the viewer/process supervisor."""
    def publish(item):
        while cancelled is None or not cancelled.is_set():
            try:
                frames.put(item, timeout=.1)
                return
            except queue.Full:
                pass
    try:
        with connection.makefile('rb') as stream:
            while True:
                magic = stream.readline()
                if not magic:
                    raise EOFError('VGA stream closed')
                if magic != b'P6\n':
                    raise ValueError('invalid VGA stream header')
                dimensions = stream.readline()
                width, height = map(int, dimensions.split())
                if not (0 < width <= 4096 and 0 < height <= 2160):
                    raise ValueError('invalid VGA stream dimensions')
                if stream.readline() != b'255\n':
                    raise ValueError('invalid VGA stream color depth')
                rgb = stream.read(width * height * 3)
                if len(rgb) != width * height * 3:
                    raise EOFError('incomplete VGA frame')
                publish((Frame(width, height, rgb), magic + dimensions + b'255\n' + rgb))
    except (OSError, EOFError, ValueError) as exc:
        publish(exc)


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def launch(binary, args, out):
    import fpgatool as tool
    ffplay = None if args.no_open else tool.require_tool('ffplay')
    out.mkdir(parents=True, exist_ok=True)
    for path in [out / 'frame.png', out / 'capture.json', *out.glob('frame-[0-9][0-9][0-9][0-9].png')]:
        path.unlink(missing_ok=True)
    limit = args.frames or (1 if args.no_open else None)
    reserve = socket.socket()
    reserve.bind(('127.0.0.1', 0))
    port = reserve.getsockname()[1]
    reserve.close()
    env = dict(os.environ, VGA_MONITOR_STREAM=f'127.0.0.1:{port}', VGA_MONITOR_FORMAT='ppm')
    env.pop('VGA_MONITOR_FRAMES', None)
    if args.cycles:
        env['FPGATOOL_SIM_CYCLES'] = str(args.cycles)
    else:
        env.pop('FPGATOOL_SIM_CYCLES', None)
    simulator = viewer = connection = None
    last = None
    count = 0
    start = time.monotonic()
    frames = queue.Queue(maxsize=2)
    cancelled = threading.Event()
    print('Acquiring VGA sync...' if args.no_open else 'Opening VGA monitor. Close the window or press Ctrl+C to stop.', flush=True)
    try:
        with (out / 'receiver.log').open('w') as log, (out / 'viewer.log').open('w') as vlog:
            simulator = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 10
            while connection is None:
                try:
                    connection = socket.create_connection(('127.0.0.1', port), timeout=.2)
                    connection.settimeout(None)
                except OSError:
                    if simulator.poll() is not None or time.monotonic() > deadline:
                        raise tool.FPGAToolError(f'simulator stopped or failed to start before a VGA frame; check --cycles and {out / "receiver.log"}')
                    time.sleep(.02)
            threading.Thread(target=read_stream, args=(connection, frames, cancelled), daemon=True).start()
            if ffplay:
                viewer = subprocess.Popen([ffplay, '-autoexit', '-loglevel', 'warning',
                    '-probesize', '32', '-analyzeduration', '0', '-window_title', f'fpgatool VGA — {Path(args.source).stem}',
                    '-f', 'image2pipe', '-vcodec', 'ppm', '-framerate', '60', '-i', 'pipe:0'],
                    stdin=subprocess.PIPE, stdout=vlog, stderr=vlog)
            last_received = time.monotonic()
            while limit is None or count < limit:
                if viewer and viewer.poll() is not None:
                    if count == 0:
                        raise tool.FPGAToolError(f'VGA viewer exited before displaying a frame; see {out / "viewer.log"}')
                    break
                try:
                    item = frames.get(timeout=.1)
                except queue.Empty:
                    if simulator.poll() is not None:
                        raise tool.FPGAToolError(f'simulator stopped after {count} frames; check --cycles and {out / "receiver.log"}')
                    if time.monotonic() - last_received > 20:
                        raise tool.FPGAToolError(f'no VGA frame for 20 seconds; check timing and {out / "receiver.log"}. Unsupported modes/clock primitives can use --sim-backend python')
                    continue
                if isinstance(item, Exception):
                    raise tool.FPGAToolError(f'{item}; see {out / "receiver.log"}')
                last, ppm = item
                count += 1
                last_received = time.monotonic()
                if viewer:
                    try:
                        viewer.stdin.write(ppm)
                        viewer.stdin.flush()
                    except BrokenPipeError:
                        break
                if args.no_open:
                    last.save(out / f'frame-{count:04d}.png')
                if count == 1:
                    print(f'VGA locked: {last.width} × {last.height}', flush=True)
    finally:
        cancelled.set()
        stop(simulator)
        if viewer and viewer.poll() is None and limit is not None and count >= limit:
            try:
                viewer.stdin.close()
                viewer.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                pass
        stop(viewer)
        if viewer and viewer.stdin and not viewer.stdin.closed:
            try:
                viewer.stdin.close()
            except BrokenPipeError:
                pass
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if last:
            last.save(out / 'frame.png')
            if args.screenshot:
                last.save(Path(args.screenshot).expanduser().resolve())
            (out / 'capture.json').write_text(json.dumps(dict(
                backend='hdl', width=last.width, height=last.height, frames=count,
                elapsed_seconds=time.monotonic() - start), indent=2) + '\n')
            print(f'Captured {count} frame(s): {out / "frame.png"}', flush=True)


def simulate(args, source, pipelinec):
    import fpgatool as tool
    if args.vga_mode:
        raise tool.FPGAToolError('--vga-mode is a Python backend option; the HDL monitor detects timing from sync signals')
    if not args.no_open:
        tool.require_tool('ffplay')
    try:
        binary = build(source, pipelinec)
        launch(binary, args, tool.build_dir(args.board, source) / 'sim')
    except OSError as exc:
        raise tool.FPGAToolError(str(exc)) from exc
