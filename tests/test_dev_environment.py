"""Development setup must survive fresh interpreters and toolchain changes."""
from pathlib import Path
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fpgatool


class DevelopmentEnvironmentTests(unittest.TestCase):
    def test_runtime_cache_refreshes_on_source_and_patch_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipelinec = root / 'PipelineC'
            source = pipelinec / 'src'
            source.mkdir(parents=True)
            modules = ('pypeline.py', 'PY_TO_LOGIC.py', 'OPEN_TOOLS.py',
                       'pypeline_sim.py', 'AUTO_PIPELINE.py')
            for name in modules:
                (source / name).write_text('value = 0\n')
            patches = root / 'toolchain' / 'patches'
            patches.mkdir(parents=True)
            names = ('pypeline-native-clock-wires.patch',
                     'pypeline-sim-factory-annotations.patch',
                     'pypeline-boolop-instance-names.patch',
                     'pipelinec-timing-snapshot-memory.patch')
            for name, module in zip(names, modules):
                (patches / name).write_text(
                    f'--- a/src/{module}\n+++ b/src/{module}\n'
                    '@@ -1 +1 @@\n-value = 0\n+value = 1\n')
            with patch.object(fpgatool, 'STATE_DIR', root / 'state'), \
                 patch.object(fpgatool, 'TOOLCHAIN_DIR', root / 'toolchain'):
                runtime = fpgatool.prepare_native_runtime(pipelinec)
                self.assertEqual((runtime / 'pypeline.py').read_text(), 'value = 1\n')
                with patch.object(fpgatool, 'run') as command:
                    self.assertEqual(fpgatool.prepare_native_runtime(pipelinec), runtime)
                    command.assert_not_called()
                (source / 'pypeline.py').write_text('value = 0\nnew_source = True\n')
                fpgatool.prepare_native_runtime(pipelinec)
                self.assertIn('new_source = True', (runtime / 'pypeline.py').read_text())
                patch_file = patches / names[0]
                patch_file.write_text(patch_file.read_text().replace('+value = 1', '+value = 2'))
                fpgatool.prepare_native_runtime(pipelinec)
                self.assertIn('value = 2', (runtime / 'pypeline.py').read_text())
                self.assertIn('new_source = True', (runtime / 'pypeline.py').read_text())
                self.assertIn('value = 0', (source / 'pypeline.py').read_text())
                patch_file.write_text('invalid patch\n')
                with self.assertRaises(subprocess.CalledProcessError):
                    fpgatool.prepare_native_runtime(pipelinec)
                self.assertIn('value = 2', (runtime / 'pypeline.py').read_text())

    def test_virtualenv_registration_works_from_another_directory(self):
        setup = runpy.run_path(str(fpgatool.ROOT / 'scripts' / 'setup-dev.py'))['setup']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'runtime'
            runtime.mkdir()
            (runtime / 'pypeline.py').write_text('registered_runtime = True\n')
            site_packages = root / 'site-packages'
            site_packages.mkdir()
            with patch.object(sys, 'prefix', str(root)), \
                 patch('sysconfig.get_path', return_value=str(site_packages)), \
                 patch.object(fpgatool, 'ensure_pipelinec', return_value=root / 'PipelineC'), \
                 patch.object(fpgatool, 'prepare_native_runtime', return_value=runtime), \
                 patch('site.addsitedir'), patch.dict(sys.modules, pypeline=type(sys)('pypeline')):
                sys.modules['pypeline'].__file__ = str(runtime / 'pypeline.py')
                setup()
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            # -S excludes this machine's existing .pth registration: load only
            # the one just written, as a fresh virtualenv would on startup.
            subprocess.run([sys.executable, '-S', '-c',
                            f'import site; site.addsitedir({str(site_packages)!r}); '
                            'import pypeline; assert pypeline.registered_runtime'],
                           cwd=root, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
