# Font v2 non-AA renderer

**Timing qualification:** the pinned OpenXC7 timing database is incomplete.
The hardware audit found missing DSP timing and RAMB36 timing arcs referring
to nonexistent clock pins. The passing results below use an isolated corrected
database; normal builds do not yet include those corrections.
The live-update revision has passed physical board validation and is loaded
in volatile SRAM. Programming persistent configuration flash is a separate step.

`examples/vga_uart_1920_1080_font_v2_demo.py` is the font-v2 renderer at
148.5 MHz / 1080p. Its capture companion replaces the MMCM with an ideal clock.

```sh
# Optional: regenerate the checked-in simulation reference (not the live font).
../red2-font/.venv/bin/python ../red2-font/generate_font.py v2-reference \
  examples/hardware/red2_row_data.py --output examples/hardware/red2_font_v2_data.py \
  --binary build/reference-font-v2.bin
./fpgatool.sh sim examples/vga_uart_1920_1080_font_v2_capture.py \
  --no-open --uart-file assets/red2-font-v2-stress.txt --frames 8
python3 scripts/verify_uart_pixels.py \
  build/basys3/vga_uart_1920_1080_font_v2_capture/sim/frame.png \
  assets/red2-font-v2-stress.txt --notdef
```

Use `assets/red2-font-v2-notdef.txt` with the same capture and verification
commands to exercise lowercase/undefined Unicode fallback and editing.

Use the corrected-model build described in the validation results below for
physical timing. The normal pinned database still has the audited timing gaps;
a normal `build --comb` report does not establish timing closure.

From a checkout, enter the toolchain shell and run the checked build:

```sh
./fpgatool.sh shell
bash toolchain/build-font-demo-with-corrected-timing.sh
```

The wrapper generates an isolated database under `build/font-v2-timingdb`,
builds the demo, and rejects a final route that misses timing. Its generator
and diagnostic patch are tracked; no files from earlier local experiments
are required. The resulting bitstream is
`build/basys3/vga_uart_1920_1080_font_v2_demo/pipelinec/top/top.bit`.

## Current font image (format version 2)

All payload tables share one synchronous, true-dual-port **1024 × 32** font
memory. The current image uses **3,360 bytes**, leaving **736 bytes**:

| Table | Bytes | Word base |
| --- | ---: | ---: |
| 85 glyph descriptors | 340 | 0 |
| 29 crop classes | 60 | 85 |
| Overlapping, mirrored row-ID streams | 1,136 | 100 |
| Padded 32 × 32 kerning | 512 | 384 |
| 264 pattern words, including the overlaid ASCII map | 1,056 | 512 |
| Packed U+25xx Unicode page | 256 | 776 |

Each pattern is one word: `pattern:21` in bits [20:0], `map_byte:8` in
[28:21], and three reserved zero bits. The first 256 pattern words carry the
U+00xx map. The pattern address is simply
`PATTERNS_BASE + (bank << 8) + row_id`; the result is bits [20:0]. There is
no division, remainder calculation, cross-word assembly, or second pattern
read. Kerning precedes patterns so the 128-word kerning table starts at
word 384 and patterns start at word 512. For this image, kerning, pattern,
and ASCII-map addresses simplify to fixed prefixes plus their index bits;
no padding or address adders are needed for those requests. Neither patterns nor other static font tables move into registers/LUTs.

The exporter explicitly reserves at least 256 pattern words when that map is
present, padding unused patterns with zero. A small font therefore works even
with fewer than 256 distinct patterns. A one-bank font uses bank 0; two-bank
fonts pad bank 0 to 256 words so bank 1 starts at pattern ID 256. Pattern count
includes allocated padding and any patterns duplicated between banks.

Descriptor fields remain `base:11, crop_class:5, left_class:5,
right_class:5, width:5, bank:1`, least significant first. `base` is a byte
offset into the row pool. A crop entry contains `top_y:5, height:6, mirror:1,
reserved:4`; height is the expanded height. Four row IDs share each word.

