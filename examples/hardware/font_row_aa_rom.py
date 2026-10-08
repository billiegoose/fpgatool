# pyright: reportInvalidTypeForm=none
"""AA font patterns: single-port 512 x 42-bit, one-cycle block ROM."""
from pypeline import *
from ram import make_ram, RamConfig, ram_vhdl_text, ram_model_class


def make_font_row_rom(words):
    reference, out_t = make_ram(uint42_t, 512, ports=("r",),
                              read_latency=1, init=words)
    cfg = RamConfig("red2_aa_font_row_rom", uint42_t, 512, ("r",), 1, 0, 0, words, False)
    body = ram_vhdl_text(cfg, handshake=False)
    body = body.replace('\nbegin\n', '\nattribute ram_style : string;\n'
                        'attribute ram_style of ram_mem : signal is "block";\nbegin\n', 1)
    input_t = reference.p0_in_t

    @pipeline_latency(1)
    def font_row_rom(p0: input_t) -> out_t:
        vhdl(body)

    sim_model(font_row_rom)(ram_model_class(cfg, False, reference.out_ts, out_t))
    font_row_rom.p0_in_t = input_t
    font_row_rom.latency = 1
    return font_row_rom
