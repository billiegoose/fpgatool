# pyright: reportInvalidTypeForm=none
"""Shared configuration-flash protocol constants.

``SPI``, ``DSPI``, and ``QSPI`` implement the same logical byte/block API over
one-, two-, and four-data-line transfers.  Command/address phases remain
single-bit SPI for the S25FL032P dual-output (0x3B) and quad-output (0x6B)
read commands; only the returned data phase is widened.

NOR programming can only clear 1 bits.  Callers must explicitly erase the
containing 64 KiB block before programming data that needs a 0 restored to 1.
"""

# Logical operation ABI shared by every transport.
FLASH_OP_NONE = 0
FLASH_OP_READ = 1
FLASH_OP_PROGRAM = 2
FLASH_OP_ERASE_BLOCK = 3

# Common serial commands.
CMD_READ = 0x03
CMD_PAGE_PROGRAM = 0x02
CMD_WRITE_ENABLE = 0x06
CMD_READ_STATUS = 0x05
CMD_READ_CONFIG = 0x35
CMD_WRITE_REGISTERS = 0x01
CMD_BLOCK_ERASE_64K = 0xD8
CMD_JEDEC_ID = 0x9F
CMD_RESET_ENABLE = 0x66
CMD_RESET = 0x99
CMD_RELEASE_POWER_DOWN = 0xAB

# S25FL032P widened read commands.  Both use one serial command byte, one
# serial 24-bit address, one serial dummy byte, then a widened data phase.
CMD_DUAL_OUTPUT_READ = 0x3B
CMD_QUAD_OUTPUT_READ = 0x6B
CMD_QUAD_PAGE_PROGRAM = 0x32

# Configuration Register bit 1 enables the device's quad I/O pins.
CONFIG_QUAD_ENABLE = 0x02

# All three transports currently use the conservative, hardware-verified
# 5 MHz serial clock.  Wider modes increase payload bits per SCK rather than
# changing the clock rate.
HALF_PERIOD_CYCLES = 10
STARTUP_PRIME_CYCLES = 8
BYTE_POWERUP_CYCLES = 2_000_000
NORMAL_CS_HIGH_CYCLES = 10
RECOVERY_CS_HIGH_CYCLES = 20
RES_CYCLES = 10_000
