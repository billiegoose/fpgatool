# pyright: reportInvalidTypeForm=none
"""Reusable board-agnostic LED and seven-segment chaser hardware."""

from pypeline import *


@struct
class led_chaser_t(NamedTuple):
    ld0: uint1_t
    ld1: uint1_t
    ld2: uint1_t
    ld3: uint1_t
    ld4: uint1_t
    ld5: uint1_t
    ld6: uint1_t
    ld7: uint1_t
    ld8: uint1_t
    ld9: uint1_t
    ld10: uint1_t
    ld11: uint1_t
    ld12: uint1_t
    ld13: uint1_t
    ld14: uint1_t
    ld15: uint1_t
    an0: uint1_t
    an1: uint1_t
    an2: uint1_t
    an3: uint1_t
    ca: uint1_t
    cb: uint1_t
    cc: uint1_t
    cd: uint1_t
    ce: uint1_t
    cf: uint1_t
    cg: uint1_t
    dp: uint1_t


@hw_func
def led_chaser(
    sw0: uint1_t,
    sw1: uint1_t,
    sw2: uint1_t,
    sw3: uint1_t,
    sw4: uint1_t,
    sw5: uint1_t,
    sw6: uint1_t,
    sw7: uint1_t,
    sw8: uint1_t,
    sw9: uint1_t,
    sw10: uint1_t,
    sw11: uint1_t,
    sw12: uint1_t,
    sw13: uint1_t,
    sw14: uint1_t,
    sw15: uint1_t,
    btn_left: uint1_t,
    btn_right: uint1_t,
    btn_up: uint1_t,
    btn_down: uint1_t,
    btn_center: uint1_t,
) -> led_chaser_t:
    counter: Reg[uint32_t] = 0
    position: Reg[uint4_t] = 0
    segment_position: Reg[uint32_t] = 0
    direction_right: Reg[uint1_t] = 1

    scan_counter: Reg[uint32_t] = 0
    scan_digit: Reg[uint4_t] = 0
    if scan_counter >= (25_000 - 1):
        scan_counter = 0
        if scan_digit == 3:
            scan_digit = 0
        else:
            scan_digit = scan_digit + 1
    else:
        scan_counter = scan_counter + 1

    if btn_left:
        direction_right = 1
    if btn_right:
        direction_right = 0

    step_cycles: uint32_t = 10_000_000
    if btn_up:
        step_cycles = 5_000_000
    if btn_down:
        step_cycles = 20_000_000

    if btn_center:
        counter = 0
    elif counter >= (step_cycles - 1):
        counter = 0
        if direction_right:
            if position == 15:
                position = 0
            else:
                position = position + 1
            if segment_position == 31:
                segment_position = 0
            else:
                segment_position = segment_position + 1
        else:
            if position == 0:
                position = 15
            else:
                position = position - 1
            if segment_position == 0:
                segment_position = 31
            else:
                segment_position = segment_position - 1
    else:
        counter = counter + 1

    ld0: uint1_t = (position == 0) ^ sw0
    ld1: uint1_t = (position == 1) ^ sw1
    ld2: uint1_t = (position == 2) ^ sw2
    ld3: uint1_t = (position == 3) ^ sw3
    ld4: uint1_t = (position == 4) ^ sw4
    ld5: uint1_t = (position == 5) ^ sw5
    ld6: uint1_t = (position == 6) ^ sw6
    ld7: uint1_t = (position == 7) ^ sw7
    ld8: uint1_t = (position == 8) ^ sw8
    ld9: uint1_t = (position == 9) ^ sw9
    ld10: uint1_t = (position == 10) ^ sw10
    ld11: uint1_t = (position == 11) ^ sw11
    ld12: uint1_t = (position == 12) ^ sw12
    ld13: uint1_t = (position == 13) ^ sw13
    ld14: uint1_t = (position == 14) ^ sw14
    ld15: uint1_t = (position == 15) ^ sw15

    q0: uint1_t = (segment_position == 0) ^ sw0
    q1: uint1_t = (segment_position == 1) ^ sw0
    q2: uint1_t = (segment_position == 2) ^ sw1
    q3: uint1_t = (segment_position == 3) ^ sw1
    q4: uint1_t = (segment_position == 4) ^ sw2
    q5: uint1_t = (segment_position == 5) ^ sw2
    q6: uint1_t = (segment_position == 6) ^ sw3
    q7: uint1_t = (segment_position == 7) ^ sw3
    q8: uint1_t = (segment_position == 8) ^ sw4
    q9: uint1_t = (segment_position == 9) ^ sw4
    q10: uint1_t = (segment_position == 10) ^ sw5
    q11: uint1_t = (segment_position == 11) ^ sw5
    q12: uint1_t = (segment_position == 12) ^ sw6
    q13: uint1_t = (segment_position == 13) ^ sw6
    q14: uint1_t = (segment_position == 14) ^ sw7
    q15: uint1_t = (segment_position == 15) ^ sw7
    q16: uint1_t = (segment_position == 16) ^ sw8
    q17: uint1_t = (segment_position == 17) ^ sw8
    q18: uint1_t = (segment_position == 18) ^ sw9
    q19: uint1_t = (segment_position == 19) ^ sw9
    q20: uint1_t = (segment_position == 20) ^ sw10
    q21: uint1_t = (segment_position == 21) ^ sw10
    q22: uint1_t = (segment_position == 22) ^ sw11
    q23: uint1_t = (segment_position == 23) ^ sw11
    q24: uint1_t = (segment_position == 24) ^ sw12
    q25: uint1_t = (segment_position == 25) ^ sw12
    q26: uint1_t = (segment_position == 26) ^ sw13
    q27: uint1_t = (segment_position == 27) ^ sw13
    q28: uint1_t = (segment_position == 28) ^ sw14
    q29: uint1_t = (segment_position == 29) ^ sw14
    q30: uint1_t = (segment_position == 30) ^ sw15
    q31: uint1_t = (segment_position == 31) ^ sw15

    an0: uint1_t = 1
    an1: uint1_t = 1
    an2: uint1_t = 1
    an3: uint1_t = 1
    ca: uint1_t = 1
    cb: uint1_t = 1
    cc: uint1_t = 1
    cd: uint1_t = 1
    ce: uint1_t = 1
    cf: uint1_t = 1
    cg: uint1_t = 1
    dp: uint1_t = 1

    if scan_digit == 0:
        an0 = 0
        ca = ~q3
        cb = ~q27
        cc = ~q12
        cd = ~q11
        ce = ~q13
        cf = ~q26
        cg = ~q4
        dp = ~q28
    elif scan_digit == 1:
        an1 = 0
        ca = ~q2
        cb = ~q25
        cc = ~q14
        cd = ~q10
        ce = ~q15
        cf = ~q24
        cg = ~q5
        dp = ~q29
    elif scan_digit == 2:
        an2 = 0
        ca = ~q1
        cb = ~q23
        cc = ~q16
        cd = ~q9
        ce = ~q17
        cf = ~q22
        cg = ~q6
        dp = ~q30
    else:
        an3 = 0
        ca = ~q0
        cb = ~q21
        cc = ~q18
        cd = ~q8
        ce = ~q19
        cf = ~q20
        cg = ~q7
        dp = ~q31

    return led_chaser_t(
        ld0=ld0, ld1=ld1, ld2=ld2, ld3=ld3,
        ld4=ld4, ld5=ld5, ld6=ld6, ld7=ld7,
        ld8=ld8, ld9=ld9, ld10=ld10, ld11=ld11,
        ld12=ld12, ld13=ld13, ld14=ld14, ld15=ld15,
        an0=an0, an1=an1, an2=an2, an3=an3,
        ca=ca, cb=cb, cc=cc, cd=cd, ce=ce, cf=cf, cg=cg, dp=dp,
    )
