"""Prove that two previous glyphs dominate every older pair constraint."""


def verify_two_glyph_history(advances, codes):
    rows = {code: advances[code << 7:(code + 1) << 7] for code in codes}
    for a in codes:
        row_a = rows[a]
        for b in codes:
            row_b = rows[b]
            xb = row_a[b]
            for c in codes:
                row_c = rows[c]
                xc = max(row_a[c], xb + row_b[c])
                for d in codes:
                    recent = max(xb + row_b[d], xc + row_c[d])
                    if row_a[d] > recent:
                        specimen = ''.join(map(chr, (a, b, c, d)))
                        raise ValueError(
                            f'Two-glyph history is insufficient for {specimen!r}: '
                            f'older bound {row_a[d]} exceeds recent bound {recent}')
    # For a longer line, any old glyph and the final two predecessors form
    # one of these subsequences. Intervening constraints only raise origins.
    return len(codes) ** 4
