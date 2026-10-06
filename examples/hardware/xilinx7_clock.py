# pyright: reportInvalidTypeForm=none
"""Integer MMCM chains for the pinned OpenXC7 Artix-7 -1 flow.

The primitive consumes the calling MAIN's clock. Connect its clock output to
Wire[uint1_t] = make_clock(generator.output_mhz); synchronize lock in the
receiving domain before enabling stateful hardware. No generated-top edits.
"""

from dataclasses import dataclass
import math

from pypeline import NamedTuple, Reg, hw_func, sim_model, struct, uint1_t, vhdl


@struct
class clock_signals_t(NamedTuple):
    clock: uint1_t
    locked: uint1_t


@dataclass(frozen=True)
class MmcmStage:
    multiply: int
    input_divide: int
    output_divide: int


# Decimal strings are intentional: GHDL real generics become IEEE-754 bit
# vectors, whereas nextpnr expects decimal strings. Only declare used outputs
# so GHDL does not create dangling nets on unsupported inverted MMCM outputs.
_COMPONENTS = """
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
"""


def make_mmcm_clock(input_mhz: float, *stages: MmcmStage):
    """Create a clock primitive using explicit integer stage ratios.

    Limits target Artix-7 -1 (600..1200 MHz VCO). The input rate must match
    the caller's MAIN. This is a synthesis primitive, not an analog lock or
    jitter simulation model. Fractional counters are deliberately unsupported.
    """
    rate = float(input_mhz)
    if not math.isfinite(rate) or not 10 <= rate <= 800:
        raise ValueError("MMCM input clock must be finite and within 10..800 MHz")
    if not stages:
        raise ValueError("at least one MMCM stage is required")
    declarations = [_COMPONENTS]
    instances = []
    for i, stage in enumerate(stages):
        for name, value, minimum, maximum in (
            ("multiply", stage.multiply, 2, 64),
            ("input_divide", stage.input_divide, 1, 106),
            ("output_divide", stage.output_divide, 1, 128),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
        pfd = rate / stage.input_divide
        if not 10 <= pfd <= 450:
            raise ValueError(f"stage {i} PFD {pfd:g} MHz is outside 10..450 MHz")
        vco = pfd * stage.multiply
        if not 600 <= vco <= 1200:
            raise ValueError(f"stage {i} VCO {vco:g} MHz is outside 600..1200 MHz")
        output = vco / stage.output_divide
        if not 4.69 <= output <= 800:
            raise ValueError(f"stage {i} output {output:g} MHz is outside 4.69..800 MHz")
        if i + 1 < len(stages) and output < 10:
            raise ValueError("an intermediate MMCM clock must be at least 10 MHz")
        declarations.append(
            f"signal c{i}, raw{i}, fb{i}, fb_buf{i}, locked{i} : std_logic;"
        )
        source = "clk" if i == 0 else f"c{i - 1}"
        reset = "reset(0)" if i == 0 else f"reset(0) or not locked{i - 1}"
        instances.append(f"""
mmcm_{i} : MMCME2_ADV
  generic map (CLKIN1_PERIOD => "{1000 / rate:.12g}",
               CLKFBOUT_MULT_F => "{stage.multiply}.0",
               DIVCLK_DIVIDE => {stage.input_divide},
               CLKOUT0_DIVIDE_F => "{stage.output_divide}.0")
  port map (CLKIN1 => {source}, CLKFBIN => fb_buf{i},
            RST => {reset}, PWRDWN => '0', LOCKED => locked{i},
            CLKFBOUT => fb{i}, CLKOUT0 => raw{i},
            CLKIN2 => '0', CLKINSEL => '1', DADDR => (others => '0'),
            DI => (others => '0'), DCLK => '0', DEN => '0', DWE => '0',
            PSCLK => '0', PSEN => '0', PSINCDEC => '0');
feedback_{i} : BUFG port map (I => fb{i}, O => fb_buf{i});
output_{i} : BUFG port map (I => raw{i}, O => c{i});
""")
        rate = output
    body = "\n".join(declarations) + "\nbegin\n" + "\n".join(instances)
    body += f"return_output.clock(0) <= c{len(stages) - 1};\n"
    body += f"return_output.locked(0) <= locked{len(stages) - 1};\n"

    @hw_func
    def clock_generator(reset: uint1_t) -> clock_signals_t:
        vhdl(body)

    @sim_model(clock_generator)
    @hw_func
    def clock_generator_sim(reset: uint1_t) -> clock_signals_t:
        # Native simulation schedules MAIN clock edges by their MHz rates.
        # This is an ideal clock/lock model; no analog acquisition or jitter.
        return clock_signals_t(clock=1, locked=not reset)

    clock_generator.input_mhz = float(input_mhz)
    clock_generator.output_mhz = rate
    return clock_generator


@hw_func
def synchronize_clock_lock(locked: uint1_t) -> uint1_t:
    """Async clear, two-edge release in the caller's destination clock domain."""
    vhdl("""
signal ready_meta, ready : std_logic := '0';
attribute ASYNC_REG : string;
attribute ASYNC_REG of ready_meta, ready : signal is "TRUE";
begin
process(clk, locked)
begin
  if locked(0) = '0' then
    ready_meta <= '0';
    ready <= '0';
  elsif rising_edge(clk) then
    ready_meta <= '1';
    ready <= ready_meta;
  end if;
end process;
return_output(0) <= ready;
""")


@sim_model(synchronize_clock_lock)
@hw_func
def synchronize_clock_lock_sim(locked: uint1_t) -> uint1_t:
    ready_meta: Reg[uint1_t] = 0
    ready: Reg[uint1_t] = 0
    if not locked:
        ready_meta = 0
        ready = 0
        return 0
    result = ready
    ready = ready_meta
    ready_meta = 1
    return result
