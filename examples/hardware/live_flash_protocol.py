"""Resident USER2 flash-ownership ABI, shared by host and FPGA designs.

    BEGIN: stop application flash transactions; grant USER1 exclusive access.
    RELEASE: release USER1 without changing the application's active data.
    RELOAD: release USER1; validate/activate data at the design's safe boundary.

BUSY includes ownership/reload. RELOAD completes with READY, !BUSY, !GRANTED
and GENERATION incremented modulo 65536. ERROR reports device validation or
activation failure. BEGIN clears the previous update error for a retry.
The design owns data addresses, validation, buffering and reload timing.
"""
MAGIC = 0x52464C32  # Preserve the original RFL2 wire signature for loaded designs.
BEGIN = 1
RELOAD = 2
RELEASE = 3
READY = 1
GRANTED = 2
BUSY = 4
ERROR = 8
USER2 = 0x03
IR_BITS = 6
DEFAULT_URL = 'ftdi://0x0403:0x6010/1'