A Unicode page directory entry is `(prefix, map_word_base, glyph_base,
glyph_count, encoding)`. High 16 codepoint bits select the page; the map
returns a local glyph ID, which is checked against the count and added to
`glyph_base`. Encoding 0 packs four map bytes per word: read
`map_word_base + (low >> 2)` and select byte `low & 3`. Encoding 1 reads
`map_word_base + low` and extracts bits [28:21]. This font uses encoding 1 for
U+00xx and encoding 0 for U+25xx. Both take one memory read. Missing entries
are 255; missing entries and absent pages select global glyph 0 (`.notdef`).
Fallback glyphs paint and participate in width/kerning history like supported
glyphs. Newline, editing controls, and the existing ignored control tokens keep
their special behavior.

The hardware demo boots its font from QSPI flash offset **`0x220000`**, the
Basys 3 `program-data` default. Header/page-directory fields live in registers;
all 1,024 payload words live in one true-dual-port BRAM. Port A writes during
loading; both read ports are disabled during replacement. Write commands cross
a register boundary before the BRAM actor and settle before ready is asserted.
VGA timing and UART reception continue throughout.

```sh
# In the sibling red2-font checkout:
python3 generate_font.py --export v2

# In fpgatool: install the optional host dependency once.
uv pip install --python .venv/bin/python pyftdi==0.57.1

# Build and load/program the updated demo once (see build commands above).
# Then update the font without reconfiguring or resetting the FPGA:
./fpgatool.sh program-data ../red2-font/dist/RED2-Regular-v2.bin --live --reload
```

`--live` is format-independent: it checks the board's user-data range and
verifies the written bytes. The exporter produces the font layout; the FPGA
preflight parser checks header fields, checksum, counts and table/map bounds.
For host-side font validation, including unique Unicode page prefixes and glyph
row bounds, run `generate_font.py validate-v2 FONT.bin` in red2-font. Its shared
compiler validates exported headers as part of generation. The general CLI
does not parse font images.
It checks the resident USER2 mailbox signature and requests exclusive
flash ownership. One PyFtdi connection owns the adapter throughout programming;
openFPGALoader uses a loopback-only XVC relay with
`--skip-load-bridge --skip-reset --verify`. The relay preserves Digilent cable
GPIO levels and substitutes BYPASS for cleanup JSHUTDOWN/JPROGRAM instructions.
This covers openFPGALoader 1.1.1's unconditional reset after `program_spi()`;
its `--skip-reset` flag alone does not prevent that reset. Other configuration
instructions are refused. The resident USER1
SPI bridge implements openFPGALoader's v1 protocol. During erase/program/verify,
rendering continues from the old BRAM. With `--reload`, USER2 RELOAD releases the
flash, rechecks quad-enable, and starts a preflight read. Only a fully validated
image can request the in-place copy at the start of vertical blanking. The copy
revalidates the image, then publishes its header registers and ready state.
The next frame resets text pointers, placement, and kerning through the normal
frame preparation path. There is no font-buffer bank or frame of black output
on successful replacement. The loader reserves the last blank line for renderer
preparation; a missed deadline disables scanout instead of using partial data.

LD14 means active font ready; LD15 means invalid image, flash error, or a missed
copy deadline. A failed preflight keeps the old font active. A failed in-place
copy leaves the display black until another successful upload. Host programming
failure sends RELEASE and never reloads; an interrupted host may leave flash
ownership granted, requiring recovery/reconfiguration before another upload.
`--ftdi-serial SERIAL` selects the adapter owned by that single USB connection.
Plain `program-data` retains the original disruptive programming behavior for
all other designs/assets. `--live` accepts arbitrary binary data at any allowed
user-data address and refuses an absent/incompatible mailbox. Without `--reload`,
it releases ownership without changing active BRAM data or generation. For the
font demo, write a 4,256-byte font image at `0x220000` and add `--reload`.
The design's hook owns that fixed address; the host does not infer it from the
uploaded file. See [the general protocol](live-flash.md) for other designs.
No board programming is performed by the build.

