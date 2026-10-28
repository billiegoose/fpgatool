"""Reusable font-v2 hardware: glyph rows, binary loading, and BRAM storage.

read_glyph_row is the renderer interface. The caller owns memories, scheduling,
compositing and physical I/O. See docs/font-v2-module.md for the cycle contract.
"""
