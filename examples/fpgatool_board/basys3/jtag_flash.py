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
signal capture, drck, tck, runtest, sel, shift, tdi, cs : std_logic := '0';
signal mosi_captured, shift_seen : std_logic := '0';
signal cap_meta, cap_sync, sel_meta, sel_sync, run_meta, run_sync : std_logic := '0';
signal tdo : std_logic;
-- Cross the slow JTAG signals into the 100 MHz application clock domain.
-- MOSI is registered several cycles before its matching SPI rising edge.
signal tck_meta, tck_sync, tck_d0, tck_d1, tck_d2 : std_logic := '0';
signal tdi_meta, tdi_sync, mosi_reg : std_logic := '0';
signal shift_meta, shift_sync, shifting : std_logic := '0';
signal cs_meta, cs_sync : std_logic := '1';
signal have_meta, have_sync : std_logic := '0';
signal sck_reg : std_logic := '0';
attribute ASYNC_REG : string;
attribute ASYNC_REG of tck_meta, tck_sync, tdi_meta, tdi_sync, shift_meta, shift_sync, cs_meta, cs_sync, cap_meta, cap_sync, sel_meta, sel_sync, run_meta, run_sync, have_meta, have_sync : signal is "TRUE";
begin
bscan_spi : BSCANE2 generic map (JTAG_CHAIN => 1)
  port map (CAPTURE => capture, DRCK => drck, RESET => open, RUNTEST => runtest,
            SEL => sel, SHIFT => shift, TCK => tck, TDI => tdi, TMS => open,
            UPDATE => open, TDO => tdo);
-- Only instantiate the functional USER1 and USER2 chains. The pinned
-- Himbächel placer can allocate an unused USER4 instance ahead of them,
-- displacing their physical BSCAN sites and breaking the JTAG mailbox.
tdo <= miso(0) when sel = '1' else tdi;
-- Capture MOSI on the USER1 DRCK rising edge. The delayed system-clock
-- SPI rising edge follows this capture, preserving the first command bit.
process(drck, runtest, granted)
begin
  if runtest = '1' or granted(0) = '0' then
    mosi_captured <= '0';
    shift_seen <= '0';
  elsif rising_edge(drck) then
    if sel = '1' and shift = '1' then
      mosi_captured <= tdi;
      shift_seen <= '1';
    end if;
  end if;
end process;
-- A full CAPTURE-DR phase precedes SHIFT-DR. Synchronize that phase and
-- assert CS while SCK is still held low, instead of relying on an
-- asynchronous falling-DRCK event whose placement relative to CAPTURE varies.
process(clk)
begin
  if rising_edge(clk) then
    cap_meta <= capture;
    cap_sync <= cap_meta;
    sel_meta <= sel;
    sel_sync <= sel_meta;
    run_meta <= runtest;
    run_sync <= run_meta;
    if granted(0) = '0' or run_sync = '1' then
      cs <= '1';
    elsif cap_sync = '1' and sel_sync = '1' then
      cs <= '0';
    end if;
  end if;
end process;
-- Do not use raw BSCAN DRCK as a physical SPI clock. Its route to STARTUPE2
-- can otherwise race the independent TDI-to-IOBUF route. At 3 MHz JTAG,
-- six 100 MHz cycles of clock latency leave generous room inside each bit.
process(clk)
begin
  if rising_edge(clk) then
    -- SPI SCK is system-clock registered; MOSI is DRCK captured.
    -- BSCAN TCK is sampled strictly as asynchronous data.
    tck_meta <= tck;
    tck_sync <= tck_meta;
    tck_d0 <= tck_sync;
    tck_d1 <= tck_d0;
    tck_d2 <= tck_d1;
    tdi_meta <= tdi;
    tdi_sync <= tdi_meta;
    mosi_reg <= tdi_sync;
    shift_meta <= shift;
    shift_sync <= shift_meta;
    cs_meta <= cs;
    cs_sync <= cs_meta;
      have_meta <= shift_seen;
      have_sync <= have_meta;
    -- Latch the start of SHIFT_DR rather than qualifying every bit with the
    -- asynchronous SHIFT signal. This retains the final SPI clock pulse.
    if granted(0) = '0' or run_sync = '1' then
      shifting <= '0';
    elsif shift_sync = '1' then
      shifting <= '1';
    elsif tck_d2 = '0' then
      -- SHIFT may fall on the last JTAG rising edge; allow its delayed SPI
      -- clock to finish high and return low before ending the transaction.
      shifting <= '0';
    end if;
    -- Capture-DR does not generate an SPI clock. CS and MOSI have already
    -- settled before the first delayed SHIFT_DR rising edge.
    if granted(0) = '1' and shifting = '1' and cs_sync = '0' and have_sync = '1' then
      sck_reg <= tck_d2;
    else
      sck_reg <= '0';
    end if;
  end if;
end process;
return_output.cclk(0) <= sck_reg;
return_output.cs_n(0) <= cs_sync or not granted(0);
return_output.dq0(0) <= mosi_captured;
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
-- USER2 application-to-DRCK status CDC: two-phase toggle handshake.
-- The payload is held in the 100 MHz domain until the next accepted request;
-- the DRCK domain copies it only after two ack synchronizer stages.
signal status_hold, status_jtag : std_logic_vector(31 downto 0) := (others => '0');
signal status_request, status_request_meta, status_request_sync,
       status_request_seen, status_ack, status_ack_meta, status_ack_sync,
       status_ack_seen : std_logic := '0';
signal command : unsigned(1 downto 0) := (others => '0');
attribute ASYNC_REG : string;
attribute ASYNC_REG of request_meta, request_sync, status_request_meta,
                       status_request_sync, status_ack_meta, status_ack_sync : signal is "TRUE";
begin
bscan_control : BSCANE2 generic map (JTAG_CHAIN => 2)
  port map (CAPTURE => capture, DRCK => drck, RESET => open, RUNTEST => open,
            SEL => sel, SHIFT => shift, TCK => open, TDI => tdi, TMS => open,
            UPDATE => update, TDO => data(0));
process(drck)
begin
  if rising_edge(drck) then
    status_ack_meta <= status_ack;
    status_ack_sync <= status_ack_meta;
    if status_ack_sync /= status_ack_seen then
      -- Ack has crossed to DRCK; status_hold was frozen before the ack.
      status_jtag <= status_hold;
      status_ack_seen <= status_ack_sync;
    end if;
    if capture = '1' and sel = '1' then
      -- Capture the previous completed snapshot, never live status bits.
      data <= status_jtag & x"52464c32";
      count <= 0;
      if status_request = status_ack_sync then
        status_request <= not status_request;
      end if;
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
    status_request_meta <= status_request;
    status_request_sync <= status_request_meta;
    if status_request_sync /= status_request_seen then
      status_hold <= std_logic_vector(status);
      status_request_seen <= status_request_sync;
      status_ack <= status_request_sync;
    end if;
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
