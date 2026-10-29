#!/usr/bin/env python3
"""Register the pinned, patched Pypeline runtime in the active virtualenv."""
from pathlib import Path
import site
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fpgatool


def setup():
    if sys.prefix == sys.base_prefix:
        raise fpgatool.FPGAToolError('run setup with .venv/bin/python')
    pipelinec = fpgatool.ensure_pipelinec()
    runtime = fpgatool.prepare_native_runtime(pipelinec)
    paths = (runtime, pipelinec / 'src', pipelinec / 'include' / 'pypeline',
             ROOT / 'examples', ROOT)
    destination = Path(sysconfig.get_path('purelib')) / 'fpgatool-dev.pth'
    # .pth paths also work for direct Python invocations and IDE interpreters.
    destination.write_text(''.join(f'{path}\n' for path in paths))
    site.addsitedir(str(destination.parent))
    import pypeline
    print(f'Pypeline ready: {pypeline.__file__}', flush=True)
    return pipelinec


if __name__ == '__main__':
    try:
        setup()
    except fpgatool.FPGAToolError as exc:
        sys.exit(f'setup-dev: {exc}')
