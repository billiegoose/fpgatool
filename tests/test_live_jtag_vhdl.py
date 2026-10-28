"""Simulate the actual primitive wrappers with a controllable BSCANE2 model."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
try:
    from fpgatool_board.basys3.jtag_flash import _SPI_VHDL, _CONTROL_VHDL
except ImportError:
    _SPI_VHDL = None

CONTEXT = 'library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all; use work.bscan_test.all;\n'
SUPPORT = '''library ieee; use ieee.std_logic_1164.all;
package bscan_test is
  signal cap, drck, sel, shift, tdi, upd, run, tdo : std_logic_vector(4 downto 0) := (others => '0');
end package;
library ieee; use ieee.std_logic_1164.all; use work.bscan_test.all;
entity BSCANE2 is
  generic (JTAG_CHAIN : integer := 1);
  port (CAPTURE, DRCK, RESET, RUNTEST, SEL, SHIFT, TCK, TDI, TMS, UPDATE : out std_logic;
        TDO : in std_logic);
end entity;
architecture model of BSCANE2 is begin
  CAPTURE <= work.bscan_test.cap(JTAG_CHAIN);
  DRCK <= work.bscan_test.drck(JTAG_CHAIN);
  RESET <= '0'; RUNTEST <= work.bscan_test.run(JTAG_CHAIN);
  SEL <= work.bscan_test.sel(JTAG_CHAIN); SHIFT <= work.bscan_test.shift(JTAG_CHAIN);
  TCK <= work.bscan_test.drck(JTAG_CHAIN); TDI <= work.bscan_test.tdi(JTAG_CHAIN);
  TMS <= '0'; UPDATE <= work.bscan_test.upd(JTAG_CHAIN);
  work.bscan_test.tdo(JTAG_CHAIN) <= TDO;
end architecture;
'''


@unittest.skipUnless(shutil.which('ghdl') and _SPI_VHDL, 'requires GHDL and Pypeline')
class JtagVhdlTests(unittest.TestCase):
    def run_hdl(self, declarations, body, bench):
        source = SUPPORT + CONTEXT + declarations + '\narchitecture rtl of uut is\n' + body
        source += '\nend architecture;\n' + CONTEXT + 'entity tb is end;\narchitecture test of tb is\n' + bench
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.vhd'
            path.write_text(source)
            for args in (['-a', '--std=08', str(path)], ['--elab-run', '--std=08', 'tb', '--assert-level=error', '--stop-time=10us']):
                result = subprocess.run(['ghdl', *args], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mailbox_status_command_cdc_and_invalid_transfers(self):
        self.run_hdl('entity uut is port(clk : in std_logic; status : in unsigned(31 downto 0); return_output : out unsigned(1 downto 0)); end;',
            _CONTROL_VHDL, '''signal clk : std_logic := '0';
  signal command : unsigned(1 downto 0);
  signal pulses : natural := 0;
  signal last_command : unsigned(1 downto 0) := "00";
begin
  clk <= not clk after 3 ns;
  dut : entity work.uut port map(clk, x"12340001", command);
  process(clk) begin
    if rising_edge(clk) and command /= 0 then pulses <= pulses + 1; last_command <= command; end if;
  end process;
  process
    variable received : std_logic_vector(63 downto 0);
    procedure pulse is begin
      drck(2) <= '0'; wait for 5 ns; drck(2) <= '1'; wait for 5 ns;
      drck(2) <= '0'; wait for 5 ns;
    end;
    procedure exchange(value : std_logic_vector(63 downto 0); n : natural := 64) is begin
      sel(2) <= '1'; cap(2) <= '1'; pulse; cap(2) <= '0'; shift(2) <= '1'; wait for 1 ns;
      for i in 0 to n-1 loop received(i) := tdo(2); tdi(2) <= value(i); pulse; end loop;
      shift(2) <= '0'; upd(2) <= '1'; wait for 15 ns; upd(2) <= '0'; wait for 100 ns;
    end;
  begin
    exchange(x"0000000000000000");
    assert received = x"1234000152464c32" report "status word/bit order" severity failure;
    assert pulses = 0 severity failure;
    exchange(x"52464c3200000002");
    assert pulses = 1 and last_command = 2 report "command CDC/pulse" severity failure;
    exchange(x"52464c3200000001", 10);
    assert pulses = 1 report "short command accepted" severity failure;
    exchange(x"0000000000000003");
    assert pulses = 1 report "bad magic accepted" severity failure;
    std.env.stop;
  end process;
end architecture;''')

    def test_spi_requires_grant_and_releases_cs_in_idle(self):
        fields = ['cclk','cs_n','dq0','dq0_t','dq1','dq1_t','dq2','dq2_t','dq3','dq3_t',
                  'ready','busy','done','error','quad_enabled','quad_activity','quad_write_activity']
        types = 'package pin_types is type pins_t is record\n'
        types += ''.join(f'{name} : unsigned(0 downto 0);\n' for name in fields)
        types += 'read_data : unsigned(7 downto 0); end record; end package;\n'
        declarations = types + CONTEXT + 'use work.pin_types.all;\nentity uut is port(miso, granted : in unsigned(0 downto 0); return_output : out pins_t); end;'
        self.run_hdl(declarations, _SPI_VHDL,
            '''signal granted, miso : unsigned(0 downto 0) := "0";
  signal pins : work.pin_types.pins_t;
begin
  dut : entity work.uut port map(miso, granted, pins);
  process begin
    sel(1) <= '1'; drck(1) <= '1'; wait for 5 ns;
    assert pins.cclk = 0 and pins.cs_n = 1 report "ungranted SPI drove flash" severity failure;
    drck(1) <= '0'; run(1) <= '1'; granted <= "1"; wait for 5 ns;
    run(1) <= '0'; drck(1) <= '1'; wait for 1 ns;
    cap(1) <= '1'; wait for 4 ns;
    assert pins.cs_n = 1 and pins.cclk = 1 report "capture clock reached flash before CS setup" severity failure;
    drck(1) <= '0'; wait for 5 ns;
    assert pins.cs_n = 0 and pins.cclk = 0 report "delayed CAPTURE missed before SHIFT" severity failure;
    cap(1) <= '0'; tdi(1) <= '1'; miso <= "0"; wait for 5 ns;
    drck(1) <= '1'; wait for 5 ns;
    assert pins.dq0 = 1 and tdo(1) = '0' report "SPI MOSI/MISO" severity failure;
    miso <= "1"; wait for 5 ns;
    assert tdo(1) = '1' severity failure;
    run(1) <= '1'; wait for 5 ns;
    assert pins.cs_n = 1 report "idle did not release CS" severity failure;
    granted <= "0"; drck(1) <= '1'; wait for 5 ns;
    assert pins.cs_n = 1 and pins.cclk = 0 severity failure;
    std.env.stop;
  end process;
end architecture;''')


if __name__ == '__main__':
    unittest.main()
