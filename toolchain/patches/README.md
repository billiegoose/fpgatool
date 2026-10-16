# PipelineC patches

`pypeline-boolop-instance-names.patch` disambiguates compiler-generated BoolOp
truthiness comparisons from source comparisons sharing the same source span.

`pypeline-red2-enhancements.patch` adds priority-preserving lowering for pure
runtime elif chains and software comparison operator lowering. Apply it **after**
the BoolOp patch. The current pair targets upstream
`2fe880d19852b8df0df1aae00f469c8be6fe8ce1`. The previous pair, based on
`d991e1f931a2303e3daa4f6256755f3ab47dd9c3`, remains available at fpgatool commit
`fa94add` for reproducing the original LUT experiments.

Asgard's `scripts/setup_pipelinec.py` consumes this pair through its fpgatool
submodule and verifies patch and compiler file hashes. The RED2 patch is not
automatically applied by fpgatool's board build script. That build retains its
independent PipelineC pin in `toolchain.lock.toml`.

The pair replaces Asgard's former combined `red2-enhancements.patch`; do not
apply that combined patch as well. Updating the fork's default branch does not
update either project's pinned compiler.

`pypeline-register-reannotations.patch` applies after that pair. A later
`r: T = value` must write an existing `Reg[T]`, preserving its stored value on
other clocks. Declaring it again as a combinational local dropped RED2's saved
primitive flag. The patch also rejects an annotation with a conflicting type.
The regression below exercises scalar and struct register re-annotations and
holds their values across disabled cycles. The old compiler fails at cycle 3;
the patched compiler matches all 31 native/VHDL rows and reaches `sim_finish`.

The upstream port drops the old name-resolution compatibility hunks because
upstream already has the resulting lookup order, including support for injected
design parameters. Priority selection, clock-enable gating, and software
comparison changes are retained.

`../tests/check_red2_compiler.py` compares 31 native/VHDL trace rows and requires
both simulations to reach `sim_finish`. It covers overlapping predicates,
disabled parent enables, pre-chain values, aggregate writes, BoolOp instance
names, and signed/mixed-width software comparisons. With NVC installed:

```sh
python toolchain/tests/check_red2_compiler.py \
  --compiler /path/to/enhanced/PipelineC --out /tmp/red2-compiler-check
```

Pass `--nvc-command 'podman run ... nvc'` to use a container with the output
directory mounted at the same absolute path used by the runner.
Alternatively, pass `--ghdl-command 'podman run ... ghdl'`; the runner checks
GHDL's explicit finish marker and the same trace rows.

## Saved-placement Xilinx routing

`openxc7-resume-delay-matrix.patch` restores measured interconnect delays when
nextpnr imports a placed JSON design and routes with `--no-pack --no-place`.
The original Xilinx backend initializes this model in `prePlace()` only;
resuming skips that method and silently uses the fallback formula. The patch
initializes the same model and options in the preplaced `preRoute()` path.
It preserves `-o delay-matrix=off` and cached-matrix options. Circuit logic and
component locations are unchanged.

The opt-in regression maps and places a small counter, then routes its saved
placement with the model enabled and explicitly disabled. Both routes must
complete and meet timing. The enabled test fails on the previous backend
because the resumed route never initializes the measured model.

Inside a shell providing Yosys and the pinned chip database, use the raw
Himbächel executable (not the compatibility wrapper):

```sh
NEXTPNR_RESUME_TEST_BIN=/path/to/bin/nextpnr-himbaechel \
NEXTPNR_RESUME_TEST_CHIPDB=/path/to/xc7a35tcpg236.bin \
python3 tests/test_nextpnr_resume_delay_matrix.py
```

## RAMB36E1 wide SDP writes

`openxc7-sdp72-write-width.patch` configures `WRITE_WIDTH_A_18` on both physical
RAMB18 halves when a RAMB36E1 uses `WRITE_WIDTH_B=72` and leaves `WRITE_WIDTH_A=0`.
The existing writer already handles the corresponding wide-read partner and
RAMB18E1 wide writes, but omitted this RAMB36E1 write case. The missing markers
leave part of the memory at its narrow default despite a legal route.

The opt-in `tests/test_nextpnr_sdp72_write_width.py` synthesizes a 512-by-64-bit
RAM and routes it on the Basys 3 package. It requires A and B write-width markers
on both halves. The previous backend fails the A-marker assertion; the patched
backend passes. The two saved-placement delay-model regressions also pass on
the rebuilt backend.

On Asgard's physical RED2 design, adding the 14 missing configuration bits for
seven affected memories changed a 131-word graph-memory test from 74 mismatches
to zero. This establishes that memory-write correction; the complete RED2
application replay still requires separate verification.

```sh
NEXTPNR_RESUME_TEST_BIN=/path/to/bin/nextpnr-himbaechel \
NEXTPNR_RESUME_TEST_CHIPDB=/path/to/xc7a35tcpg236.bin \
python3 tests/test_nextpnr_sdp72_write_width.py
```
# BUFG route-through FASM completion

The compatibility front-end also runs `../compat/complete-bufg-fasm.py` after
FASM export. The pinned router can traverse unused BUFGCTRL I0-to-O connections
while routing ordinary data. Its FASM writer emits their routing but omits the
buffer configuration because there is no placed BUFG cell. A routed Basys 3
RED2 image consequently lost a graph-RAM address bit: its low-word writes
aliased addresses separated by 16. The same image worked after enabling the
13 implicit buffers, with no HDL, placement or routing changes.

The helper emits the same static I0 configuration as an ordinary BUFG, leaves
placed/gated buffers unchanged, and rejects unqualified I1 or control-pin modes.
It produces a hash-stamped report of every added feature. This is an exporter
compatibility correction; the cached backend and chip database remain unchanged.

