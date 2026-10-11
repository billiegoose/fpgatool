# PipelineC patches

`pypeline-boolop-instance-names.patch` disambiguates compiler-generated BoolOp
truthiness comparisons from source comparisons sharing the same source span.

`pypeline-red2-enhancements.patch` adds priority-preserving lowering for pure
runtime elif chains and software comparison operator lowering. Apply it **after**
the BoolOp patch: the two patches together reproduce Asgard's tested enhanced
compiler based on `d991e1f931a2303e3daa4f6256755f3ab47dd9c3`.

Asgard's `scripts/setup_pipelinec.py` consumes this pair through its fpgatool
submodule and verifies patch and compiler file hashes. The RED2 patch is not
automatically applied by fpgatool's board build script. That build retains its
independent PipelineC pin in `toolchain.lock.toml`.

The pair replaces Asgard's former combined `red2-enhancements.patch`; do not
apply that combined patch as well. Updating the fork's default branch does not
update either project's pinned compiler. Port and validate these patches before
changing the pins; the RED2 patch does not apply directly to upstream
`2fe880d19852b8df0df1aae00f469c8be6fe8ce1`.
