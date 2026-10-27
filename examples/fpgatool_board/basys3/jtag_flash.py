# pyright: reportInvalidTypeForm=none
"""Resident openFPGALoader v1 SPI bridge (USER1) and upload mailbox (USER2).

STARTUPE2 and the pad IOBUFs belong to qspi.py. This module supplies only
logical SPI pins; switch ownership while both masters have SCK low / CS high.
USER2 explicitly grants flash ownership across all programmer transactions,
including their idle gaps. JTAG TAP resets do not reset the application.
"""
from pypeline import *
from hardware.QSPI import qspi_flash_byte_io_t

_BSCAN = """
component BSCANE2 is
  generic (JTAG_CHAIN : integer := 1);
  port (CAPTURE, DRCK, RESET, RUNTEST, SEL, SHIFT, TCK, TDI, TMS, UPDATE : out std_logic;
        TDO : in std_logic);
end component;
"""


_SPI_VHDL = _BSCAN + """
signal capture, drck, runtest, sel, tdi, cs : std_logic := '0';
signal tdo : std_logic;
begin
bscan_spi : BSCANE2 generic map (JTAG_CHAIN => 1)
  port map (CAPTURE => capture, DRCK => drck, RESET => open, RUNTEST => runtest,
            SEL => sel, SHIFT => open, TCK => open, TDI => tdi, TMS => open,
            UPDATE => open, TDO => tdo);
-- Explicit v1 version response. Newer openFPGALoader defaults to v1 on zero.
bscan_version : BSCANE2 generic map (JTAG_CHAIN => 4)
  port map (CAPTURE => open, DRCK => open, RESET => open, RUNTEST => open,
            SEL => open, SHIFT => open, TCK => open, TDI => open, TMS => open,
            UPDATE => open, TDO => '0');
tdo <= miso(0) when sel = '1' else tdi;
process(drck, runtest, granted)
begin
  if runtest = '1' or granted(0) = '0' then
    cs <= '1';
  elsif rising_edge(drck) then
    if capture = '1' and sel = '1' then cs <= '0'; end if;
  end if;
end process;
return_output.cclk(0) <= drck and granted(0);
return_output.cs_n(0) <= cs or not granted(0);
return_output.dq0(0) <= tdi;
return_output.dq0_t(0) <= '0';
return_output.dq1(0) <= '1';
return_output.dq1_t(0) <= '1';
return_output.dq2(0) <= '1';
return_output.dq2_t(0) <= '0';
return_output.dq3(0) <= '1';
return_output.dq3_t(0) <= '0';
return_output.read_data <= (others => '0');
return_output.ready(0) <= not granted(0);
return_output.busy(0) <= granted(0);
return_output.done(0) <= '0';
return_output.error(0) <= '0';
return_output.quad_enabled(0) <= '0';
return_output.quad_activity(0) <= '0';
return_output.quad_write_activity(0) <= '0';
"""


@hw_func
def spi_bridge(miso: uint1_t, granted: uint1_t) -> qspi_flash_byte_io_t:
    # Same SPI/TDO latency as upstream's original spiOverJtag implementation.
    vhdl(_SPI_VHDL)


@sim_model(spi_bridge)
@hw_func
def _spi_bridge_sim(miso: uint1_t, granted: uint1_t) -> qspi_flash_byte_io_t:
    return qspi_flash_byte_io_t(cclk=0, cs_n=1, dq0=0, dq0_t=0,
        dq1=1, dq1_t=1, dq2=1, dq2_t=0, dq3=1, dq3_t=0,
        read_data=0, ready=~granted, busy=granted, done=0, error=0,
        quad_enabled=0, quad_activity=0, quad_write_activity=0)


_CONTROL_VHDL = _BSCAN + """
signal capture, drck, sel, shift, tdi, update : std_logic;
signal data : std_logic_vector(63 downto 0) := (others => '0');
signal count : integer range 0 to 64 := 0;
signal mailbox : unsigned(1 downto 0) := (others => '0');
signal request, request_meta, request_sync, seen : std_logic := '0';
signal command : unsigned(1 downto 0) := (others => '0');
attribute ASYNC_REG : string;
attribute ASYNC_REG of request_meta, request_sync : signal is "TRUE";
begin
bscan_control : BSCANE2 generic map (JTAG_CHAIN => 2)
  port map (CAPTURE => capture, DRCK => drck, RESET => open, RUNTEST => open,
            SEL => sel, SHIFT => shift, TCK => open, TDI => tdi, TMS => open,
            UPDATE => update, TDO => data(0));
process(drck)
begin
  if rising_edge(drck) then
    if capture = '1' and sel = '1' then
      data <= std_logic_vector(status) & x"52464c32";
      count <= 0;
    elsif shift = '1' and sel = '1' then
      data <= tdi & data(63 downto 1);
      if count < 64 then count <= count + 1; end if;
    end if;
  end if;
end process;
process(update)
begin
  if rising_edge(update) then
    if sel = '1' and count = 64 and data(63 downto 32) = x"52464c32"
       and data(31 downto 2) = (31 downto 2 => '0') then
      mailbox <= unsigned(data(1 downto 0));
      request <= not request;
    end if;
  end if;
end process;
-- Mailbox holds steady across the toggle synchronizer until the next command.
process(clk)
begin
  if rising_edge(clk) then
    request_meta <= request;
    request_sync <= request_meta;
    seen <= request_sync;
    command <= (others => '0');
    if request_sync /= seen then command <= mailbox; end if;
  end if;
end process;
return_output <= command;
"""


@hw_func
def live_command(status: uint32_t) -> uint2_t:
    vhdl(_CONTROL_VHDL)


@sim_model(live_command)
@hw_func
def _live_command_sim(status: uint32_t) -> uint2_t:
    return uint2_t(0)
