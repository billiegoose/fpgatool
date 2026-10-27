#!/usr/bin/env python3
"""Reproduce the isolated font-v2 timing database in the toolchain Nix shell.

This corrects BRAM clock pins and RAM32M DI2 checks. The DSP arcs describe only
the old unregistered multiplier configuration, not general DSP timing. Font v2
uses no DSP. The normal toolchain database is left untouched.
"""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def audit_bram(source, parse_sdf, sdf, pins):
    class Cell:
        def __init__(self, name):
            self.name, self.arcs = name, []

        def add_setup_hold(self, clock, port, *args):
            self.arcs.append((clock, port))

        def add_clock_out(self, clock, port, *args):
            self.arcs.append((clock, port))

    class Timing:
        def __init__(self):
            self.cells = []

        def add_cell_variant(self, grade, name):
            cell = Cell(name)
            self.cells.append(cell)
            return cell

    tree = ast.parse(source)
    function = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'import_bram_timings')
    env = dict(parse_sdf=parse_sdf, ClockEdge=type('Edge', (), {'RISING': 0}),
               TimingValue=lambda *args: args)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<timing-audit>', 'exec'), env)
    timing = Timing()
    env['import_bram_timings'](timing, sdf)
    cells = [c for c in timing.cells if c.name.startswith('RAMB36E1_')]
    invalid = sorted({(clock, port) for c in cells for clock, port in c.arcs
                      if clock not in pins or port not in pins})
    return dict(variants=len(cells), arcs=sum(len(c.arcs) for c in cells),
                invalid_arcs=len(invalid), invalid_pins=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/font-v2-timingdb')
    args = parser.parse_args()
    probe = args.output.resolve()
    xray = Path(os.environ['PRJXRAY_DB_DIR'])
    share = xray.parents[1]
    xilinx = share / 'himbaechel/uarch/xilinx'
    gen = probe / 'himbaechel/uarch/xilinx/gen'
    def make_writable():
        for entry in (probe, *probe.rglob('*')):
            if entry.is_dir():
                entry.chmod(entry.stat().st_mode | 0o700)
    if probe.exists():
        make_writable()
    # Copy afresh so repeated runs never apply the patch to an already patched file.
    shutil.copytree(xilinx / 'gen', gen, dirs_exist_ok=True, copy_function=shutil.copyfile)
    shutil.copytree(share / 'himbaechel/himbaechel_dbgen',
                    probe / 'himbaechel/himbaechel_dbgen',
                    dirs_exist_ok=True, copy_function=shutil.copyfile)
    # copytree preserves the Nix store's read-only directory permissions.
    make_writable()
    original = (gen / 'xilinx_gen.py').read_text()
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                    str(ROOT / 'toolchain/patches/openxc7-font-v2-timing-probe.patch')],
                   cwd=gen, check=True)
    spec = importlib.util.spec_from_file_location('parse_sdf', gen / 'parse_sdf.py')
    parse_sdf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parse_sdf)
    sdf = parse_sdf.parse_sdf_file(str(xray / 'artix7/timings/BRAM_L.sdf'))
    pins = set(json.loads((xilinx / 'meta/artix7/site_type_RAMBFIFO36E1.json').read_text())
               ['RAMB36E1']['bels']['RAMB36E1']['pins'])
    results = {'original': audit_bram(original, parse_sdf, sdf, pins),
               'corrected': audit_bram((gen / 'xilinx_gen.py').read_text(), parse_sdf, sdf, pins)}
    (probe / 'timing-audit.json').write_text(json.dumps(results, indent=2) + '\n')
    if results['corrected']['invalid_arcs'] or not results['corrected']['arcs']:
        raise RuntimeError('Corrected RAMB36 timing audit failed')
    print(json.dumps(results, indent=2), flush=True)
    bba = probe / 'xc7a50t.bba'
    subprocess.run([sys.executable, str(gen / 'xilinx_gen.py'), '--xray', str(xray / 'artix7'),
                    '--metadata', str(xilinx / 'meta/artix7'), '--device', 'xc7a50t',
                    '--constids', str(xilinx / 'constids.inc'), '--bba', str(bba)], check=True)
    subprocess.run([str(share.parents[1] / 'bin/bbasm'), '-l', str(bba),
                    str(probe / 'chipdb-xc7a50t.bin')], check=True)
    alias = probe / 'xc7a35tcpg236.bin'
    if alias.is_symlink():
        alias.unlink()
    alias.symlink_to('chipdb-xc7a50t.bin')
    bba.unlink()
    print(f'Font-v2 diagnostic timing database: {probe}', flush=True)


if __name__ == '__main__':
    main()
