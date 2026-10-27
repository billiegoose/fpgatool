# Font v2 non-AA renderer

**Timing qualification:** the pinned OpenXC7 timing database is incomplete.
The hardware audit found missing DSP timing and RAMB36 timing arcs referring
to nonexistent clock pins. The passing results below use an isolated corrected
database; normal builds do not yet include those corrections.
The hardware-verified font-v2 build is loaded in volatile SRAM.
Persistent flash still contains the earlier flickering build.

`examples/vga_uart_1920_1080_font_v2_demo.py` is the font-v2 renderer at
148.5 MHz / 1080p. Its capture companion replaces the MMCM with an ideal clock.

```sh
python3 scripts/generate_font_v2.py
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
bash toolchain/build-font-v2.sh
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

Generated header/page-directory constants and BRAM initialization still supply
the prototype. Serial/flash font loading and a serialized header ABI are not
implemented. The format version and page encoding are explicit exporter data;
header constants can currently fold during synthesis. This profile supports
up to 256 global glyph IDs, 32 crop classes, two pattern banks, and 2,048 row
bytes. Crop-class merging/padding for larger fonts remains future work.

## Renderer schedule

The font-v2 demo keeps an **eight-word pixel FIFO**, a one-row mailbox, and a
five-clock glyph initiation interval. It uses seven font reads per glyph.
In steady state, each period overlaps the pattern/placement of glyph `g`,
crop and kerning of `g+1`, and Unicode mapping of `g+2`:

| Clock / state | Port A request | Port B request | Response / register work |
| --- | --- | --- | --- |
| 0 / 3 | Crop(g+1) from registered crop address | Pattern(g) from registered pattern ID | Previous-origin candidate(g) |
| 1 / 4 | Unicode map(g+2) | Older kerning(g+1) | Selected 12-bit crop(g+1), 21-bit pattern(g); forecast post-publication older class |
| 2 / 5 | Hold map(g+2) | Previous kerning(g+1) | Publish(g), mapped ID(g+2), prepared row(g+1), older kerning nibble(g+1) |
| 3 / 7 | Metadata(g+2) from registered glyph ID | Row ID(g+1) from prepared row | Previous kerning nibble(g+1), older step(g+1), ink/byte selector |
| 4 / 6 | Hold metadata(g+2) | Hold row ID(g+1) | Row ID/pending packet(g+1), previous step/older-origin candidate(g+1), metadata and crop-address register(g+2) |

Every dependent ROM request consumes registered data: mapping -> glyph ID,
metadata -> crop address, crop -> selected crop -> prepared row, and row ID ->
pattern ID. No ROM output directly feeds another ROM address. Pattern assembly
is a single [20:0] slice. Each kerning nibble, advance, and origin addition
crosses a separate register boundary. The older lookup moves before
publication: if the pending token is a supported glyph, it uses the current
previous class (which publication will move to older); otherwise it uses the
existing older class. This preserves history through ignored control tokens;
undefined printable codepoints advance history using `.notdef`.
The selected crop and prepared row form two explicit row-arithmetic cuts.

State 5 waits for mailbox space while the map and older-kerning requests,
saved pattern, crop, and metadata stay stable. The row helper may repeatedly capture the same
stable crop there; it never consumes the unrelated map word. Publication
advances class/origin history before constructing previous-kerning requests;
Pypeline forwarding is intentional there. State 6 copies the old current
packet into pending before accepting new metadata and prefetched token tags.
The controller explicitly advances `3 → 4 → 5 → 7 → 6 → 3`; bootstrap is
`1 → 2 → 5 → 7 → 6 → 3`, with invalid packets discarded.

The lookup-to-publication latency is eleven clocks, while the initiation
interval remains five. Text cursors use 12 bits for 2,048 codepoints and their
end/prefetch positions. The existing compositor, row restart/drain behavior,
binary-to-color conversion, and FIFO handshake are retained. Physical timing
and board status for this revision are recorded below after validation.

## Current validation and hardware status

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
using the tracked `toolchain/build-font-v2.sh` wrapper described above.
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
