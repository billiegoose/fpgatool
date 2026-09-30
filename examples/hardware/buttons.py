# pyright: reportInvalidTypeForm=none
"""Reusable synchronized, debounced pushbutton input.

The Basys 3 buttons are asynchronous mechanical inputs.  Each instance first
passes the raw pin through a two-register synchronizer, then requires the
synchronized value to remain different from the current stable level for 20 ms
at a 100 MHz system clock before accepting the transition.

``level`` is the debounced level for hold-style controls. ``pressed`` and
``released`` are one-clock pulses emitted only when a debounced transition is
accepted. ``repeat`` is an activation pulse suitable for keyboard-style
navigation: it fires immediately with ``pressed``, waits 500 ms, then repeats
every 75 ms until release.
"""

from pypeline import *




@struct
class button_t(NamedTuple):
    level: uint1_t
    pressed: uint1_t
    released: uint1_t
    repeat: uint1_t


def make_button(
    DEBOUNCE_CYCLES=2_000_000,
    REPEAT_DELAY_CYCLES=50_000_000,
    REPEAT_INTERVAL_CYCLES=7_500_000,
):
    """Return a synchronized/debounced button ``hw_func``.

    Timing parameters are ordinary Python elaboration-time values. Counter
    widths are derived from them before Pypeline lowers the returned hardware
    function, so the generated design contains only the required-width counters
    and constant thresholds.
    """

    if DEBOUNCE_CYCLES <= 0:
        raise ValueError("DEBOUNCE_CYCLES must be positive")
    if REPEAT_DELAY_CYCLES <= 0:
        raise ValueError("REPEAT_DELAY_CYCLES must be positive")
    if REPEAT_INTERVAL_CYCLES <= 0:
        raise ValueError("REPEAT_INTERVAL_CYCLES must be positive")

    debounce_count_t = make_uint_t(max(1, (DEBOUNCE_CYCLES - 1).bit_length()))
    repeat_count_t = make_uint_t(
        max(
            1,
            (max(REPEAT_DELAY_CYCLES, REPEAT_INTERVAL_CYCLES) - 1).bit_length(),
        )
    )

    @hw_func
    def button(raw: uint1_t) -> button_t:
        sync_meta: Reg[uint1_t] = 0
        sync_value: Reg[uint1_t] = 0
        stable: Reg[uint1_t] = 0
        count: Reg[debounce_count_t] = 0
        repeat_count: Reg[repeat_count_t] = 0
        repeating: Reg[uint1_t] = 0

        pressed: uint1_t = 0
        released: uint1_t = 0
        repeat: uint1_t = 0

        # Two-register clock-domain synchronizer before the debounce state machine.
        sync_meta = raw
        sync_value = sync_meta

        if sync_value == stable:
            count = 0
        elif count >= (DEBOUNCE_CYCLES - 1):
            count = 0
            stable = sync_value
            if sync_value:
                pressed = 1
            else:
                released = 1
        else:
            count = count + 1

        # Keyboard-style auto-repeat. The first activation coincides with the
        # accepted press; only a continuously held debounced level can generate
        # subsequent pulses.
        if pressed:
            repeat = 1
            repeat_count = 0
            repeating = 0
        elif released or not stable:
            repeat_count = 0
            repeating = 0
        elif repeating:
            if repeat_count >= (REPEAT_INTERVAL_CYCLES - 1):
                repeat = 1
                repeat_count = 0
            else:
                repeat_count = repeat_count + 1
        else:
            if repeat_count >= (REPEAT_DELAY_CYCLES - 1):
                repeat = 1
                repeat_count = 0
                repeating = 1
            else:
                repeat_count = repeat_count + 1

        return button_t(
            level=stable,
            pressed=pressed,
            released=released,
            repeat=repeat,
        )

    return button
