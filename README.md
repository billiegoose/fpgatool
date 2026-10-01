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

## Example structure

Top-level `examples/*.py` files are complete board-facing designs: they own `@MAIN` entry points and physical board interfaces. Reusable, board-agnostic hardware functions live under `examples/hardware/` and contain neither `@MAIN` declarations nor `board.*` imports. `examples/kitchen_sink_demo.py` demonstrates composition by combining the LED/seven-segment chaser, UART echo, VGA test bars, and mouse cursor blocks in one design.

### 1920x1080 VGA test bars

```sh
./fpgatool.sh build examples/vga_1920_1080_test_bars.py
```

This Pypeline design runs at 148.5 MHz for 1920x1080 at 60 Hz (2200x1125 total
pixels). `@MAIN(148.5)` declares a clock domain; it does not synthesize a clock
from the board oscillator. The example imports `fpgatool_board.basys3.clock_148p5`
to bind that domain to the physical 100 MHz clock on W5 using a synthesis-final
board hook, just like the PS/2 and QSPI boundary adapters.

The adapter uses two MMCMs with integer counters: 100 MHz × 27 / 4 / 5 = 135 MHz,
then 135 MHz × 11 / 2 / 5 = 148.5 MHz. This keeps the pinned OpenXC7 backend on
its tested integer-counter path; the VCOs run at 675 and 742.5 MHz. The second
stage waits for the first to lock, and the pixel process stays disabled until
the second stage's lock is synchronized. The hook supports one 148.5 MHz MAIN.
The clock ratios follow the [7-series clocking guide](https://www.amd.com/content/dam/xilinx/support/documents/user_guides/ug472_7Series_Clocking.pdf).

The resulting bitstream is `build/basys3/vga_1920_1080_test_bars/vga_1920_1080_test_bars.bit`.
Building does not program the board; display operation needs a hardware check.

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
