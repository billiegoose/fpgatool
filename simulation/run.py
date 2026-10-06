#!/usr/bin/env python3
"""Native Pypeline simulator with clock scheduling and a Basys 3 VGA sink."""
import argparse
import ast
import importlib.machinery
from fractions import Fraction
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from socketserver import TCPServer
import threading
import time
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulation.vga import Frame, VgaMonitor

HTML = b'''<!doctype html><meta charset="utf-8"><title>fpgatool VGA monitor</title>
<style>body{background:#141820;color:#e4eaf3;font:16px system-ui;margin:32px}
img{max-width:100%;image-rendering:pixelated;background:#000;box-shadow:0 0 0 1px #374151}
p{color:#aeb9ca}</style><h1>VGA monitor</h1><p id="status">Waiting for VGA sync...</p><img id="screen">
<script>let version=-1;async function refresh(){try{let s=await(await fetch('/status')).json();
document.getElementById('status').textContent=s.message;
if(s.frame!==version&&s.frame>0){version=s.frame;document.getElementById('screen').src='/frame.png?v='+version;}}
catch(e){}setTimeout(refresh,500)}refresh();</script>'''


class Viewer:
    def __init__(self, enabled):
        self.message = 'Waiting for VGA sync...'
        self.frame = 0
        self.revision = 0
        self.png = None
        self.server = None
        if enabled:
            viewer = self
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/':
                        content, mime = HTML, 'text/html; charset=utf-8'
                    elif self.path == '/status':
                        content = json.dumps(dict(message=viewer.message, frame=viewer.revision)).encode()
                        mime = 'application/json'
                    elif self.path.startswith('/frame.png') and viewer.png is not None:
                        content, mime = viewer.png, 'image/png'
                    else:
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(content)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(content)
                def log_message(self, *args):
                    pass
            class LocalServer(ThreadingHTTPServer):
                def server_bind(self):
                    # This local viewer needs no reverse DNS lookup. macOS
                    # can block getfqdn() for minutes on some networks.
                    TCPServer.server_bind(self)
                    self.server_name, self.server_port = self.server_address
            self.server = LocalServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            url = f'http://127.0.0.1:{self.server.server_port}/'
            print(f'VGA monitor: {url}', flush=True)
            webbrowser.open(url)

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def simulate(args, viewer):
    # Use the pinned runtime and fpgatool's disposable compatibility copy.
    local_path = str(Path(__file__).resolve().parent)
    if local_path in sys.path:
        sys.path.remove(local_path)
    sys.path[:0] = [args.compat, str(Path(args.pipelinec) / 'src'),
                    str(Path(args.pipelinec) / 'include' / 'pypeline'),
                    str(Path(__file__).resolve().parents[1] / 'examples')]
    if sys.version_info >= (3, 14):
        # Pinned Pypeline discovers module wire annotations while decorating
        # MAINs. Restore eager module annotations on Python 3.14, which normally
        # defers them until after the module has finished executing.
        original_compile = importlib.machinery.SourceFileLoader.source_to_code
        def eager_annotations(loader, data, path, *, _optimize=-1):
            tree = ast.parse(data, filename=path)
            annotations = [node for node in tree.body if isinstance(node, ast.AnnAssign)
                           and isinstance(node.target, ast.Name)]
            future_strings = any(isinstance(node, ast.ImportFrom) and node.module == '__future__'
                                 and any(n.name == 'annotations' for n in node.names) for node in tree.body)
            if not annotations or future_strings:
                return original_compile(loader, data, path, _optimize=_optimize)
            body = []
            initialized = False
            for node in tree.body:
                if node in annotations and not initialized:
                    body.append(ast.copy_location(ast.parse('__annotations__ = {}').body[0], node))
                    initialized = True
                body.append(node)
                if node in annotations:
                    assignment = ast.Assign(targets=[ast.Subscript(value=ast.Name(id='__annotations__', ctx=ast.Load()),
                        slice=ast.Constant(node.target.id), ctx=ast.Store())], value=node.annotation)
                    body.append(ast.copy_location(assignment, node))
            tree.body = body
            return compile(ast.fix_missing_locations(tree), path, 'exec', dont_inherit=True, optimize=_optimize)
        importlib.machinery.SourceFileLoader.source_to_code = eager_annotations
        # Cached bytecode predates the compatibility transformation.
        importlib.machinery.SourceFileLoader.get_code = lambda loader, fullname: loader.source_to_code(loader.get_data(loader.path), loader.path)
    import pypeline as p
    import pypeline_sim as sim
    import vga.timing as timing
    # Bit extraction otherwise allocates a new Python class for each bit of
    # every RGB pin on every pass. Scalar types depend only on their width.
    p.make_uint_t = lru_cache(maxsize=None)(p.make_uint_t)
    p.make_int_t = lru_cache(maxsize=None)(p.make_int_t)
    p.SIM_STRICT_ARITH = True
    p.SIM_RAW_INTS = False
    # Built-in typed operators have the same arithmetic results, without
    # simulating the soft arithmetic implementation's internal gates.
    p.set_sim_soft_ops('none')
    producer = None
    original_write = p._sim_wire_write
    def write(name, value, claim_key=None):
        nonlocal producer
        if name.endswith('.VGA_HS'):
            producer = p._sim_current_main
        return original_write(name, value, claim_key)
    # Rewritten hardware bodies capture this function at decoration time.
    p._sim_wire_write = write
    specs = []
    original_factory = timing.make_vga_timing
    def factory(spec, *a, **kw):
        specs.append(spec)
        return original_factory(spec, *a, **kw)
    timing.make_vga_timing = factory
    try:
        module = sim._import_design(args.source)
    finally:
        timing.make_vga_timing = original_factory
    if args.vga_mode:
        spec = getattr(timing, 'VGA_' + args.vga_mode.replace('x', '_'))
    elif len(specs) == 1:
        spec = specs[0]
    else:
        raise ValueError('could not discover one VGA timing; specify --vga-mode')
    monitor = VgaMonitor(spec)
    wire_info = sim._discover_wire_names(module)
    pin_names = ['VGA_' + color + str(bit) for color in 'RGB' for bit in range(4)] + ['VGA_HS', 'VGA_VS']
    keys = []
    for pin in pin_names:
        matches = [name for name, _ in wire_info if name.endswith('.' + pin)]
        if len(matches) != 1:
            raise ValueError(f'design must declare one Basys 3 {pin} output')
        keys.append(matches[0])
    mains = list(p._main_registry)
    if not mains:
        raise ValueError('no @MAIN functions found')
    rates = [Fraction(str(p._main_mhz_registry.get(fn.__name__, spec.pixel_clk_mhz))) for fn in mains]
    if any(rate <= 0 for rate in rates):
        raise ValueError('MAIN clock frequencies must be positive')
    # Find the actual MAIN that writes the sync output, including nested calls.
    p.sim_reset()
    for name, ctype in wire_info:
        p._sim_wire_state[name] = p.sim_zero(ctype)
    p._sim_active = True
    pending = None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for path in [out / 'frame.png', out / 'capture.json', *out.glob('frame-[0-9][0-9][0-9][0-9].png')]:
        path.unlink(missing_ok=True)
    start = last_progress = time.monotonic()
    next_edges = [Fraction(0) for _ in mains]
    producer_edges = 0
    divider = None
    cycles = 0
    limit = args.cycles
    try:
        p.RUN_INITIAL_HOOKS('sim')
        while monitor.frames < args.frames:
            edge = min(next_edges)
            selected = [fn for i, fn in enumerate(mains) if next_edges[i] == edge]
            for i in range(len(mains)):
                if next_edges[i] == edge:
                    next_edges[i] += 1 / rates[i]
            try:
                # A process whose clock has no edge must not be requeued by
                # cross-domain wire changes during delta-cycle convergence.
                p._sim_wire_readers.clear()
                sim._run_clock_cycle(selected, cycles)
            except p.SimFinish:
                break
            cycles += 1
            if producer is not None and divider is None:
                ratio = rates[mains.index(producer)] / Fraction(str(spec.pixel_clk_mhz))
                if ratio.denominator != 1 or ratio < 1:
                    raise ValueError('VGA writer clock must be an integer multiple of the pixel clock')
                divider = int(ratio)
                if limit is None:
                    # Allow acquisition plus requested frames and startup slack.
                    events_per_pixel = sum(rates) / Fraction(str(spec.pixel_clk_mhz))
                    limit = int((args.frames + 2) * spec.h_max * spec.v_max * events_per_pixel) + 10000
                print(f'Simulating {spec.frame_width}x{spec.frame_height}, {spec.pixel_clk_mhz:g} MHz pixels; acquiring sync...', flush=True)
            if producer in selected:
                if producer_edges % divider == 0:
                    values = [int(p._sim_wire_state[key]) for key in keys]
                    rgb = [sum(values[c * 4 + b] << b for b in range(4)) for c in range(3)]
                    frame = monitor.sample(*rgb, *values[-2:])
                    if frame:
                        path = out / f'frame-{monitor.frames:04d}.png'
                        frame.save(path)
                        frame.save(out / 'frame.png')
                        if args.screenshot:
                            frame.save(args.screenshot)
                        viewer.png = frame.png()
                        viewer.frame = monitor.frames
                        viewer.revision += 1
                        print(f'Captured frame {monitor.frames}: {path}', flush=True)
                producer_edges += 1
            now = time.monotonic()
            if now - last_progress >= 5:
                if monitor.collecting and viewer.server:
                    viewer.png = Frame(spec.frame_width, spec.frame_height, bytes(monitor.buffer)).png()
                    viewer.revision += 1
                viewer.message = f'{spec.frame_width} × {spec.frame_height} · {monitor.frames}/{args.frames} frames · {cycles:,} clock events · {now - start:.0f}s'
                print(viewer.message, flush=True)
                last_progress = now
            if cycles >= (limit or 10000) and monitor.frames < args.frames:
                raise ValueError(f'no complete VGA frame within {cycles} clock events ({monitor.frames}/{args.frames} captured); check timing or increase --cycles')
        if monitor.frames < args.frames:
            raise ValueError(f'design stopped after {monitor.frames}/{args.frames} complete VGA frames')
        viewer.message = f'{spec.frame_width} × {spec.frame_height} · {monitor.frames} frame(s) captured in {time.monotonic() - start:.1f}s · Ctrl+C to close'
        (out / 'capture.json').write_text(json.dumps(dict(width=spec.frame_width, height=spec.frame_height,
            frames=monitor.frames, clock_events=cycles, pixel_samples=monitor.samples), indent=2) + '\n')
        print(viewer.message, flush=True)
    except BaseException as exc:
        pending = exc
        raise
    finally:
        p._sim_wire_write = original_write
        p._sim_converging = False
        p._sim_reg_write_buffer = None
        p.RUN_FINAL_HOOKS('sim', pending_exc=pending)
        p._sim_active = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--pipelinec', required=True)
    parser.add_argument('--compat', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--frames', type=int, default=1)
    parser.add_argument('--cycles', type=int)
    parser.add_argument('--vga-mode')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    viewer = Viewer(not args.no_open)
    try:
        simulate(args, viewer)
        if not args.no_open:
            threading.Event().wait()
        return 0
    except KeyboardInterrupt:
        print('VGA monitor closed.', flush=True)
        return 0 if viewer.frame >= args.frames else 130
    except Exception as exc:
        print(f'VGA simulation failed: {exc}', file=sys.stderr)
        return 1
    finally:
        viewer.close()


if __name__ == '__main__':
    raise SystemExit(main())
