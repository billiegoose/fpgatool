# pyright: reportInvalidTypeForm=none
"""Small, board-agnostic SPI reader for a configuration flash JEDEC ID.

This first QSPI example is intentionally read-only.  It issues only the
standard 0x9F Read JEDEC ID command in single-bit SPI mode and captures the
three identification bytes.  DQ2 (WP#) and DQ3 (HOLD#/RESET#) are held high.
"""

from pypeline import *


_HALF_PERIOD_CYCLES = 10  # 100 MHz / (2 * 10) = 5 MHz SCK.
_POWERUP_CYCLES = 100_000  # 1 ms after FPGA user logic starts.
_STARTUP_PRIME_CYCLES = 8  # STARTUPE2 suppresses the first three USRCCLKO cycles.
_CS_HIGH_CYCLES = 20  # 200 ns deselect gap between recovery commands.
_RES_CYCLES = 10_000  # 100 us after 0xAB; comfortably beyond tRES.

_ST_WAIT = 0
_ST_PRIME = 1
_ST_WAKE_FF = 2
_ST_WAKE_CMD = 3
_ST_WAKE_GAP = 4
_ST_WAKE_RES_WAIT = 5
_ST_COMMAND = 6
_ST_READ = 7
_ST_FINISH = 8
_ST_DONE = 9


@struct
class qspi_flash_id_t(NamedTuple):
    cclk: uint1_t
    cs_n: uint1_t
    dq0: uint1_t
    dq2: uint1_t
    dq3: uint1_t
    manufacturer_id: uint8_t
    memory_type: uint8_t
    capacity: uint8_t
    ready: uint1_t


@hw_func
def read_jedec_id(dq1: uint1_t) -> qspi_flash_id_t:
    """Read the flash's three-byte JEDEC ID once after power-up.

    SPI mode 0 is used: command bits are presented while CCLK is low and the
    flash samples them on rising edges; returned DQ1 bits are sampled on rising
    edges after the command's final falling edge.
    """

    state: Reg[uint4_t] = _ST_WAIT
    timer: Reg[uint32_t] = 0
    cclk: Reg[uint1_t] = 0
    cs_n: Reg[uint1_t] = 1

    tx_shift: Reg[uint8_t] = 159  # 0x9F, Read JEDEC ID.
    tx_bit: Reg[uint4_t] = 0

    rx_shift: Reg[uint32_t] = 0
    rx_bit: Reg[uint6_t] = 0
    prime_cycle: Reg[uint4_t] = 0
    wake_ff_byte: Reg[uint4_t] = 0
    wake_step: Reg[uint2_t] = 0

    manufacturer_id: Reg[uint8_t] = 0
    memory_type: Reg[uint8_t] = 0
    capacity: Reg[uint8_t] = 0
    ready: Reg[uint1_t] = 0

    if state == _ST_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_POWERUP_CYCLES - 1):
            timer = 0
            prime_cycle = 0
            state = _ST_PRIME
        else:
            timer = timer + 1

    elif state == _ST_PRIME:
        # UG470: the first three USRCCLKO cycles after End Of Startup are consumed
        # while STARTUPE2 switches CCLK to the user source.  Keep CS# high and emit
        # several complete clocks before placing a real flash command on the bus.
        cs_n = 1
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if prime_cycle >= (_STARTUP_PRIME_CYCLES - 1):
                    # Mirror the recovery preamble used by openFPGALoader before
                    # probing the flash: a run of 1s, reset-enable/reset, then
                    # Release from Deep Power-Down.  This returns configuration
                    # flash devices to a known single-SPI command state.
                    cs_n = 0
                    tx_shift = 255
                    tx_bit = 0
                    wake_ff_byte = 0
                    state = _ST_WAKE_FF
                else:
                    prime_cycle = prime_cycle + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_FF:
        # Send nine bytes of 0xFF under one CS# assertion, matching the initial
        # all-ones transaction used by openFPGALoader's flash reset path.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if tx_bit == 7:
                    tx_bit = 0
                    tx_shift = 255
                    if wake_ff_byte >= 8:
                        cs_n = 1
                        wake_step = 0
                        state = _ST_WAKE_GAP
                    else:
                        wake_ff_byte = wake_ff_byte + 1
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_GAP:
        cclk = 0
        cs_n = 1
        if timer >= (_CS_HIGH_CYCLES - 1):
            timer = 0
            cs_n = 0
            tx_bit = 0
            if wake_step == 0:
                tx_shift = 102  # 0x66, Reset Enable.
            elif wake_step == 1:
                tx_shift = 153  # 0x99, Reset.
            else:
                tx_shift = 171  # 0xAB, Release from Deep Power-Down.
            state = _ST_WAKE_CMD
        else:
            timer = timer + 1

    elif state == _ST_WAKE_CMD:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                cclk = 1
            else:
                cclk = 0
                if tx_bit == 7:
                    cs_n = 1
                    if wake_step == 2:
                        state = _ST_WAKE_RES_WAIT
                    else:
                        wake_step = wake_step + 1
                        state = _ST_WAKE_GAP
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_WAKE_RES_WAIT:
        cclk = 0
        cs_n = 1
        if timer >= (_RES_CYCLES - 1):
            timer = 0
            cs_n = 0
            tx_shift = 159
            tx_bit = 0
            state = _ST_COMMAND
        else:
            timer = timer + 1

    elif state == _ST_COMMAND:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                # Rising edge: flash samples the currently presented MOSI bit.
                cclk = 1
            else:
                # Falling edge: advance MOSI.  After bit 7, the flash begins
                # driving the JEDEC response and we switch to receive mode.
                cclk = 0
                if tx_bit == 7:
                    rx_shift = 0
                    rx_bit = 0
                    state = _ST_READ
                else:
                    tx_shift = tx_shift << 1
                    tx_bit = tx_bit + 1
        else:
            timer = timer + 1

    elif state == _ST_READ:
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            if cclk == 0:
                # Mode-0 sample edge.  Oldest received bit ends up at bit 23.
                cclk = 1
                rx_shift = (rx_shift << 1) | dq1
                if rx_bit == 23:
                    state = _ST_FINISH
                else:
                    rx_bit = rx_bit + 1
            else:
                cclk = 0
        else:
            timer = timer + 1

    elif state == _ST_FINISH:
        # Complete the final high half-cycle before releasing chip-select.
        if timer >= (_HALF_PERIOD_CYCLES - 1):
            timer = 0
            cclk = 0
            cs_n = 1
            manufacturer_id = rx_shift[23:16]
            memory_type = rx_shift[15:8]
            capacity = rx_shift[7:0]
            ready = 1
            state = _ST_DONE
        else:
            timer = timer + 1

    else:
        cclk = 0
        cs_n = 1

    dq0: uint1_t = 0
    if state == _ST_WAKE_FF or state == _ST_WAKE_CMD or state == _ST_COMMAND:
        dq0 = tx_shift[7]

    return qspi_flash_id_t(
        cclk=cclk,
        cs_n=cs_n,
        dq0=dq0,
        dq2=1,
        dq3=1,
        manufacturer_id=manufacturer_id,
        memory_type=memory_type,
        capacity=capacity,
        ready=ready,
    )