The standalone exporter uses the same prepared glyphs and validated kerning as
its web and legacy BRAM exports. The profile supports 256 global glyph IDs
(including required `.notdef` at ID 0), 32 crop classes, 32 × 32 kerning,
two pattern banks, 2,048 row bytes, spacing 0–31, and eight Unicode pages.
Unsupported fonts fail export rather than silently truncating fields.

### Flash binary ABI

`RED2-Regular-v2.bin` is **4,256 bytes**: a fixed 160-byte header followed by
4,096 bytes of BRAM32. All integers and payload words are little endian.
Payload addresses are word offsets relative to BRAM word zero, excluding the
header. The checksum is the two's complement of the sum of all other 32-bit
words; the sum of the entire image is zero modulo 2³².

| Header word | Value |
| --- | --- |
| 0 | Magic `RFV2` (`0x32564652`) |
| 1–3 | Version `2`, header bytes `160`, payload words `1024` |
| 4 | Used payload bytes, word aligned (512–4096) |
| 5–9 | Metadata, crop, rows, kerning, pattern word bases |
| 10–13 | Glyph, crop, row-byte, allocated pattern counts |
| 14–15 | Spacing, Unicode page count (1–8) |
| 16 | Whole-image additive checksum |
| 17–23 | Reserved zero |
| 24–39 | Eight two-word page slots; unused slots are zero |

