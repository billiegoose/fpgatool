# fpgatool

`fpgatool` is a thin host-side wrapper around a reproducible FPGA build environment.
The build runs under Podman + a pinned Nix/OpenXC7 toolchain; programming stays on
the host so USB/JTAG passthrough is not part of the container contract.

The first supported vertical slice is PipelineC/OpenXC7 -> Digilent Basys 3 ->
`openFPGALoader`.

## Quick start

With Podman and `openFPGALoader` installed, a bare invocation prints usage and
does not touch hardware:

```sh
./fpgatool.sh
```

Build and immediately run a design with:

```sh
./fpgatool.sh run examples/blink.py
```

The default board is `basys3`; spell it out with `--board basys3` when useful.
`load` writes a bitstream to **volatile SRAM** and disappears when the FPGA loses
power. `program` writes a bitstream to the board's persistent flash using
`openFPGALoader -f`, so it survives power cycling.

The first build fetches/builds the pinned OpenXC7 stack and generates the Basys 3
nextpnr chip database. The Podman Nix image is digest-pinned, and the Nix store is
retained in the named volume `fpgatool-nix`, so later builds reuse it. If a clean
sibling `../PipelineC` checkout is already at the exact pinned revision, fpgatool
reuses it read-only instead of cloning a duplicate; otherwise it creates a managed
checkout under `.fpgatool/cache/`.

Commands are deliberately literal:

```sh
./fpgatool.sh build examples/blink.py
./fpgatool.sh load build/basys3/blink/blink.bit
./fpgatool.sh run examples/blink.py
./fpgatool.sh program build/basys3/blink/blink.bit
./fpgatool.sh program-data assets.bin
./fpgatool.sh program-data assets.bin --offset 0x230000
./fpgatool.sh doctor
./fpgatool.sh shell
```

- `build`: design source -> `.bit`
- `load`: existing `.bit` -> volatile FPGA SRAM
- `run`: build a design source, then load it into volatile SRAM
- `program`: existing `.bit` -> persistent board flash
- `program-data`: raw binary -> verified user-data area in configuration flash; defaults to `0x220000` on Basys 3

`program` intentionally requires an already-built `.bit` file so a persistent flash
write is always an explicit operation. `doctor` and `shell` do not require a source.

On Basys 3, the XC7A35T full configuration payload is fixed at `0x21728c` bytes.
The flash programmer erases through the containing 64 KiB block, so fpgatool reserves
`0x000000..0x21ffff` for FPGA configuration and treats `0x220000..0x3fffff`
as user data. `program-data` refuses writes below `0x220000` or past the 4 MiB end
of flash, passes the raw file to openFPGALoader with an explicit offset, and enables
readback verification. Writes may erase whole 64 KiB blocks touched by the requested
range, so unrelated data sharing those blocks should be packed together.
Normal builds keep the underlying Nix/PipelineC/programmer output quiet and save it
as `build.log`, `load.log`, or `program.log` beside the design output. Pass
`--verbose` (or `-v`) to stream the full tool output directly to the terminal.

## VGA simulation

Launch a live VGA monitor with no FPGA attached:

```sh
./fpgatool.sh sim examples/vga_test_bars.py
```

