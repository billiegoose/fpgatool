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
    command = jtag.live_command(status)
    # Both an application acknowledgement and idle physical pins are required.
    safe = live_flash_application_t(ready=application.ready, busy=application.busy,
        quiescent=application.quiescent & application_pins.cs_n & (~application_pins.cclk),
        done=application.done, error=application.error)
    control = live_flash_control(command, safe)
    status = control.status
    pause = control.pause
    reload_request = control.reload
    clear_error = control.clear_error
    bridge = jtag.spi_bridge(miso, control.granted)
    flash = application_pins
    if control.granted:
        flash = bridge
    return live_flash_proxy_t(flash=flash, control=control)
