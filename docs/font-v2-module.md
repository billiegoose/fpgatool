# Reusing the font-v2 renderer

The hardware lives in `examples/hardware/font_v2/`. Add this repository's
`examples` directory to your design's Python import path alongside Pypeline's
library. The package imports no board pins, UART, VGA timing, clock generator,
or demo text buffer. It does not instantiate memories on import.

| Module | Responsibility |
| --- | --- |
| `renderer.py` | Unicode lookup, row decoding, two-glyph kerning, backpressured glyph output |
| `types.py` | Active configuration, glyph-row packet, memory-address outputs |
| `mapping.py` | Registered Unicode page lookup |
| `row_address.py` | Registered crop/mirroring and row-address calculations |
| `memory.py` | Factory for one dual-port 1024×32 BRAM |
| `format.py` | Binary-format constants; also importable without Pypeline |
| `loader.py` | Optional QSPI boot, validation and vertical-blank reload |

`hardware/vga_uart_font_v2_pixels.py` is the demo adapter. It owns UART decoding,
text RAM, line wrapping, margins, the 64-bit overlap compositor, pixel FIFO,
and VGA timing. The board top owns physical pins, MMCM wiring, BRAM connection,
and the live-flash proxy. Raster-engine can use the glyph reader with its own
text storage, scheduling, compositor, palette and video output.

## Glyph-row interface

```python
from hardware.font_v2.renderer import read_glyph_row
from hardware.font_v2.types import font_v2_config_t

# Call once per application clock, alongside caller-owned synchronous RAMs.
glyph = read_glyph_row(
    config, font_ready,
    text_data, font_data_a, font_data_b,
    row_y, text_end, start_index, origin,
    start, stop, take)
```

| Input | Contract |
| --- | --- |
| `config` | Validated active header (`font_v2_config_t`), stable during a row |
| `font_ready` | Font memory/configuration may be used; low flushes the reader |
| `text_data` | One-clock synchronous response to `text_address`; 24-bit codepoint |
| `font_data_a/b` | One-clock synchronous responses to the two font addresses |
| `row_y` | Glyph-relative Y, stable during the row; ordinary glyphs occupy 0–31 |
| `text_end` | Exclusive end of the caller's text snapshot, stable during the row |
| `start_index` | First text index, sampled on `start` |
| `origin` | Starting X for this row, signed 13-bit, stable during the row |
| `start` | One-clock restart, resets history and discards pending output |
| `stop` | Abort and discard pending output; `start` has priority |
| `take` | Consume this cycle's valid packet; the reader holds it while stalled |

The result contains `font_address_a/b` (10 bits), `text_address` (12 bits),
`valid`, and `row`. A packet is accepted only when `valid & take`. `start`,
`stop`, or a low `font_ready` suppress validity immediately. A start while
`font_ready` is low is discarded. Hold the inputs stable and call the function
every clock even when output is stalled; the memory pipeline remains active.

`row` contains:

- `kind`: 0 glyph, 1 newline, 2 end of text. Other C0 controls are skipped.
- `index` and `after`: text position and continuation position. A newline's
  `after` points past LF; end-of-text `after` equals `text_end`.
- For glyphs: `bits` (21 bits, bit 0 is leftmost), `width`, and final kerned
  `origin`. `backtrack` is currently zero. Ink/geometry fields on control packets
  are unspecified and must be ignored.

Missing codepoints use glyph zero, including its ink, width and kerning classes.
The reader applies the same two-glyph history used by the demo. It neither
clips nor wraps. A caller can stop on a glyph outside its bounds, then start the
next line at that packet's `index`; on LF, continue from `after`.

For raster-engine's lane compositor, accept a glyph packet when a lane is
available, use `origin`/`width` for its horizontal extent, and pass `bits` as ink.
The caller chooses clipping and layer. This refactor supplies that interface;
it does not change raster-engine's existing scene format or integrate a new
font asset type there.

## Memory and reload ownership

Create BRAM explicitly with `hardware.font_v2.memory.make_font_v2_rom()` or supply
an equivalent one-clock dual-read memory. The reader owns no BRAM and has no
write port. The caller connects read addresses/data and grants writes to a
loader only when rendering is stopped. Text storage is likewise caller-owned.
The demo uses logical wires to connect synchronous memory responses without
adding registers at the module boundary. With the pinned compiler, put a
logical feedback wire's reader and writer in distinct hardware functions (or
actors); reading and then assigning that same wire in one function becomes an
external readback input. The demo's `text_memory()` adapter shows this wiring.

`hardware.font_v2.loader.load_font_from_qspi()` remains an optional asset loader.
It returns validated active configuration and BRAM writes, accepts the caller's
blank-start/deadline pulses, and keeps the previous header active until a
successful copy. The active-header snapshot still costs 411 flip-flops; the
previously noted opportunity to remove that snapshot remains unimplemented.

The live-flash service is independent of fonts. Its `proxy()` accepts application
flash signals and explicit MISO, then returns the selected QSPI bus plus control
status. Only the top binds that bus to board pins and STARTUPE2; see
[live-flash.md](live-flash.md).

After changes to module hierarchy or scheduling, recheck the UART/VGA HDL golden
frames and route timing before loading a replacement bitstream. Historical
`build/font-v2-live.bit` and its manifest remain the saved hardware-tested build.

## Refactor validation (2026-10-28)

The UART/VGA harness matches all 1920×1080 pixels across eight HDL frames,
including the spacing reload: old, new, new, new, new, new, new, new. Standalone
reader tests compare every reference glyph against independent column data,
exercise Unicode fallback and two-glyph kerning, and hold output under stalls.
Proxy tests cover explicit MISO, complete-bus selection and idle-before-grant;
the JTAG HDL tests also pass. The host suite passes 191 tests with 75 optional
Pypeline/GHDL tests skipped; the native hardware tests were run separately.

The final synthesized netlist routes at **156.94 MHz** for the 148.5 MHz target
with the corrected timing database and **placement seed 1**. The build wrapper
now defaults to seed 1. Packed resources are **3,433 LUT sites**, **2,471 FFs**,
one RAMB36 for the font and three RAMB18s for text. The previous extracted
live-flash demo used 3,453 LUT sites and the same FF/BRAM counts. No additional
pipeline stage was introduced by selecting this placement.

The checked bitstream is `build/font-v2-module.bit`; timing is recorded in
`build/font-v2-module-timing.log` and source/test hashes in
`build/font-v2-module-validation.json`. Its implementation artifacts are under
`build/basys3/vga_uart_1920_1080_font_v2_demo/pipelinec/top/seed1/`.
The refactored bitstream was loaded onto Basys 3 on 2026-10-28. USER1 readback
returned the existing 4,256-byte font with a valid header/checksum and SHA-256
`3a07f19f892e9099366aaeab8b730c6ebd8bd2c2b9606fc140eda0fd0469cfa0`.
Reloading that stored font advanced generation 1 → 2 and returned READY with
BUSY/GRANTED/ERROR clear. This check did not write flash. The previous
hardware-tested `build/font-v2-live.bit` remains preserved.
