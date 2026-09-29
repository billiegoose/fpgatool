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

Top-level `examples/*.py` files are complete board-facing designs: they own `@MAIN(100.0)` entry points and physical board interfaces. Reusable, board-agnostic hardware functions live under `examples/hardware/` and contain neither `@MAIN` declarations nor `board.*` imports. `examples/kitchen_sink_demo.py` demonstrates composition by combining the LED/seven-segment chaser, UART echo, VGA test bars, and mouse cursor blocks in one design.

## Basys 3 peripheral coverage

The Basys 3 support is intentionally built out as small, composable Pypeline modules so
examples can double as reference designs for individual board features.

| Feature | Status / notes |
| --- | --- |
| 100 MHz oscillator | Supported; the current Basys 3 examples use the board clock directly. |
| 16 slide switches | Supported. |
| 16 user LEDs | Supported. |
| 5 pushbuttons | Supported. |
| 4-digit seven-segment display | Supported, including multiplexed scanning in `examples/led_chaser.py`. |
| 12-bit VGA output | Supported; `examples/vga_test_bars.py` provides the hardware-verified 640x480 bars/geometry diagnostic, while `examples/mouse_demo.py` exercises the PS/2 mouse cursor independently. |
| USB-UART bridge | Supported at 115200 baud by the reusable UART transport example. |
| USB HID mouse through the PIC24 PS/2 bridge | Supported, including three buttons and IntelliMouse wheel negotiation. |
| USB HID keyboard through the PIC24 PS/2 bridge | Deferred. The bridge recognized tested keyboards at attach time but did not forward keypress scan codes; see the investigation note below. |
| 32-Mbit QSPI configuration flash | Read and write support hardware-verified. `examples/qspi_flash_id.py` reads JEDEC `01 02 15` with command `0x9F` through the Artix-7 `STARTUPE2` CCLK path. `examples/qspi_flash_rw.py` reserves the final 64 KiB block (`0x3F0000..0x3FFFFF`), loads a checked four-digit BCD value at boot, changes it with BTNU/BTND, and saves it with BTNC using WREN + 64 KiB erase + page program + status polling + readback verification. The Himbächel build meets the 100 MHz target, and physical Basys 3 testing verified save/readback plus restoration after a full power cycle. |
| Digital Pmod connectors | Planned; deliberately left out of the built-in-peripheral pass. |

### QSPI persistent-number demo

Build and persistently program the demo once:

```sh
./fpgatool.sh build examples/qspi_flash_rw.py --comb
./fpgatool.sh program build/basys3/qspi_flash_rw/qspi_flash_rw.bit
```

After the board boots, BTNU increments the four-digit decimal value, BTND decrements it, and BTNC saves it to the reserved final 64 KiB flash block. LD15 is on while the flash controller is busy, LD14 means a valid checked record is present, and LD13 means the most recent save verification failed. Each BTNC save erases that reserved block before programming the new four-byte record, so avoid repeatedly saving unnecessarily.

Persistence is hardware-verified on Basys 3: choose a recognizable number, press BTNC, wait for LD15 to turn off, and then power-cycle the board without running `fpgatool program` again. The same number is restored at boot. The verified cold-boot path primes STARTUPE2 CCLK ownership, normalizes the flash back to single-SPI command mode, and then reads the checked record from the reserved block.
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

1. Generalize the now-demonstrated QSPI read/erase/program path into reusable arbitrary-address asset helpers for fonts, icons, sprites, lookup tables, and other persistent resources.
2. Pmod helpers and representative common Pmod peripherals.
3. XADC support.
4. Optional `BSCANE2` JTAG-user bridge for a low-speed debug/control channel that leaves UART free for the application.

After QSPI flash, the remaining planned work is mostly expansion/debug I/O. Keyboard support is tabled pending a known-compatible USB HID keyboard or a better understanding of the PIC24 bridge's compatibility limits.

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
