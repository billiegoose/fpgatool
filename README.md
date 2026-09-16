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
./fpgatool.sh doctor
./fpgatool.sh shell
```

- `build`: design source -> `.bit`
- `load`: existing `.bit` -> volatile FPGA SRAM
- `run`: build a design source, then load it into volatile SRAM
- `program`: existing `.bit` -> persistent board flash

`program` intentionally requires an already-built `.bit` file so a persistent flash
write is always an explicit operation. `doctor` and `shell` do not require a source.
Normal builds keep the underlying Nix/PipelineC/programmer output quiet and save it
as `build.log`, `load.log`, or `program.log` beside the design output. Pass
`--verbose` (or `-v`) to stream the full tool output directly to the terminal.

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
