# pyright: reportInvalidTypeForm=none
# ruff: noqa: F821
# Pypeline initializes annotation-only registers, structs and arrays.
"""Priority-elif lowering regression through native simulation and real VHDL.

Covers the semantic distinction between branch VALUE selection and branch
CLOCK_ENABLE.  A flattened elif nested under a runtime-disabled parent must
still compute ordinary combinational values from raw priority conditions while
using the parent CE only to gate effects inside the selected branch.

Also covers:
  * overlapping, non-equality predicates;
  * a later condition reading a value written only by an earlier branch body
    (the later condition must see the pre-chain value because reaching it means
    the earlier body did not execute);
  * final-else and no-final-else chains;
  * repeated writes to one destination;
  * scalar, struct-field, and static array-element writes.

The debug payload is intentionally emitted on every checked cycle except the sim_finish cycle so cycle-by-cycle
native/VHDL parity covers all observable values below.
"""

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    int8_t,
    uint1_t,
    uint8_t,
    uint16_t,
)
from operators.soft import register_sw_lib_replacements

register_sw_lib_replacements()


@struct
class elif_pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


NUM_CYCLES = 32


@MAIN
def general_elif_priority():
    n: Reg[uint8_t]
    case: uint8_t = n & 7
    enable: uint1_t = (n >> 3) & 1
    signed_value: int8_t = int8_t(n) - 16
    wide: uint16_t = uint16_t(n) * 17
    # The real != and generated truthiness != share the right operand's span.
    truthy: uint1_t = (wide > 0) and (case != 7)
    signed_lt: uint1_t = signed_value < 0
    wide_gt: uint1_t = wide > 255
    sim_assert(truthy == ((n > 0) & (case != 7)))
    sim_assert(signed_lt == (n < 16))
    sim_assert(wide_gt == (n >= 16))

    x: uint8_t = 10
    y: uint8_t = 20
    z: uint8_t = 30
    p: elif_pair_t
    p.a = 40
    p.b = 50
    arr: uint8_t[3]
    arr[0] = 60
    arr[1] = 70
    arr[2] = 80

    # Inner general-elif chain under a runtime parent CE.  When enable=0 the
    # outer else must win even though the inner raw conditions remain defined.
    if enable:
        if case < 3:
            # The next condition reads x.  If execution reaches that condition,
            # this body did not execute, so it must read pre-chain x == 10.
            x = 100 + case
            p.a = 101 + case
        elif (x == 10) & (case < 5):
            y = 110 + case
            arr[1] = 111 + case
        elif (case & 1) != 0:
            z = 120 + case
            p.b = 121 + case
        else:
            x = 130 + case
            arr[2] = 131 + case
    else:
        x = 200 + case
        y = 210 + case
        z = 220 + case
        p.a = 230 + case
        p.b = 240 + case
        arr[0] = 180 + case

    # No final else, repeated destination, same runtime parent CE.
    if enable:
        if case == 0:
            z = z ^ 1
        elif case < 4:
            z = z ^ 2
        elif (case & 2) != 0:
            z = z ^ 4

    if not enable:
        sim_assert(x == 200 + case)
        sim_assert(y == 210 + case)
        sim_assert(p.a == 230 + case)
        sim_assert(p.b == 240 + case)
        sim_assert(arr[0] == 180 + case)
    else:
        if case < 3:
            sim_assert(x == 100 + case)
            sim_assert(p.a == 101 + case)
        elif case < 5:
            sim_assert(x == 10)
            sim_assert(y == 110 + case)
            sim_assert(arr[1] == 111 + case)
        elif (case & 1) != 0:
            sim_assert(
                z == ((120 + case) ^ 4 if (case & 2) != 0 else (120 + case))
            )
            sim_assert(p.b == 121 + case)
        else:
            sim_assert(x == 130 + case)
            sim_assert(arr[2] == 131 + case)

    if n < NUM_CYCLES - 1:
        sim_print(
            f"general_elif_priority n={n} en={enable} case={case} "
            f"x={x} y={y} z={z} pa={p.a} pb={p.b} "
            f"a0={arr[0]} a1={arr[1]} a2={arr[2]} "
            f"truthy={truthy} signed_lt={signed_lt} wide_gt={wide_gt}",
            debug=True,
        )
    if n == NUM_CYCLES - 1:
        sim_finish()
    n += 1
