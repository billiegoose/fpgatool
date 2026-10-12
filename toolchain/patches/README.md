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
