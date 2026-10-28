# pyright: reportInvalidTypeForm=none
"""Application-independent resident flash ownership and reload protocol."""
from pypeline import *
from hardware.live_flash_protocol import BEGIN, RELOAD, RELEASE


@struct
class live_flash_application_t(NamedTuple):
    ready: uint1_t
    busy: uint1_t
    quiescent: uint1_t
    done: uint1_t
    error: uint1_t


@struct
class live_flash_control_t(NamedTuple):
    pause: uint1_t
    granted: uint1_t
    reload: uint1_t
    clear_error: uint1_t
    busy: uint1_t
    generation: uint16_t
    status: uint32_t


@hw_func
def live_flash_control(command: uint2_t,
                       application: live_flash_application_t) -> live_flash_control_t:
    """Arbitrate one flash: IDLE, waiting for quiescence, HOST, RELOADING.

    pause prevents new application transfers. The application may finish an
    existing transfer, then assert quiescent. reload/clear_error are one-clock
    requests. done pulses after successful activation, including initial boot;
    error reports failure. All flash addressing and asset semantics stay with
    the application. Return cycle-start status to avoid forwarding FSM paths.
    """
    phase: Reg[uint2_t] = 0
    generation: Reg[uint16_t] = 0
    cycle_phase: uint2_t = phase
    saved_generation: uint16_t = generation
    granted: uint1_t = cycle_phase == 2
    pause: uint1_t = (cycle_phase == 1) | granted
    busy: uint1_t = (cycle_phase != 0) | application.busy
    reload: uint1_t = 0
    clear_error: uint1_t = 0
    if application.done & (~application.error):
        generation = generation + 1
    if cycle_phase == 0:
        if (command == BEGIN) & (~application.busy):
            clear_error = 1
            phase = 1
    elif cycle_phase == 1:
        if command == RELEASE:
            phase = 0
        elif application.quiescent:
            phase = 2
    elif cycle_phase == 2:
        if command == RELOAD:
            reload = 1
            phase = 3
        elif command == RELEASE:
            phase = 0
    elif cycle_phase == 3:
        if application.done | application.error:
            phase = 0
    status: uint32_t = ((uint32_t(saved_generation) << 16)
                       | (uint32_t(application.error) << 3)
                       | (uint32_t(busy) << 2)
                       | (uint32_t(granted) << 1) | uint32_t(application.ready))
    return live_flash_control_t(pause=pause, granted=granted, reload=reload,
        clear_error=clear_error, busy=busy, generation=saved_generation, status=status)
