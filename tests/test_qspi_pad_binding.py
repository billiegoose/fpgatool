"""Physical pad lowering supports shared inputs in reusable submodules."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
try:
    from fpgatool_board.basys3.qspi import _rewrite_pad
except ImportError:
    _rewrite_pad = None


@unittest.skipIf(_rewrite_pad is None, 'requires Pypeline')
class QspiPadBindingTests(unittest.TestCase):
    def test_rewrites_every_reader_at_any_hierarchy_depth(self):
        original = '''QspiDQ1_I : in unsigned(0 downto 0);
QspiDQ1_O : out unsigned(0 downto 0);
QspiDQ1_T : out unsigned(0 downto 0);
global_to_module.demo.QspiDQ1_I <= QspiDQ1_I;
global_to_module.demo.live_flash.QspiDQ1_I <= QspiDQ1_I;
global_to_module.demo.other.reader.QspiDQ1_I <= QspiDQ1_I;
QspiDQ1_O <= module_to_global.demo.live_flash.QspiDQ1_O;
QspiDQ1_T <= module_to_global.demo.live_flash.QspiDQ1_T;
'''
        result = _rewrite_pad(original, 'QspiDQ1')
        self.assertNotIn('QspiDQ1_I;', result)
        self.assertIn('QspiDQ1 : inout unsigned(0 downto 0);', result)
        for reader in ('demo', 'demo.live_flash', 'demo.other.reader'):
            self.assertIn(f'global_to_module.{reader}.QspiDQ1_I <= QspiDQ1;', result)
        self.assertIn("QspiDQ1 <= module_to_global.demo.live_flash.QspiDQ1_O "
                      "when module_to_global.demo.live_flash.QspiDQ1_T = "
                      "unsigned'(0 => '0') else (others => 'Z');", result)


if __name__ == '__main__':
    unittest.main()
