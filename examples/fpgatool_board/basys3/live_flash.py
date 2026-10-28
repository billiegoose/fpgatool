# pyright: reportInvalidTypeForm=none
"""One-call Basys 3 resident live-flash service for application demos.

    loader = load_asset(dq, reload_request, clear_error)
    service(loader.flash, application_status)

The application must stop starting transfers when pause is set, finish the
current transfer, and report quiescent. service owns the QSPI output pins and
the USER1/USER2/USER4 chains. Instantiate once per design in one clock domain.
"""
from pypeline import *
from hardware.QSPI import qspi_flash_byte_io_t
from hardware.live_flash import (live_flash_application_t, live_flash_control_t,
                                 live_flash_control)
import fpgatool_board.basys3.qspi as qspi
import fpgatool_board.basys3.jtag_flash as jtag

pause: Wire[uint1_t]
reload_request: Wire[uint1_t]
clear_error: Wire[uint1_t]


@hw_func
def service(application_pins: qspi_flash_byte_io_t,
            application: live_flash_application_t) -> live_flash_control_t:
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
    bridge = jtag.spi_bridge(qspi.QspiDQ1_I, control.granted)
    flash = application_pins
    if control.granted:
        flash = bridge
    qspi.QspiCSn = qspi.drive_clock_and_cs(flash.cclk, flash.cs_n, not flash.busy)
    qspi.QspiDQ0_O = flash.dq0
    qspi.QspiDQ0_T = flash.dq0_t
    qspi.QspiDQ1_O = flash.dq1
    qspi.QspiDQ1_T = flash.dq1_t
    qspi.QspiDQ2_O = flash.dq2
    qspi.QspiDQ2_T = flash.dq2_t
    qspi.QspiDQ3_O = flash.dq3
    qspi.QspiDQ3_T = flash.dq3_t
    return control
