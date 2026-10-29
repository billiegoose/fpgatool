# pyright: reportInvalidTypeForm=none
"""Basys 3 resident live-flash proxy with caller-owned physical pins.

    loader = load_asset(dq, reload_request, clear_error)
    selected = proxy(loader.flash, application_status, dq[1])
    # The top level binds selected.flash to QSPI and STARTUPE2.

The application must stop starting transfers when pause is set, finish the
current transfer, and report quiescent. The proxy owns USER1/USER2/USER4,
but does not import or drive board pins. Instantiate once per design in one
clock domain. pause/reload_request/clear_error are logical feedback wires.
"""
from pypeline import *
from hardware.QSPI import qspi_flash_byte_io_t
from hardware.live_flash import (live_flash_application_t, live_flash_control_t,
                                 live_flash_control)
import fpgatool_board.basys3.jtag_flash as jtag

pause: Wire[uint1_t]
reload_request: Wire[uint1_t]
clear_error: Wire[uint1_t]


@struct
class live_flash_proxy_t(NamedTuple):
    flash: qspi_flash_byte_io_t
    control: live_flash_control_t


@hw_func
def proxy(application_pins: qspi_flash_byte_io_t,
          application: live_flash_application_t, miso: uint1_t) -> live_flash_proxy_t:
    status: Reg[uint32_t] = 4
    seen_cs: Reg[uint1_t] = 0
    seen_clock: Reg[uint1_t] = 0
    seen_mosi_zero: Reg[uint1_t] = 0
    seen_mosi_one: Reg[uint1_t] = 0
    seen_miso_zero: Reg[uint1_t] = 0
    seen_miso_one: Reg[uint1_t] = 0
    seen_application_cs: Reg[uint1_t] = 0
    seen_application_clock: Reg[uint1_t] = 0
    command = jtag.live_command(status)
    # Both an application acknowledgement and idle physical pins are required.
    safe = live_flash_application_t(ready=application.ready, busy=application.busy,
        quiescent=application.quiescent & application_pins.cs_n & (~application_pins.cclk),
        done=application.done, error=application.error)
    control = live_flash_control(command, safe)
    pause = control.pause
    reload_request = control.reload
    clear_error = control.clear_error
    bridge = jtag.spi_bridge(miso, control.granted)
    if control.granted:
        if not bridge.cs_n:
            seen_cs = 1
            if bridge.cclk:
                seen_clock = 1
            if bridge.dq0:
                seen_mosi_one = 1
            else:
                seen_mosi_zero = 1
            if miso:
                seen_miso_one = 1
            else:
                seen_miso_zero = 1
        if not application_pins.cs_n:
            seen_application_cs = 1
        if application_pins.cclk:
            seen_application_clock = 1
    status = control.status | (uint32_t(seen_cs) << 4) | (uint32_t(seen_clock) << 5) | (uint32_t(seen_mosi_zero) << 6) | (uint32_t(seen_mosi_one) << 7) | (uint32_t(seen_miso_zero) << 8) | (uint32_t(seen_miso_one) << 9) | (uint32_t(seen_application_cs) << 10) | (uint32_t(seen_application_clock) << 11)
    flash = application_pins
    if control.granted:
        flash = bridge
    return live_flash_proxy_t(flash=flash, control=control)
