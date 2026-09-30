# pyright: reportInvalidTypeForm=none
"""Reusable synchronized, debounced pushbutton input.

The Basys 3 buttons are asynchronous mechanical inputs.  Each instance first
passes the raw pin through a two-register synchronizer, then requires the
synchronized value to remain different from the current stable level for 20 ms
at a 100 MHz system clock before accepting the transition.

``level`` is the debounced level for hold-style controls. ``pressed`` and
``released`` are one-clock pulses emitted only when a debounced transition is
accepted.
"""

from pypeline import *


_DEBOUNCE_CYCLES = 2_000_000  # 20 ms at 100 MHz.


@struct
class button_t(NamedTuple):
    level: uint1_t
    pressed: uint1_t
    released: uint1_t


@hw_func
def debounce_button(raw: uint1_t) -> button_t:
    """Synchronize and debounce one active-high mechanical pushbutton."""

    sync_meta: Reg[uint1_t] = 0
    sync_value: Reg[uint1_t] = 0
    stable: Reg[uint1_t] = 0
    count: Reg[uint21_t] = 0

    pressed: uint1_t = 0
    released: uint1_t = 0

    # Two-register clock-domain synchronizer before the debounce state machine.
    sync_meta = raw
    sync_value = sync_meta

    if sync_value == stable:
        count = 0
    elif count >= (_DEBOUNCE_CYCLES - 1):
        count = 0
        stable = sync_value
        if sync_value:
            pressed = 1
        else:
            released = 1
    else:
        count = count + 1

    return button_t(
        level=stable,
        pressed=pressed,
        released=released,
    )
