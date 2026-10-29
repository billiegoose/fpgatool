"""Simulate the actual primitive wrappers with a controllable BSCANE2 model."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def _source_vhdl_templates():
    """Test actual VHDL strings without needing the Pypeline Python runtime."""
    source = Path(__file__).resolve().parents[1] / 'examples/fpgatool_board/basys3/jtag_flash.py'
    values = {}

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return evaluate(node.left) + evaluate(node.right)
        raise ValueError(f'Unsupported VHDL expression: {ast.dump(node)}')

    for statement in ast.parse(source.read_text()).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in ('_BSCAN', '_SPI_VHDL', '_CONTROL_VHDL'):
                values[target.id] = evaluate(statement.value)
    return values['_SPI_VHDL'], values['_CONTROL_VHDL']


_SPI_VHDL, _CONTROL_VHDL = _source_vhdl_templates()

CONTEXT = 'library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all; use work.bscan_test.all;\n'
SUPPORT = '''library ieee; use ieee.std_logic_1164.all;
package bscan_test is
  signal cap, drck, sel, shift, tdi, upd, run, rst, tdo : std_logic_vector(4 downto 0) := (others => '0');
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
  RESET <= work.bscan_test.rst(JTAG_CHAIN); RUNTEST <= work.bscan_test.run(JTAG_CHAIN);
  SEL <= work.bscan_test.sel(JTAG_CHAIN); SHIFT <= work.bscan_test.shift(JTAG_CHAIN);
  TCK <= work.bscan_test.drck(JTAG_CHAIN); TDI <= work.bscan_test.tdi(JTAG_CHAIN);
  TMS <= '0'; UPDATE <= work.bscan_test.upd(JTAG_CHAIN);
  -- TAP samples the BSCAN return bit on the falling JTAG clock.
  process(work.bscan_test.drck(JTAG_CHAIN)) begin
    if falling_edge(work.bscan_test.drck(JTAG_CHAIN)) then
      work.bscan_test.tdo(JTAG_CHAIN) <= TDO;
    end if;
  end process;
end architecture;
'''


@unittest.skipUnless(shutil.which('ghdl'), 'requires GHDL')
class JtagVhdlTests(unittest.TestCase):
    def run_hdl(self, declarations, body, bench):
        source = SUPPORT + CONTEXT + declarations + '\narchitecture rtl of uut is\n' + body
        source += '\nend architecture;\n' + CONTEXT + 'entity tb is end;\narchitecture test of tb is\n' + bench
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.vhd'
            waveform = Path(tmp)/'waves.vcd'
            path.write_text(source)
            commands = [['-a', '--std=08', str(path)],
                        ['--elab-run', '--std=08', 'tb', '--assert-level=error', '--stop-time=100us']]
            capture_waveform = os.environ.get('FPGATOOL_CAPTURE_JTAG_VCD') == '1'
            if capture_waveform:
                commands[1].append(f'--vcd={waveform}')
            for args in commands:
                result = subprocess.run(['ghdl', *args], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if capture_waveform:
                destination = (Path(__file__).resolve().parents[1] / 'build' / 'basys3'
                               / 'mini_filesystem_demo' / 'jtag_waveforms')
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(waveform, destination / f'{self._testMethodName}.vcd')

    def test_mailbox_status_command_cdc_and_invalid_transfers(self):
        self.run_hdl('entity uut is port(clk : in std_logic; status : in unsigned(31 downto 0); return_output : out unsigned(1 downto 0)); end;',
            _CONTROL_VHDL, '''signal clk : std_logic := '0';
  signal command : unsigned(1 downto 0);
  signal live_status : unsigned(31 downto 0) := x"12340001";
  signal pulses : natural := 0;
  signal last_command : unsigned(1 downto 0) := "00";
begin
  clk <= not clk after 3 ns;
  dut : entity work.uut port map(clk, live_status, command);
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
      assert received = x"0000000052464c32" report "initial status should be the zero snapshot" severity failure;
      exchange(x"0000000000000000");
    assert received = x"1234000152464c32" report "acknowledged coherent status/bit order" severity failure;
    assert pulses = 0 severity failure;
      -- Capture a transition that changes many bits, including the generation.
      live_status <= x"FFFF0005"; wait for 17 ns;
      for n in 0 to 3 loop
        exchange(x"0000000000000000");
        assert received(63 downto 32) = x"12340001" or received(63 downto 32) = x"FFFF0005"
          report "torn status during multi-bit transition" severity failure;
      end loop;
      assert received(63 downto 32) = x"FFFF0005" report "status snapshot never refreshed" severity failure;
      -- The FFFF -> 0000 wrap changes all generation bits. JTAG can stop
      -- during this transition and the TAP may reset without a design reset.
      live_status <= x"00000005"; rst(2) <= '1'; wait for 400 ns; rst(2) <= '0';
      for n in 0 to 3 loop
        exchange(x"0000000000000000");
        assert received(63 downto 32) = x"FFFF0005" or received(63 downto 32) = x"00000005"
          report "torn status during generation wrap or TAP reset" severity failure;
      end loop;
      assert received(63 downto 32) = x"00000005" report "snapshot handshake stuck after reset" severity failure;
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
        declarations = types + CONTEXT + 'use work.pin_types.all;\nentity uut is port(clk : in std_logic; miso, granted : in unsigned(0 downto 0); return_output : out pins_t); end;'
        self.run_hdl(declarations, _SPI_VHDL,
            '''signal clk : std_logic := '0';
  signal granted, miso : unsigned(0 downto 0) := "0";
  signal pins : work.pin_types.pins_t;
begin
  clk <= not clk after 5 ns;
  dut : entity work.uut port map(clk, miso, granted, pins);
  process begin
    sel(1) <= '1'; drck(1) <= '1'; wait for 100 ns;
    assert pins.cclk = 0 and pins.cs_n = 1 report "ungranted SPI drove flash" severity failure;
    drck(1) <= '0'; run(1) <= '1'; granted <= "1"; wait for 100 ns;
    run(1) <= '0'; cap(1) <= '1'; drck(1) <= '1'; wait for 100 ns;
    assert pins.cs_n = 0 and pins.cclk = 0 report "capture did not establish CS before clock" severity failure;
    drck(1) <= '0'; wait for 100 ns;
    assert pins.cs_n = 0 and pins.cclk = 0 report "CS not established before shift" severity failure;
    cap(1) <= '0'; shift(1) <= '1'; tdi(1) <= '1'; miso <= "0";
    wait for 100 ns;
    assert pins.cclk = 0 report "SCK rose before DRCK-captured MOSI" severity failure;
    drck(1) <= '1'; wait for 100 ns;
    assert pins.cclk = 1 and pins.dq0 = 1 and tdo(1) = '0'
      report "registered first SPI bit or MISO failed" severity failure;
    drck(1) <= '0'; wait for 100 ns;
    assert pins.cclk = 0 report "registered SCK did not fall" severity failure;
    tdi(1) <= '0'; miso <= "1"; wait for 100 ns;
    assert tdo(1) = '0' report "registered TDO changed before falling JTAG edge" severity failure;
    drck(1) <= '1'; wait for 100 ns;
    assert pins.cclk = 1 and pins.dq0 = 0 report "second SPI bit failed" severity failure;
    drck(1) <= '0'; wait for 100 ns;
    assert tdo(1) = '1' report "TDO failed to capture MISO at falling JTAG edge" severity failure;
      shift(1) <= '0'; run(1) <= '1'; wait for 100 ns;
    assert pins.cs_n = 1 and pins.cclk = 0 report "idle did not release SPI" severity failure;
    granted <= "0"; drck(1) <= '1'; wait for 100 ns;
    assert pins.cs_n = 1 and pins.cclk = 0 report "ungranted SPI became active" severity failure;
    std.env.stop;
  end process;
end architecture;''')


    def test_spi_full_bytes_clock_edges_setup_hold_and_back_to_back(self):
        """Observe actual SPI pins, not merely the JTAG shift-register data."""
        fields = ['cclk', 'cs_n', 'dq0', 'dq0_t', 'dq1', 'dq1_t', 'dq2', 'dq2_t', 'dq3', 'dq3_t',
                  'ready', 'busy', 'done', 'error', 'quad_enabled', 'quad_activity', 'quad_write_activity']
        types = 'package pin_types is type pins_t is record\n'
        types += ''.join(f'{name} : unsigned(0 downto 0);\n' for name in fields)
        types += 'read_data : unsigned(7 downto 0); end record; end package;\n'
        declarations = types + CONTEXT + 'use work.pin_types.all;\nentity uut is port(clk : in std_logic; miso, granted : in unsigned(0 downto 0); return_output : out pins_t); end;'
        self.run_hdl(declarations, _SPI_VHDL, '''signal clk : std_logic := '0';
  signal granted, miso : unsigned(0 downto 0) := "0";
  signal pins : work.pin_types.pins_t;
  signal observed : std_logic_vector(39 downto 0) := (others => '0');
  signal rising_edges : natural := 0;
  signal falling_edges : natural := 0;
  signal last_mosi_change : time := 0 ns;
  signal last_cs_assert : time := 0 ns;
  signal last_sck_rise : time := 0 ns;
  signal last_sck_fall : time := 0 ns;
begin
  clk <= not clk after 5 ns;
  dut : entity work.uut port map(clk, miso, granted, pins);
  process(pins.dq0(0)) begin
    if pins.dq0(0)'event then
      if rising_edges > 0 then
        assert pins.cclk(0) = '0' report "MOSI changed while SCK was high" severity failure;
        assert now - last_sck_rise >= 20 ns
          report "MOSI hold time after rising SCK too short" severity failure;
      end if;
      last_mosi_change <= now;
    end if;
  end process;
  process(pins.cs_n(0)) begin
    if falling_edge(pins.cs_n(0)) then last_cs_assert <= now; end if;
  end process;
  process
  begin
    wait until rising_edge(pins.cclk(0));
    assert pins.cs_n(0) = '0' report "SCK rose with CS inactive" severity failure;
    assert rising_edges < 40 report "extra SPI rising edge" severity failure;
    assert now - last_cs_assert >= 20 ns report "insufficient CS-to-SCK setup" severity failure;
    assert now - last_mosi_change >= 20 ns report "insufficient MOSI-to-SCK setup" severity failure;
    assert now - last_sck_fall >= 40 ns report "SPI low pulse too short" severity failure;
    observed(39 - rising_edges) <= pins.dq0(0);
    rising_edges <= rising_edges + 1;
    last_sck_rise <= now;
  end process;
  process
  begin
    wait until falling_edge(pins.cclk(0));
    if rising_edges > 0 then
      assert now - last_sck_rise >= 40 ns report "SPI high pulse too short" severity failure;
      falling_edges <= falling_edges + 1;
      last_sck_fall <= now;
    end if;
  end process;
  process
    procedure start_transfer is begin
      run(1) <= '1'; drck(1) <= '0'; wait for 120 ns;
      run(1) <= '0'; sel(1) <= '1'; cap(1) <= '1';
      drck(1) <= '1'; wait for 120 ns;
      drck(1) <= '0'; wait for 120 ns;
      assert pins.cs_n(0) = '0' and pins.cclk(0) = '0'
        report "CAPTURE_DR must establish CS without clocking flash" severity failure;
      cap(1) <= '0'; shift(1) <= '1'; wait for 120 ns;
      assert pins.cclk(0) = '0' report "SHIFT_DR entry emitted an extra SCK" severity failure;
    end;
    procedure send_byte(value : std_logic_vector(7 downto 0)) is begin
      for i in 7 downto 0 loop
        tdi(1) <= value(i); wait for 60 ns;
        drck(1) <= '1'; wait for 120 ns;
        assert pins.cclk(0) = '1' report "missing SCK high phase" severity failure;
        drck(1) <= '0'; wait for 120 ns;
        assert pins.cclk(0) = '0' report "missing SCK low phase" severity failure;
      end loop;
    end;
    procedure finish_transfer is begin
      shift(1) <= '0'; run(1) <= '1'; wait for 120 ns;
      assert pins.cclk(0) = '0' and pins.cs_n(0) = '1'
        report "RUNTEST must release flash with SCK low" severity failure;
    end;
  begin
    sel(1) <= '1'; granted <= "1"; wait for 120 ns;
    start_transfer;
    assert rising_edges = 0 report "CAPTURE_DR clocked flash" severity failure;
    send_byte(x"06");
    finish_transfer;
    assert rising_edges = 8 and falling_edges = 8
      report "single-byte transaction must have exactly eight full SCK pulses" severity failure;
    start_transfer;
    send_byte(x"9F"); send_byte(x"80");
    finish_transfer;
    assert rising_edges = 24 and falling_edges = 24
      report "expected exactly twenty-four complete SCK pulses" severity failure;
    start_transfer;
    send_byte(x"03"); send_byte(x"1F");
    finish_transfer;
    assert rising_edges = 40 and falling_edges = 40
      report "expected exactly thirty-two complete SCK pulses" severity failure;
    assert observed = x"069F80031F"
      report "MOSI first/last-bit or byte-boundary alignment incorrect" severity failure;
    granted <= "0"; wait for 120 ns;
    assert pins.cs_n(0) = '1' and pins.cclk(0) = '0'
      report "grant removal failed to disable flash" severity failure;
    std.env.stop;
  end process;
end architecture;''')


    def test_spi_mode_zero_flash_miso_and_host_one_bit_alignment(self):
        """Flash changes SO after falling SCK; BSCAN TDO registers on falling TCK."""
        fields = ['cclk', 'cs_n', 'dq0', 'dq0_t', 'dq1', 'dq1_t', 'dq2', 'dq2_t', 'dq3', 'dq3_t',
                  'ready', 'busy', 'done', 'error', 'quad_enabled', 'quad_activity', 'quad_write_activity']
        types = 'package pin_types is type pins_t is record\n'
        types += ''.join(f'{name} : unsigned(0 downto 0);\n' for name in fields)
        types += 'read_data : unsigned(7 downto 0); end record; end package;\n'
        declarations = types + CONTEXT + 'use work.pin_types.all;\nentity uut is port(clk : in std_logic; miso, granted : in unsigned(0 downto 0); return_output : out pins_t); end;'
        self.run_hdl(declarations, _SPI_VHDL, '''signal clk : std_logic := '0';
  signal granted, miso : unsigned(0 downto 0) := "0";
  signal pins : work.pin_types.pins_t;
  -- Eight dummy SO command bits, then two response bytes, then lookahead.
  signal response : std_logic_vector(24 downto 0) := x"00A65C" & '0';
  signal sck_falls : natural := 0;
begin
  clk <= not clk after 5 ns;
  dut : entity work.uut port map(clk, miso, granted, pins);
  -- Flash mode 0: SO updates up to 8 ns after SCK falls, not on SCK rising.
  process
  begin
    wait until falling_edge(pins.cclk(0));
    if sck_falls < 24 then
      miso(0) <= response(23 - sck_falls) after 8 ns;
    end if;
    sck_falls <= sck_falls + 1;
  end process;
  process
    variable sampled : std_logic_vector(24 downto 0);
    variable reconstructed : std_logic_vector(15 downto 0);
    variable command : std_logic_vector(7 downto 0) := x"03";
  begin
    granted <= "1"; sel(1) <= '1'; run(1) <= '1'; wait for 120 ns;
    run(1) <= '0'; cap(1) <= '1'; drck(1) <= '1'; wait for 120 ns;
    drck(1) <= '0'; wait for 120 ns;
    cap(1) <= '0'; shift(1) <= '1'; wait for 120 ns;
    for i in 0 to 24 loop
      if i < 8 then tdi(1) <= command(7 - i); else tdi(1) <= '0'; end if;
      wait for 60 ns;
      sampled(24 - i) := tdo(1);
      drck(1) <= '1'; wait for 120 ns;
      drck(1) <= '0'; wait for 120 ns;
    end loop;
    shift(1) <= '0'; run(1) <= '1'; wait for 120 ns;
    assert sck_falls = 25 report "flash model saw missing or extra SCK edges" severity failure;
    -- Host samples before shifting each bit. Its returned bit i+1 is
    -- flash bit i, so two received bytes require a following lookahead bit.
    for i in 0 to 15 loop
      reconstructed(15 - i) := sampled(24 - (9 + i));
    end loop;
    assert reconstructed = x"A65C"
      report "host one-bit MISO compensation disagrees with registered BSCAN TDO" severity failure;
    std.env.stop;
  end process;
end architecture;''')


if __name__ == '__main__':
    unittest.main()
