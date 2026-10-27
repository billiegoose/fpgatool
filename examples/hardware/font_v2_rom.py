# pyright: reportInvalidTypeForm=none
"""One dual-port 1024x32 font store with synchronous, one-clock reads."""
from pypeline import *
from ram import make_ram, RamConfig, ram_vhdl_text, ram_model_class


def make_font_v2_rom(words):
    reference, out_t = make_ram(uint32_t, 1024, ports=('r', 'r'), read_latency=1, init=words)
    cfg = RamConfig('red2_font_v2_rom', uint32_t, 1024, ('r', 'r'), 1, 0, 0, words, False)
    body = ram_vhdl_text(cfg, handshake=False)
    body = body.replace('\nbegin\n', '\nattribute ram_style : string;\n'
                        'attribute ram_style of ram_mem : signal is "block";\nbegin\n', 1)
    input_t, input1_t = reference.p0_in_t, reference.p1_in_t

    @pipeline_latency(1)
    def font_v2_rom(p0: input_t, p1: input1_t) -> out_t:
        vhdl(body)

    sim_model(font_v2_rom)(ram_model_class(cfg, False, reference.out_ts, out_t))
    font_v2_rom.p0_in_t = input_t
    font_v2_rom.p1_in_t = input1_t
    return font_v2_rom
