# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 configuration-flash physical interface.

The four QSPI data pins and chip-select are ordinary package pins. The flash
clock is the Artix-7 configuration CCLK pin, which user logic can only drive
through STARTUPE2.

Important OpenXC7 detail: USRCCLKTS must be routed from fabric, not tied to a
constant.  nextpnr-xilinx currently disconnects constant-tied STARTUPE2 control
pins; on Basys 3 that leaves physical CCLK tri-stated even though USRCCLKO is
routed.  ``drive_clock_and_cs`` therefore takes an explicit, non-constant
``cclk_ts`` input.  cclk_ts=0 enables CCLK; cclk_ts=1 tri-states it.
"""

from pypeline import Input, Output, hw_func, sim_model, uint1_t, vhdl

QspiCSn: Output[uint1_t]
QspiDQ0: Output[uint1_t]
QspiDQ1: Input[uint1_t]
QspiDQ2: Output[uint1_t]
QspiDQ3: Output[uint1_t]


_STARTUPE2_VHDL = r"""
component STARTUPE2 is
  generic(
    PROG_USR : string := "FALSE";
    SIM_CCLK_FREQ : real := 0.0
  );
  port(
    CFGCLK : out std_logic;
    CFGMCLK : out std_logic;
    EOS : out std_logic;
    PREQ : out std_logic;
    CLK : in std_logic;
    GSR : in std_logic;
    GTS : in std_logic;
    KEYCLEARB : in std_logic;
    PACK : in std_logic;
    USRCCLKO : in std_logic;
    USRCCLKTS : in std_logic;
    USRDONEO : in std_logic;
    USRDONETS : in std_logic
  );
end component;
begin
qspi_startup : STARTUPE2
  port map(
    CFGCLK => open,
    CFGMCLK => open,
    EOS => open,
    PREQ => open,
    CLK => '0',
    GSR => '0',
    GTS => '0',
    KEYCLEARB => '1',
    PACK => '0',
    USRCCLKO => cclk(0),
    USRCCLKTS => cclk_ts(0),
    USRDONEO => '1',
    USRDONETS => '1'
  );
return_output <= cs_n;
"""


@hw_func
def drive_clock_and_cs(cclk: uint1_t, cs_n: uint1_t, cclk_ts: uint1_t) -> uint1_t:
    """Drive configuration CCLK through STARTUPE2 and pass CS# through unchanged."""
    vhdl(_STARTUPE2_VHDL)


@sim_model(drive_clock_and_cs)
@hw_func
def _drive_clock_and_cs_sim(cclk: uint1_t, cs_n: uint1_t, cclk_ts: uint1_t) -> uint1_t:
    return cs_n