A page's first word packs `prefix:16`, `map_word_base:10`, `encoding:1`, then
five reserved zero bits, least significant first. Its second word packs
`glyph_base:8`, `glyph_count:9`, then fifteen reserved zero bits. Encodings
0 and 1 retain the packed-map and pattern-overlay behavior described above.
Directory prefixes are unique.
The loader checks header bounds before writing BRAM and checks the whole-image
checksum before enabling scanout. Startup/recovery and quad-enable checks reuse
`QSPI.flash_byte_io`; initialization occurs before the preflight, outside the
blanking budget. `qspi_burst.read_burst` then sends command/address/dummy once
(40 SCK), followed by two SCK per byte. At 148.5 MHz with five clocks per half
period, SCK is 14.85 MHz and 4,256 bytes take approximately 85,526 pixel clocks
(**0.576 ms**). The 45-line vertical blank is 99,000 pixel clocks (**0.667 ms**);
the copy deadline is the beginning of its final line (96,800 clocks). This leaves
about 76 microseconds before that deadline for control and checksum completion.
The [S25FL032P datasheet](https://www.infineon.com/assets/row/public/documents/10/49/infineon-s25fl032p-32-mbit-3.0-v-flash-memory-datasheet-en.pdf) rates quad-output reads up to 80 MHz; board I/O timing still needs
physical validation at the chosen 14.85 MHz rate. Loader, header registers, BRAM,
and renderer share the pixel clock. JTAG control crosses through a held mailbox
and a toggle synchronizer; SPI clock/pin ownership changes only with both
masters idle.

The capture harness feeds the serialized reference image through the same
header decoder and BRAM write interface, bypassing the physical QSPI bus.
The legacy conversion script also accepts `--binary path.bin` to write this
ABI alongside its Python reference constants.

## Renderer schedule

The font-v2 demo keeps an **eight-word pixel FIFO**, a one-row mailbox, and a
five-clock glyph initiation interval. It uses seven font reads per glyph.
In steady state, each period overlaps the pattern/placement of glyph `g`,
crop and kerning of `g+1`, and Unicode mapping of `g+2`:

| Clock / state | Port A request | Port B request | Response / register work |
| --- | --- | --- | --- |
| 0 / 3 | Crop(g+1) from registered crop address | Pattern(g) from registered pattern ID | Previous-origin candidate(g); registered kerning addresses(g+1) |
| 1 / 4 | Unicode map(g+2) | Older kerning(g+1) | Selected 12-bit crop(g+1), 21-bit pattern(g); register metadata page base(g+2) |
| 2 / 5 | Hold map(g+2) | Previous kerning(g+1) | Publish(g), registered map byte(g+2), prepared row(g+1), older kerning nibble(g+1) |
| 3 / 7 | Metadata(g+2) from registered map byte/page base, or fallback | Row ID(g+1) from prepared row | Previous kerning nibble(g+1), older step(g+1), ink/byte selector |
| 4 / 6 | Hold metadata(g+2) | Hold row ID(g+1) | Row ID/pending packet(g+1), previous step/older-origin candidate(g+1), metadata and crop-address register(g+2) |

Unicode page selection computes each candidate map address in parallel and
registers two groups of four directory entries on the codepoint prefetch path.
Combining their previous-cycle outputs keeps the same one-clock selected-address
interface while shortening the reduction before each register. Matching unique
prefixes are reduced without a priority chain. Bootstrap waits one additional clock for this cut;
the steady initiation interval stays at five clocks. The metadata page base
(`metadata_base + glyph_base`) is registered when the map read launches. The
map response only selects and registers its byte. The next phase computes the
candidate metadata address and checks that byte's bounds in parallel, then
selects the candidate or `.notdef` address. Map validity selects complete addresses after the arithmetic; no BRAM output
feeds a dependent BRAM address.

Every dependent ROM request consumes registered data: mapping -> map byte,
metadata -> crop address, crop -> selected crop -> prepared row, and row ID ->
pattern ID. Pattern assembly is a single [20:0] slice. Each kerning nibble,
advance, and origin addition crosses a separate register boundary. Both
kerning addresses are forecast and registered in state 3: publication of a
glyph will make its left class the previous class and move the old previous
class to older. Other tokens preserve history. Requests use those stored
addresses in states 4 and 5, so mailbox publication cannot forward a history
update into address arithmetic. Undefined printable codepoints advance history
using `.notdef`. The selected crop and prepared row retain their two explicit
row-arithmetic cuts.

The older/previous origin comparison is registered during the spare cycle
before publication. Both candidates are already stable then, so publication
selects with that saved comparison and keeps its existing cycle and pixel positions.

State 5 waits for mailbox space while the map and older-kerning requests,
saved pattern, crop, and metadata stay stable. The row helper may repeatedly capture the same
stable crop there; it never consumes the unrelated map word. Publication
advances class/origin history while the previous-kerning request uses the
already prepared address. State 6 copies the old current
packet into pending before accepting new metadata and prefetched token tags.
The controller explicitly advances `3 → 4 → 5 → 7 → 6 → 3`; bootstrap is
`1 → 2 → 5 → 7 → 6 → 3`, with invalid packets discarded.

BRAM requests use a parallel phase selector independent of the compositor's
reset/stop priority chain. Speculative requests while flushing are discarded;
phase 5 still holds map/older-kerning responses during publication stalls.
Scanline preparation registers its beam predicates one clock before use,
preserving the original `x = WIDTH + 32` handoff and frame-reset schedule.
The header parser uses a one-hot position for its 40 header words, with cached
table capacities and registered fault flags. These cuts keep control comparisons
out of BRAM addresses and distributed header/row register enables.

The lookup-to-publication latency is eleven clocks, while the initiation
interval remains five. Text cursors use 12 bits for 2,048 codepoints and their
end/prefetch positions. The existing compositor, row restart/drain behavior,
binary-to-color conversion, and FIFO handshake are retained. Physical timing
and board status for this revision are recorded below after validation.

## Original live-update validation (2026-10-27)

The selected pin-constrained route passes **148.68 MHz** against the 148.5 MHz
target, using the isolated corrected timing database and **placement seed 2**.
The critical path is the header fault reduction through write-enable control;
setup margin is only about **0.008 ns**, with no reported hold violations.
Resources are **2,172 LUT2–LUT6**, **2,440 flip-flops**, **one RAMB36E1** for the
font, **three RAMB18E1** for text, **six RAM32M** for the FIFO, and **zero DSPs**.
An area optimization remains available: removing the separate active font-header
snapshot would save **411 mapped flip-flops** (451 declared bits, of which 411
survive synthesis). It would require reusing the parser/header registers and
preventing preflight from changing metadata visible to the renderer. Header
validation and replacement would need to occur while scanout is paused, or use
a validation-only preflight that does not overwrite those registers. Recheck
vblank timing, failed-upload recovery, and final pixel placement before making
that tradeoff. The current implementation deliberately retains the snapshot.
The build helper validates the report for its selected seed; the timing parser
also handles nextpnr's aligned multi-clock report columns.

The checked artifact is `build/font-v2-live.bit`, its report is
`build/font-v2-live-timing.log`, and source hashes are in `build/font-v2-live.json`.
It was generated from the as-written final netlist, retaining fixed RAM latency,
with the existing Basys 3 QSPI pull-up workaround. As in the boot-loader route,
the preliminary throughput sweep was bypassed for this direct final build.
This is a modeled timing pass with very little margin, not vendor timing signoff.
These measurements describe the original inline live-update implementation.

### Reusable service validation (2026-10-27)

The demo now uses `fpgatool_board.basys3.live_flash.service()` for resident JTAG,
QSPI routing, ownership, and reload acknowledgement. The font loader retains
format validation and vblank activation. See the [integration guide](live-flash.md#adding-the-hardware-to-a-demo)
for the application handshake and use in other demos.

The extracted design passes final routing at **159.34 MHz** against the same
148.5 MHz target, with corrected timing data and **placement seed 4**. The build
helper now defaults to seed 4. Packed resources are **3,453 LUT sites** and
**2,471 flip-flops**, versus 3,408 and 2,440 for the inline version; BRAM counts
are unchanged. The report and bitstream are under
`build/basys3/vga_uart_1920_1080_font_v2_live_origin_cut/pipelinec/top/seed4/`.
The corrected bitstream was loaded onto Basys 3 and tested with an actual live
font upload: 88 glyphs, two pattern banks, 3,472 payload bytes. USER1 readback
matched all 4,256 file bytes before and after programming. The exact
`generate_font.py --export v2` / `program-data --live --reload` workflow advanced
generation 1 to 2, retaining READY with busy/grant/error clear. The bridge samples
CAPTURE on falling DRCK to avoid a placement-dependent chip-select race; the
programmer now requires completed readback verification before requesting reload.
The as-written final netlist was routed directly after
the initial throughput sweep; no automatic pipeline stages were added.

Wire-level native simulation checks 0x6B command/address/dummy clocks, quad-pad
turnaround, byte ordering, complete 4,256-byte bursts within the blanking budget,
and abort/restart. Loader tests cover two-pass validation, BRAM write ownership,
waiting for blank start, simultaneous header/data activation, rejected uploads,
aborted host uploads, missed deadlines, and recovery. GHDL tests exercise the
actual BSCANE2 wrapper bodies with a controllable primitive model, including
mailbox bit order, CDC command pulses, malformed transfers, and SPI grant/CS.
The host tests verify continuous USB ownership, GPIO preservation, bounds/checksum
rejection before flash access, programmer flags, and commit/abort ordering.
Relay tests cover fragmented XVC messages and instructions, TMS/TDI/TDO bit
order, FIFO batching, filtering reset instructions to BYPASS, and TAP resync.

The capture fixture can replace the font spacing with 9 at the sixth vertical
blank, using the same parser, registered BRAM writes, read-port gating, and
renderer. It emits words at the 14.85 MHz burst cadence while bypassing SPI pads.
Compare every captured frame using red2-font's independent binary decoder and
full-history pixel renderer. The font file must match the original simulation
fixture; generate it with `v2-reference` as shown above, rather than using a
newer artwork export:

```sh
FPGATOOL_FONT_RELOAD_CAPTURE=1 ./fpgatool.sh sim \
  examples/vga_uart_1920_1080_font_v2_capture.py --frames 8 --no-open \
  --uart-file assets/red2-font-v2-notdef.txt
../red2-font/.venv/bin/python ../red2-font/generate_font.py verify-v2-reload \
  build/basys3/vga_uart_1920_1080_font_v2_capture/sim \
  assets/red2-font-v2-notdef.txt --font build/reference-font-v2.bin
```

Eight captured frames match the independent reference exactly: one complete
old-spacing frame followed by seven complete new-spacing frames. No captured
frame is mixed or black during the update. The host suite passes 176 tests
(62 skipped for unavailable optional compiler/runtime dependencies); targeted
native tests and the two GHDL primitive-wrapper tests pass separately.

The fixture switch is forwarded to elaboration and included in the HDL cache key.
The wire-level reader, upload controller, JTAG primitive wrappers, and pixel
capture are checked separately. Physical Basys 3 testing on 2026-10-27 verified
JTAG erase/program/readback, a vblank reload of the updated 87-glyph font,
two consecutive uploads advancing generation 1 → 2 → 3, and repeated USB connections retaining font
ready with no loader error. The bitstream is loaded into volatile SRAM; a board
power cycle restores whichever design is stored in configuration flash.

## Flash-loading revision validation (2026-10-27)

The final Basys 3 pin-constrained route passes **148.70 MHz** at the
148.5 MHz target using the isolated corrected timing database and seed 1.
The critical path is **6.72 ns**, from the prepared-row register through
row-address arithmetic and request selection into font BRAM. Setup margin is
only about **0.01 ns**; there are no reported hold violations. This is a
modeled timing result with very little margin, not vendor timing signoff or
physical board validation. The user subsequently confirmed this boot-loading
revision works perfectly on hardware. The live-update revision below requires
its own validation.

The checked artifact is
`build/basys3/vga_uart_1920_1080_font_v2_demo/pipelinec/top/top.bit`, with its
pin-constrained report in the adjacent `open_tools_final.log`. Final mapped
resources are **2,077 LUT2–LUT6**, **1,880 flip-flops**, **one RAMB36E1** for the
font, **three RAMB18E1** for text, **six RAM32M** for the FIFO, and **zero DSPs**.
This run directly generated the as-written final design without the preliminary
throughput sweep; the fixed one-clock RAM latency and explicit controller
registers are retained. The normal build wrapper above performs the additional
preliminary sweep and validates the final report.

The hardware-free capture loads the same serialized image through the header
parser and registered BRAM write path. Eight HDL frames match the independent
1920×1080 pixel reference exactly for the 392-byte undefined-character/Unicode
and editing input. Native checks exercise header bounds, checksum failure,
truncated data, stalled word input, relocated
tables, all eight directory slots, and empty non-ASCII glyph rows. The real
Aseprite `--export v2` output is 4,256 bytes and matches the legacy conversion's
serialized reference image byte for byte.

## Validation of the earlier compiled-in font build

The selected final board-constrained route uses the isolated corrected timing
database described in the hardware audit. With undefined-codepoint fallback,
it reaches **152.81 MHz** at the 148.5 MHz target: a **6.54 ns** critical path
against **6.734 ns**, giving approximately **0.19 ns setup margin**.
There are no reported hold violations.
This is a passing result with modest margin, not comprehensive vendor timing
signoff. The remaining critical path is the prepared-row register through the
final row-address addition and request selection into font BRAM.

| Final mapped resources | Font-v2 renderer |
| --- | ---: |
| LUT2–LUT6 cells | 935 |
| Flip-flops | 862 |
| DSP48E1 | 0 |
| Font RAMB36E1 | 1 |
| Text RAMB18E1 | 3 |
| FIFO RAM32M | 6 |

Compared with the original manual shared loader, this removes six LUTs, adds
four flip-flops, and removes its DSP. The pixel FIFO retains all eight words.
The payload grows by 96 bytes overall: single-word patterns add 352 bytes,
while the overlaid Unicode page saves 256 bytes.

The retained 19 font/reference tests and three UTF-8 tests pass after renaming.
They cover the small-font reservation, all glyph rows,
all kerning pairs, Unicode-page holes, editing around undefined characters,
and forced row-helper stalls. The renamed capture entry point also produces an
exact 1920×1080 reference match for 392 bytes of Unicode/undefined-codepoint
and editing input over eight HDL frames. Before the filename renames, three
1920×1080 HDL captures matched the independent column-major reference
exactly: 968-byte supported mixed text (8 frames), 392-byte undefined-codepoint
and editing text (8 frames), and a full 2,048-character lowercase buffer
(16 frames). Mapped-netlist graph
checks find no unregistered font-read-to-font-address path and no direct
font-read path into the kerning advance/origin registers.

More aggressive routing and a register after the entire row calculation did
not improve the selected route. The prepared-row cut is retained.
These timing results describe
the hardware-verified build before the filename/module renames; no new
physical route is claimed for the renamed source.

The selected source snapshots, checksums, captures, reports, and bitstream are
preserved under `build/banked-hardware-debug/`. The full build/report is in
`build/basys3/shared_notdef_checked/`; the selected frozen bitstream is
`build/banked-hardware-debug/notdef_frozen/top.bit`. Build the renamed source
using the tracked `toolchain/build-font-demo-with-corrected-timing.sh` wrapper described above.
That script selects the diagnostic chipdb;
ordinary builds still use the pinned database with its known coverage gaps.

The preceding format-2 build reached 161.50 MHz and was confirmed stable on
Basys 3 **volatile SRAM at 1080p /148.5 MHz** while displaying
`ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890`, with the eight-word FIFO retained.
That build skipped undefined characters. The fallback revision above was then
loaded into volatile SRAM. Its HDL checks pass, and the user confirmed that
a long run of lowercase letters renders fallback glyphs with normal spacing
and stable text at 1080p /148.5 MHz.
Persistent flash retains the earlier
flickering build. The previous two-word-FIFO shared diagnostic,
which the user confirmed stable, remains available at
`build/banked-hardware-debug/shared_fifo2_frozen/top.bit`.

## Hardware timing audit

The pinned OpenXC7 timing importer uses `CLKARDCLK` and `CLKBWRCLK` in
RAMB36 timing records, while its physical metadata and packer expose the
`L`/`U` clock pins. Importing the actual pinned SDF finds 274 distinct records
with nonexistent clock references across four RAMB36 variants. It also lacks
a DSP48E1 timing variant, despite the font quotient using an unregistered DSP.
The applicable SDF multiplier delay is up to 3.841 ns from A to P.
RAM32M's second input also lacks a setup/hold check.

An isolated diagnostic database corrects the RAMB36 clock references, adds
RAM32M DI2 checks, and imports the multiplier arcs for this particular
unregistered DSP configuration. It is not a general DSP timing model or full
timing signoff. The pinned source is
[OpenXC7's timing generator](https://github.com/openXC7/nextpnr/blob/93b4a52731d006e1504fd6a455a5d820820e080f/himbaechel/uarch/xilinx/gen/xilinx_gen.py).

Rerouting the original shared-loader netlist with the diagnostic model exposes
a 12.41 ns font-ROM → row-byte selection → quotient DSP → font-ROM address
path, versus the 6.734 ns pixel-clock budget. Its modeled logic alone takes
7.76 ns. This is a rerouted netlist, not the exact flashed placement or a
measured silicon limit. It nevertheless exposes a substantial timing deficit
that the earlier apparent pass omitted.

The diagnostic sources, reports, and current board state are preserved in
`build/banked-hardware-debug/`. The small-FIFO result is a working hardware
observation, not proof of an algorithm error in the original FIFO: changing its
depth also changes synthesis and placement/routing.
