#!/usr/bin/env python3
"""Run unittest in the pinned simulation environment, without optional skips."""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fpgatool


def main():
    args = sys.argv[1:]
    if args[:1] == ['--in-container']:
        pipelinec = Path('/opt/PipelineC')
        runtime = fpgatool.prepare_native_runtime(pipelinec)
        paths = [runtime, pipelinec / 'src', pipelinec / 'include' / 'pypeline',
                 ROOT / 'examples', ROOT]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, paths)))
        # Match simulation/run.py: preserve typed arithmetic while avoiding
        # per-bit operator implementation tests in application regressions.
        env.setdefault('PYPELINE_SIM_SOFT_OPS', 'none')
        # Fail early when the environment is broken instead of passing with skips.
        subprocess.run([sys.executable, '-c',
                        'import pypeline, PY_TO_LOGIC, AUTO_PIPELINE, pyftdi, PIL'],
                       env=env, check=True)
        if not shutil.which('ghdl'):
            raise fpgatool.FPGAToolError('GHDL is missing from the simulation shell')
        command = args[1:] or ['discover', '-s', 'tests', '-v']
        # The native simulator also caches scalar types: bit extraction would
        # otherwise allocate a new Python class on every simulated cycle.
        bootstrap = '''from functools import lru_cache
import pypeline as p
p.make_uint_t = lru_cache(maxsize=None)(p.make_uint_t)
p.make_int_t = lru_cache(maxsize=None)(p.make_int_t)
import unittest
unittest.main(module=None)
'''
        return subprocess.call([sys.executable, '-c', bootstrap, *command],
                               cwd=ROOT, env=env)

    setup = runpy.run_path(str(ROOT / 'scripts' / 'setup-dev.py'))
    pipelinec = setup['setup']()
    fpgatool.ensure_podman()
    fpgatool.ensure_nix_volume()
    cmd = fpgatool.podman_base(pipelinec_dir=pipelinec)
    for name in ('PYPELINE_SIM_SOFT_OPS', 'FPGATOOL_CAPTURE_JTAG_VCD'):
        if name in os.environ:
            cmd[-1:-1] = ['--env', name + '=' + os.environ[name]]
    cmd += [
        'nix', '--extra-experimental-features', 'nix-command flakes',
        'develop', 'path:/workspace/toolchain#simulation', '--command',
        'python3', 'scripts/run-tests.py', '--in-container', *args,
    ]
    return subprocess.call(cmd)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (fpgatool.FPGAToolError, subprocess.CalledProcessError) as exc:
        sys.exit(f'tests: {exc}')
