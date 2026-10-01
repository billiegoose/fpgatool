"""Bind Pypeline's 148.5 MHz MAIN domain to the Basys 3 oscillator.

The pinned OpenXC7 MMCM patch is validated for integer counters. Two MMCMs
provide exactly 148.5 MHz without fractional feedback: 100 * 27 / 4 / 5 =
135 MHz, then 135 * 11 / 2 / 5 = 148.5 MHz (VCOs 675 and 742.5 MHz).
Like the PS/2 and QSPI board adapters, this uses a synthesis-final hook;
the portable hardware functions and Pypeline simulation stay unchanged.
"""

import os
import re
from pathlib import Path

from pypeline import final


# GHDL/Yosys black-box generics use decimal strings for real parameters.
# VHDL real values become IEEE-754 bit vectors, which nextpnr cannot decode.
# Declare only used outputs: GHDL otherwise emits dangling nets for `open`,
# including inverted MMCM outputs that this backend cannot route.
_DECLARATIONS = """
-- Basys 3 exact 148.5 MHz pixel clock
component MMCME2_ADV is
  generic (
    BANDWIDTH : string := "OPTIMIZED";
    CLKIN1_PERIOD : string := "10.0";
    CLKFBOUT_MULT_F : string := "5.0";
    DIVCLK_DIVIDE : integer := 1;
    CLKOUT0_DIVIDE_F : string := "1.0";
    COMPENSATION : string := "ZHOLD";
    STARTUP_WAIT : string := "FALSE"
  );
  port (
    CLKIN1, CLKIN2, CLKINSEL, CLKFBIN, RST, PWRDWN : in std_logic;
    DADDR : in std_logic_vector(6 downto 0);
    DI : in std_logic_vector(15 downto 0);
    DCLK, DEN, DWE, PSCLK, PSEN, PSINCDEC : in std_logic;
    CLKFBOUT, CLKOUT0, LOCKED : out std_logic
  );
end component;
component BUFG is
  port (I : in std_logic; O : out std_logic);
end component;
signal clk_148p5, pixel_clk_raw, intermediate_clk, intermediate_clk_raw : std_logic;
signal feedback_1, feedback_1_buf, feedback_2, feedback_2_buf : std_logic;
signal clock_locked_1, clock_locked_2 : std_logic;
signal pixel_ready_meta, pixel_ready : std_logic := '0';
attribute ASYNC_REG : string;
attribute ASYNC_REG of pixel_ready_meta, pixel_ready : signal is "TRUE";
"""

_INSTANCES = """
pixel_clock_stage1 : MMCME2_ADV
  generic map (CLKIN1_PERIOD => "10.0", CLKFBOUT_MULT_F => "27.0",
               DIVCLK_DIVIDE => 4, CLKOUT0_DIVIDE_F => "5.0")
  port map (CLKIN1 => clk_100p0, CLKFBIN => feedback_1_buf,
            RST => '0', PWRDWN => '0', LOCKED => clock_locked_1,
            CLKFBOUT => feedback_1, CLKOUT0 => intermediate_clk_raw,
            CLKIN2 => '0', CLKINSEL => '1', DADDR => (others => '0'),
            DI => (others => '0'), DCLK => '0', DEN => '0', DWE => '0',
            PSCLK => '0', PSEN => '0', PSINCDEC => '0');
pixel_clock_feedback1 : BUFG port map (I => feedback_1, O => feedback_1_buf);
pixel_clock_intermediate : BUFG port map (I => intermediate_clk_raw, O => intermediate_clk);
pixel_clock_stage2 : MMCME2_ADV
  generic map (CLKIN1_PERIOD => "7.407407407", CLKFBOUT_MULT_F => "11.0",
               DIVCLK_DIVIDE => 2, CLKOUT0_DIVIDE_F => "5.0")
  port map (CLKIN1 => intermediate_clk, CLKFBIN => feedback_2_buf,
            RST => not clock_locked_1, PWRDWN => '0', LOCKED => clock_locked_2,
            CLKFBOUT => feedback_2, CLKOUT0 => pixel_clk_raw,
            CLKIN2 => '0', CLKINSEL => '1', DADDR => (others => '0'),
            DI => (others => '0'), DCLK => '0', DEN => '0', DWE => '0',
            PSCLK => '0', PSEN => '0', PSINCDEC => '0');
pixel_clock_feedback2 : BUFG port map (I => feedback_2, O => feedback_2_buf);
pixel_clock_output : BUFG port map (I => pixel_clk_raw, O => clk_148p5);

-- Hold the timing counters until lock has crossed into the pixel domain.
process(clk_148p5, clock_locked_2)
begin
  if clock_locked_2 = '0' then
    pixel_ready_meta <= '0';
    pixel_ready <= '0';
  elsif rising_edge(clk_148p5) then
    pixel_ready_meta <= '1';
    pixel_ready <= pixel_ready_meta;
  end if;
end process;
"""


def _rewrite_final_top_text(text: str) -> str:
    if "pixel_clock_stage1 : MMCME2_ADV" in text:
        return text
    text, count = re.subn(
        r"(?m)^clk_148p5\s*:\s*in\s+std_logic;",
        "clk_100p0 : in std_logic;", text,
    )
    if count != 1:
        raise RuntimeError("Basys 3 pixel clock requires one 148.5 MHz MAIN clock port")
    text, count = re.subn(
        r"(?m)^begin\s*$", _DECLARATIONS + "\nbegin\n" + _INSTANCES,
        text, count=1,
    )
    if count != 1:
        raise RuntimeError("Basys 3 pixel clock could not find top architecture body")
    text, count = re.subn(
        r"(\bclk_148p5,\s*\n)to_unsigned\(1,1\),",
        r"\1unsigned'(0 => pixel_ready),", text,
    )
    if count != 1:
        raise RuntimeError("Basys 3 pixel clock requires one 148.5 MHz MAIN instance")
    return text


@final(syn=True)
def _bind_basys3_pixel_clock():
    import SYN

    top_path = os.environ.get("FPGATOOL_FINAL_TOP_VHDL")
    if not top_path:
        raise RuntimeError("Basys 3 pixel clock requires FPGATOOL_FINAL_TOP_VHDL")
    path = Path(top_path)
    path.write_text(_rewrite_final_top_text(path.read_text()))

    # The compiler constrains MAIN's generated 148.5 MHz clock. Add the
    # oscillator constraint only for this design; putting it in the shared
    # board XDC duplicates the compiler's constraint for 100 MHz examples.
    constraints = path.with_name("pixel_clock.xdc")
    if Path(SYN.PIN_CONSTRAINTS_FILE) != constraints:
        board_xdc = Path(SYN.PIN_CONSTRAINTS_FILE).read_text()
        constraints.write_text(
            board_xdc + "\ncreate_clock -period 10.0 [get_ports clk_100p0]\n"
        )
    SYN.PIN_CONSTRAINTS_FILE = str(constraints)