The default backend generates the design's as-written VHDL, optimizes it with
GHDL/Yosys, and runs the resulting hardware model with Verilator. The bundled
MIT-licensed [vga-monitor-sim](https://github.com/DFiantWorks/vga-monitor-sim)
receiver reconstructs images from the actual Basys 3 RGB and sync outputs and
opens an ffplay window. Simulation continues until you close the window (or
press **Q**, **Escape**, or **Ctrl+C**). The 640×480 test design runs at about
5 frames per second on the development machine. This is simulated hardware
speed, independent of the VGA timing's nominal refresh rate.

The first launch compiles the model; unchanged designs reuse a cached binary.
Changes to local Python sources, compiler patches, toolchain pins, monitor code,
or host compiler versions invalidate the cache. Cached launches do not need
Podman running. Compilation uses the existing pinned Podman/Nix environment;
host dependencies are Python 3.11+, Git, Verilator, a C++ compiler, and Make.
Live viewing also requires ffplay (included with FFmpeg). On macOS:

```sh
brew install verilator ffmpeg
```

Save screenshots without opening a window, or limit a live run:

```sh
./fpgatool.sh sim examples/vga_test_bars.py --no-open --screenshot build/bars.png
./fpgatool.sh sim examples/vga_test_bars.py --no-open --frames 2
./fpgatool.sh sim examples/vga_test_bars.py --frames 60
```

`--no-open` captures one frame by default. `--frames N` stops after N received
frames; `--cycles N` limits input clock cycles and fails if the requested capture
cannot finish. RGB444 expands to RGB888 (`channel * 17`). The latest frame and
capture metadata are saved in `build/basys3/<design>/sim/frame.png` and
`capture.json`; headless runs also save numbered frames. `--screenshot PATH`
saves the last frame there when the run ends. Receiver and viewer diagnostics
are in the same directory; compilation logs are in `.fpgatool/cache/hdl-sim/`.

The compiled backend currently supports a single input clock and the upstream
monitor's standard 640×480, 800×600, 1024×768, 1280×960, and 1920×1080 timings. External
inputs default to zero; Python simulation hooks do not execute in the compiled
model. Designs using MMCM primitives, multiple clocks, or other VGA timings can
use the native Python backend:

```sh
./fpgatool.sh sim examples/vga_800_600_test_bars.py --sim-backend python
./fpgatool.sh sim examples/vga_1920_1080_test_bars.py --sim-backend python
```

The Python backend opens a browser monitor and captures one frame by default,
then stays open until Ctrl+C. It can take several minutes for a 640×480 capture.
It needs only Python, Git, and `patch`, and supports ideal MMCM clock/lock models
and design simulation hooks. `--vga-mode` is available for this backend when
timing cannot be discovered from `make_vga_timing`. Both paths follow explicit
registers rather than synthesis-selected pipeline placement; neither models
analog VGA or clock jitter.

For Python image comparisons, `simulation.vga.VgaMonitor.sample(r, g, b, hs, vs)`
accepts one sample per pixel clock and returns a complete `Frame`. `Frame.rgb`
is a row-major RGB byte buffer; `Frame.pixel(x, y)` and `Frame.save(path)` provide
pixel access and dependency-free PNG export.

### 1920×1080 UART text demo

`examples/vga_uart_1920_1080_demo.py` receives 115200-baud 8-N-1 serial
input on the Basys 3 USB-UART bridge and renders RED2 text at 1920×1080,
60 Hz. It uses the hardware-verified 100 → 135 → 148.5 MHz MMCM chain:

```sh
./fpgatool.sh build examples/vga_uart_1920_1080_demo.py --comb
./fpgatool.sh sim examples/vga_uart_1920_1080_capture.py --no-open \
  --uart-file assets/red2-readme-example.txt --frames 3 \
  --screenshot build/vga_uart_readme_1080.png
```

The design supplies its pipeline registers explicitly; `--comb` preserves
that pipeline. The final pin-constrained route must still meet 148.5 MHz.

The renderer stores incoming UART bytes in an editable 8 KiB buffer,
including LF. It snapshots the committed byte count once per frame and replays
the same byte span for every glyph scanline. LF advances to the next text line;
CR and unsupported bytes are skipped. Text starts at (5, 2), with a 5-pixel
left/right and 2-pixel top/bottom margin around the entire screen. It uses
native font pixels and pair kerning, and wraps before the right margin. UART
TX stays idle. Backspace (`08`) and Delete (`7F`) remove the last buffered
byte, including a newline; the next byte replaces it. Backspace at an empty
buffer does nothing and can free space in a full buffer. The demo does not
scroll. Edits are reflected by the next frame; removed BRAM bytes are zeroed
so an in-progress frame cannot reread deleted characters.

Font storage is row-major and dictionary-compressed. The font has 253 unique
21-bit patterns, including blank at dictionary entry 0. Each pattern occupies
three little-endian bytes, followed by 1,253 cropped row indices: 759 + 1,253 =
2,012 bytes. Both tables share one 1024×16-bit dual-port block ROM. Metadata
base addresses point into the row-index byte region. A pattern occupies two
adjacent sixteen-bit words; both ports read them together, then a byte-alignment
shift extracts the 21 pixels. The 128×43-bit glyph metadata stores width, top_y,
cropped height, base byte address, validity, backtracking guard, and separate
six-bit left/right kerning class IDs. Scanlines outside the cropped height
supply blank ink without changing placement; spaces have zero stored rows.
Kerning uses 55 left classes (identical adjustment rows) and 51 right classes
(identical adjustment columns). The generated table has 55×51 four-bit entries;
the hardware pads to a 64-column stride in a 4096×4-bit dual-port ROM, allowing
addressing as `(left_class << 6) | right_class`. Class mappings share the
metadata read, so they require no separate block RAM. Font generation verifies
every supported ASCII pair retains exactly the original adjustment. A 64-bit
compositor ORs each incoming row into unfinished ink and emits only pixels that
no future glyph can affect. The generated metadata retains a backtracking guard;
all guards are zero with the current nonnegative pair advances.

The loader remembers the two previous supported glyphs' left classes, widths,
and absolute origins. It places each new glyph at the maximum origin required by
both pair advances, preserving spacing through tucked punctuation such as `P.O.`
and `F.T`. Two read ports use the same kerning ROM. The font loader registers
the cropped byte address, reads its row ID, registers the two dictionary-word
addresses, then reads and aligns the pattern. Kerning and origin arithmetic run
in parallel. The next supported character lookup starts when the current row is
published; publication waits for mailbox space. This preserves six clocks per
glyph despite the added dictionary-address stage. UART bytes are prefetched
throughout lookup, with newline/end/unsupported-byte boundaries handled
separately. History starts empty for each scanline replay at the current text
line's first byte, so LF, wrapping, and backspace retain their behavior. There
is no placement cache. Font generation exhaustively checks every four-glyph
combination to prove two-glyph history is sufficient at spacing 4; an
incompatible font is rejected before updating the ROM constants.

Eight settled pixels are mapped to four-bit palette indices and packed into
one 32-bit FIFO word. The circular FIFO has eight memory words; including its
FWFT output word and consumer shift register, it stores at most 80 upcoming
pixels. VGA consumes one index per active clock. There is no framebuffer or
full-scanline pixel buffer. The current palette maps 0 to black and 1 to white.

VGA timing requests the next row during horizontal blanking. Blanking first
drains any stale FIFO words, then starts the next row and prefills the FIFO.
If a row underflows, remaining pixels are background and the next row starts
fresh; timing never stalls. A sticky underflow fault lights the seven-segment
decimal point.

`examples/vga_uart_1920_1080_capture.py` supplies an ideal 148.5 MHz clock to
the same UART/video core used by the board demo, since the compiled backend
does not simulate MMCMs. `--uart-file` drives actual 8-N-1 serial bits into
`RsRx`; `--uart-baud` defaults to 115200. Three frames allow the complete
README sample to arrive and a stable frame to be captured.

The checked-in font data comes directly from raw Aseprite slices, independent
of R2BF. Regenerate the row ROMs, column data for verification, and README
sample from the adjacent `red2-font` checkout (requires Aseprite and its Pillow
environment):

```sh
../red2-font/.venv/bin/python scripts/generate_uart_font.py
```

Capture verification uses an independent renderer based on the column-major
font data, rather than the streaming compositor:

```sh
../red2-font/.venv/bin/python scripts/verify_uart_pixels.py \
  build/vga_uart_readme_1080.png assets/red2-readme-example.txt
```

The final Basys 3 route meets 148.5 MHz at 168.27 MHz. It uses two RAMB36 and
two RAMB18 blocks (13.5 KiB, 6% of the board's block RAM), down from 15.75 KiB
before combining the font ROMs, 22.5 KiB with row compression alone, and
29.25 KiB originally. Font row storage falls from five RAMB18 blocks to one;
kerning falls from two RAMB36
blocks to one RAMB18. Compiled HDL captures match the 335-byte README sample, a
609-byte punctuation/wrapping/backspace stress input, and a 1,579-byte
all-glyph/cropped-row/dense-kerning input exactly. The build command also
checks the final pin-constrained timing report before publishing its bitstream;
a failing final route is rejected even when nextpnr exits successfully.

The board demo also exposes UART diagnostics from the same receiver used by
the renderer. The seven-segment display reads `CCBB`: received-byte count modulo
256 followed by the last received byte, both hexadecimal. Sending `A` after
configuration should show `0141`; LF is `0A`, CR is `0D`. Every valid UART byte
counts, including bytes ignored by the text layout. Indicators reset on FPGA
configuration; activity and write indicators stay lit until then.

| LEDs | Meaning |
| --- | --- |
| LD0–LD7 | Last received byte, bit 0 through bit 7 |
| LD8 | Pixel clock locked |
| LD9 | Pixel-domain heartbeat |
| LD10 | Synchronized RX level (normally lit while idle) |
| LD11 | RX has gone low at least once |
| LD12 | At least one valid UART byte received |
| LD13 | Toggles on every valid byte |
| LD14 | At least one byte committed to the text buffer |
| LD15 | Text buffer full (8,192 bytes) |

With LD11 off, check the host port and serial connection. LD11 on with LD12 off
means activity reached RX but no valid byte was decoded; check 115200 baud,
8-N-1, and disabled flow control. LD12 on with LD14 off means bytes arrived but
have not been committed to the text buffer. LD15 means the buffer is full;
Backspace can free space, or reloading the configuration starts a fresh screen.
The demo does not scroll or provide a clear-screen command.

To type into the 1080p UART demo (`examples/vga_uart_1920_1080_demo.py`), connect
with `tio`:

```sh
tio --map OCRNL,OLTU /dev/cu.usbserial-2101837357871
```

`OCRNL` sends Enter as a newline, and `OLTU` converts lowercase input to
uppercase. Exit with Ctrl-T followed by Q. Replace the port with the board's
current UART device if needed.

Send hardware test input with a single connection that configures 115200 baud,
8-N-1 and no flow control before writing. This avoids relying on serial settings
surviving a port close/reopen. The sender uses Python's standard library:

```sh
python3 scripts/send_uart.py --port /dev/cu.usbserial-2101837357871 --text ABC --newline
python3 scripts/send_uart.py --port /dev/cu.usbserial-2101837357871 --file assets/red2-readme-example.txt
```

After a fresh configuration, the first command should display `040A` on the
seven-segment display and `ABC` on VGA. Replace the port with the board's current
UART device. Add `--delay-ms 10` to compare paced bytes against the default
continuous stream while diagnosing reception.

## Example structure

Top-level `examples/*.py` files are complete board-facing designs: they own `@MAIN` entry points and physical board interfaces. Reusable, board-agnostic hardware functions live under `examples/hardware/` and contain neither `@MAIN` declarations nor `board.*` imports. `examples/kitchen_sink_demo.py` demonstrates composition by combining the LED/seven-segment chaser, UART echo, VGA test bars, and mouse cursor blocks in one design.

The kitchen-sink demo outputs 1920x1080 at 60 Hz using the same 148.5 MHz
MMCM chain as the standalone 1080p example. Video and PS/2 run in that pixel
domain; buttons, LEDs, seven-segment display, and UART remain at 100 MHz.
`make_ps2_mouse(clock_mhz, frame_width, frame_height)` scales the protocol
timeouts and mouse bounds, while `make_mouse_cursor(spec)` renders across the
full frame. The standalone mouse demo retains its 100 MHz, 640x480 defaults.
The cursor renderer has two pipeline stages that delay RGB and sync together;
debounced button levels are registered before driving the chaser logic.

All VGA test-bar examples use the same `hardware.vga_test_bars` factory:

```python
vga_timing = make_vga_timing(spec)
test_bars = make_vga_test_bars(spec)  # spec: VgaTimingSpec
```

Call `test_bars(sig)` on the timing generator's output. The factory derives
frame dimensions and constant bar thresholds from `spec`; every mode uses the
same corner markers, edge ticks, and center X spanning a square to reveal
aspect-ratio distortion. The seven bars differ in
width by at most one pixel, with blanking rendered black and sync passed through.

### 800x600 VGA test bars

```sh
./fpgatool.sh build examples/vga_800_600_test_bars.py
```

This example uses Pypeline's `VGA_800_600` timing preset: a 40 MHz pixel clock
and 1056x628 total pixels, giving approximately 60.32 Hz refresh. A single
`MmcmStage(8, 1, 20)` generates 40 MHz from the board's 100 MHz oscillator
with an 800 MHz VCO. The pixel domain waits for synchronized MMCM lock before
advancing its timing counters, using the same clock interface as the 1080p example.

### 1920x1080 VGA test bars

```sh
./fpgatool.sh build examples/vga_1920_1080_test_bars.py
```

This Pypeline design runs at 148.5 MHz for 1920x1080 at 60 Hz (2200x1125 total
pixels). `@MAIN(148.5)` declares a clock domain; it does not synthesize a clock
from the board oscillator. The example configures and calls its clock generator from
a 100 MHz MAIN and wires its output using Pypeline's `make_clock()` declaration:

```python
_pixel_clock_generator = make_mmcm_clock(100.0, MmcmStage(27, 4, 5), MmcmStage(11, 2, 5))
pixel_clock: Wire[uint1_t] = make_clock(_pixel_clock_generator.output_mhz)
pixel_locked: AsyncWire[uint1_t]

@MAIN(100.0)
def vga_pixel_clock():
    signals = _pixel_clock_generator(0)
    pixel_clock = signals.clock
    pixel_locked = signals.locked
```

The pixel MAIN calls `synchronize_clock_lock(pixel_locked)` before advancing
its timing counters. `AsyncWire` explicitly permits the asynchronous connection;
the synchronizer provides asynchronous clear and a two-edge release in the pixel
domain. `AsyncWire` itself inserts no synchronization.

`examples/hardware/xilinx7_clock.py` provides the reusable `make_mmcm_clock()`
factory and `MmcmStage` configuration. The example supplies the
hardware-verified integer chain: 100 MHz × 27 / 4 / 5 = 135 MHz, then 135 MHz ×
11 / 2 / 5 = 148.5 MHz. The VCOs run at 675 and 742.5 MHz, and the second MMCM
waits for the first to lock. Configuration checks target Artix-7 -1 limits;
fractional counters and analog clock/lock simulation are not provided. The
input frequency supplied to the factory must match its calling MAIN's clock.
The ratios follow the [7-series clocking guide](https://www.amd.com/content/dam/xilinx/support/documents/user_guides/ug472_7Series_Clocking.pdf).

Vendor HDL is confined to ordinary `vhdl()` hardware functions. The design no
longer rewrites generated VHDL or changes the compiler's pin-constraint setting.
A small compiler compatibility patch exposes PipelineC's existing asynchronous
wire support as `AsyncWire` and accepts clock primitives that have no interior
timing paths. The build applies it to disposable module copies, leaving the
pinned checkout unchanged. Existing nextpnr MMCM patches are unchanged.

The build also applies `pipelinec-timing-snapshot-memory.patch` to its disposable
`AUTO_PIPELINE.py` copy. It makes Python deep copies use `TimingParams`' existing
copy method, so timing snapshots retain independent pipeline choices while
sharing the compiled logic graph. This avoids duplicating that large graph
after a successful timing check, which can exhaust an 8 GiB build VM.

The resulting bitstream is `build/basys3/vga_1920_1080_test_bars/vga_1920_1080_test_bars.bit`.
Both the original final-hook implementation (saved in commit `d0739af`) and the
native clock abstraction have been hardware-verified on Basys 3. Building does
not program the board.

## Basys 3 peripheral coverage

The Basys 3 support is intentionally built out as small, composable Pypeline modules so
examples can double as reference designs for individual board features.

| Feature | Status / notes |
| --- | --- |
| 100 MHz oscillator | Supported; most examples use it directly. The 1920x1080 VGA example derives a 148.5 MHz pixel clock using two MMCMs. |
| 16 slide switches | Supported. |
| 16 user LEDs | Supported. |
| 5 pushbuttons | Supported. |
| 4-digit seven-segment display | Supported, including multiplexed scanning in `examples/led_chaser.py`. |
| 12-bit VGA output | Supported; `examples/vga_test_bars.py` provides the hardware-verified 640x480 bars/geometry diagnostic, while `examples/mouse_demo.py` exercises the PS/2 mouse cursor independently. |
| USB-UART bridge | Supported at 115200 baud by the reusable UART transport example. |
| USB HID mouse through the PIC24 PS/2 bridge | Supported, including three buttons and IntelliMouse wheel negotiation. |
| USB HID keyboard through the PIC24 PS/2 bridge | Deferred. The bridge recognized tested keyboards at attach time but did not forward keypress scan codes; see the investigation note below. |
| 32-Mbit QSPI configuration flash | SPI, dual-output SPI, and QSPI transports live in `examples/hardware/SPI.py`, `DSPI.py`, and `QSPI.py`, with shared protocol constants in `flash.py`. The example matrix makes the bus-width progression explicit: `flash_spi_read.py` and `flash_spi_write.py` use ordinary 1-1-1 SPI, `flash_dspi_read.py` uses 1-1-2 Dual Output Read, and `flash_qspi_read.py` plus `flash_qspi_write.py` use 1-1-4 reads and quad page program. Quad reads/writes and persistence are hardware-verified on Basys 3. |
| Digital Pmod connectors | Planned; deliberately left out of the built-in-peripheral pass. |

### Flash examples

The flash examples intentionally keep the application behavior parallel so the transport differences are easy to compare:

- `examples/flash_spi_read.py` — single-bit SPI reads.
- `examples/flash_spi_write.py` — single-bit SPI read/erase/program persistence.
- `examples/flash_dspi_read.py` — Dual Output Read (`0x3B`): command/address remain serial and payload data arrives two bits per clock. Program operations on this transport remain ordinary serial SPI, so there is no redundant `flash_dspi_write.py` demo.
- `examples/flash_qspi_read.py` — Quad Output Read (`0x6B`), four payload bits per clock.
- `examples/flash_qspi_write.py` — quad reads plus Quad Page Program (`0x32`).

The three read demos consume the same raw text directly from the reserved flash sector. The first erased `0xFF` byte marks end-of-text; no image header or preprocessing utility is required. ASCII lower-case is rendered as upper-case on the seven-segment display, while tabs/newlines render as spaces.

### Flash persistent-number demo

Build and persistently program the demo once:

```sh
./fpgatool.sh build examples/flash_qspi_write.py --comb
./fpgatool.sh program build/basys3/qspi_flash_rw/qspi_flash_rw.bit
```

After the board boots, BTNU increments the four-digit decimal value, BTND decrements it, and BTNC saves it to the reserved final 64 KiB flash block. The buttons use the shared synchronized/debounced `examples/hardware/buttons.py` input block. LD15 means QUAD mode is enabled, LD12 proves a four-lane read payload has occurred, LD10 proves a four-lane page-program payload has occurred, LD14 means a valid checked record is present, LD13 reports a save/readback error, and LD11 is flash busy.

Persistence is hardware-verified on Basys 3: choose a recognizable number, press BTNC, wait for LD11 to turn off, and then power-cycle the board without running `fpgatool program` again. The same number is restored at boot. Cold-boot recovery and QSPI transactions are centralized in `examples/hardware/QSPI.py`; the demo keeps only its small application-specific record state machine.

### Flash read demos

The SPI, DSPI, and QSPI read demos all display four characters at a time from raw text stored at flash offset `0x3e0000`. Program an ordinary text file directly; `program-data` erases the touched 64 KiB flash block, so the erased `0xFF` byte immediately after the file naturally terminates the document:

```sh
./fpgatool.sh program-data book.txt --offset 0x3e0000
```

Then build/load any of `examples/flash_spi_read.py`, `examples/flash_dspi_read.py`, or `examples/flash_qspi_read.py` to compare 1-bit, 2-bit, and 4-bit payload reads over the same content. Text may be at most 65,535 bytes so one erased terminator byte remains in the reserved sector.
| XADC / analog Pmod connector | Planned. |
| JTAG user logic | Optional future infrastructure. The physical JTAG port is primarily for configuration/debug, but 7-series `BSCANE2` can expose USER scan chains to fabric for a private host<->FPGA control/debug channel. |
| USB thumb-drive programming | Board configuration facility handled by the PIC24, not a normal user-fabric mass-storage peripheral. |

### Keyboard investigation (deferred)

The Basys 3 USB-HID connector is mediated by the board's PIC24, which translates supported USB mice/keyboards into PS/2-style `PS2Clk`/`PS2Data` signals for the FPGA. Keyboard support was investigated in September 2026 and deliberately tabled after the bridge failed to forward keypress traffic from the keyboards available for testing.

What was verified:

- The existing mouse path remains hardware-proven, including buttons and IntelliMouse wheel negotiation.
- A ZSA Moonlander produced idle-high PS/2 clock/data but no FPGA-visible traffic when keys were pressed.
- A Microsoft USB keyboard produced a valid `0xAA` PS/2 BAT/self-test byte on reconnect, proving that the PIC24 recognized the device and that the FPGA receiver could decode a real keyboard frame. However, pressing keys produced **zero PS/2 clock edges and zero PS/2 data transitions** at the FPGA pins.
- Sending PS/2 `F4` (Enable Scanning) to that Microsoft keyboard received the expected `0xFA` acknowledgement, but still produced no subsequent keypress scan codes.
- Digilent's official Basys 3 Keyboard Demo (Vivado 2018.2 release `v2018.2-3`) was loaded as an independent A/B test. It also produced no keyboard output with the same Microsoft keyboard. Digilent's reference receiver is passive and expects the PIC24 bridge to emit scan codes directly.

The practical conclusion is that this was not shown to be a Pypeline/fpgatool receiver bug. Future keyboard work should start with a known-compatible, simple USB HID boot keyboard and the passive receive model used by Digilent's reference design, rather than restoring the abandoned dynamic mouse/keyboard detector experiment.

Suggested remaining Basys 3 work, in order:

1. Add dual- and quad-SPI data paths to the generic flash controller and measure the throughput improvement over the currently hardware-proven single-SPI path.
2. Pmod helpers and representative common Pmod peripherals.
3. XADC support.
4. Optional `BSCANE2` JTAG-user bridge for a low-speed debug/control channel that leaves UART free for the application.

With the generic flash API now in place, the next flash-specific goal is dual/quad transfer support; the remaining board work is mostly expansion/debug I/O. Keyboard support is tabled pending a known-compatible USB HID keyboard or a better understanding of the PIC24 bridge's compatibility limits.

## Boundaries

- `fpgatool.py`: host orchestration only; Python standard library.
- `boards/*.toml`: board/backend/programmer facts.
- `toolchain/flake.nix`: reproducible synthesis dependencies.
- `toolchain/build-pipelinec.sh`: adapter from fpgatool's build contract to PipelineC.
- `openFPGALoader`: native host programmer; never runs in the container.

PipelineC and OpenXC7 are pinned independently. See `toolchain.lock.toml`.

This intentionally starts with one proven implementation per boundary rather than
pretending untested boards and synthesis backends are supported. More board
profiles and programmers can be added without changing the one-command UX.
