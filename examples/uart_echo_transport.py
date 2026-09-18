# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Reusable 115200-baud 8-N-1 UART echo transport for Basys 3.

This module deliberately owns only the USB-UART pins (RsRx/RsTx).  Import it
from a larger design to add an echoing serial port without also claiming LEDs,
switches, buttons, seven-segment pins, VGA, or PS/2 resources.

`last_rx_byte` is a registered module boundary carrying the most recently
accepted byte for optional presentation logic in another @MAIN.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.uart as board_uart


# 100 MHz / 115200 baud = 868.055... clocks per bit.
BAUD_DIV = 868
HALF_BAUD_DIV = 434

@struct
class uart_tx_request_t(NamedTuple):
    data: uint8_t
    seq: uint8_t
    accepted_seq: uint8_t


last_rx_byte: Wire[uint32_t]
# A composable one-byte TX mailbox.  Another @MAIN may drive `.data` and `.seq`;
# this transport alone drives `.accepted_seq`.  With no external writer the
# undriven request fields are zero, so the standalone UART echo still works.
tx_request: Wire[uart_tx_request_t]


@MAIN(100.0)
def uart_echo_transport():
    # Two-stage synchronization of asynchronous RsRx.  Pypeline forwards Reg
    # assignments within a function, so shift-register transfers are written
    # oldest-destination first to preserve the previous-cycle samples.
    rx_meta: Reg[uint1_t] = 1
    rx_sync: Reg[uint1_t] = 1
    rx_sync = rx_meta
    rx_meta = board_uart.RsRx

    # RX states: 0=idle, 1=verify start, 2=data, 3=stop.
    rx_state: Reg[uint32_t] = 0
    rx_timer: Reg[uint32_t] = 0
    rx_bit: Reg[uint32_t] = 0
    rx_shift: Reg[uint32_t] = 0

    # One-byte mailbox between the receiver and transmitter.
    rx_byte: Reg[uint32_t] = 0
    rx_pending: Reg[uint1_t] = 0

    # Publish only registered state at the module boundary.  This avoids
    # forwarding the stop-bit receive logic into downstream presentation mains.
    out_last_rx_byte: uint32_t = rx_byte

    if rx_state == 0:
        if rx_sync == 0:
            rx_timer = 0
            rx_state = 1
    elif rx_state == 1:
        # Re-sample halfway through the start bit to reject short glitches.
        if rx_timer >= (HALF_BAUD_DIV - 1):
            rx_timer = 0
            if rx_sync == 0:
                rx_bit = 0
                rx_shift = 0
                rx_state = 2
            else:
                rx_state = 0
        else:
            rx_timer = rx_timer + 1
    elif rx_state == 2:
        # From the center of the start bit, wait one full bit period to sample
        # each data bit in its center. UART transmits least-significant bit first.
        if rx_timer >= (BAUD_DIV - 1):
            rx_timer = 0
            if rx_sync:
                rx_shift = (rx_shift >> 1) | 128
            else:
                rx_shift = rx_shift >> 1
            if rx_bit == 7:
                rx_state = 3
            else:
                rx_bit = rx_bit + 1
        else:
            rx_timer = rx_timer + 1
    else:
        # Stop bit must be high. If the one-byte mailbox is occupied, the new
        # byte is intentionally dropped rather than overwriting unsent data.
        if rx_timer >= (BAUD_DIV - 1):
            rx_timer = 0
            rx_state = 0
            if rx_sync & ~rx_pending:
                rx_byte = rx_shift
                rx_pending = 1
        else:
            rx_timer = rx_timer + 1

    # TX states: 0=idle, 1=start, 2=data, 3=stop.
    tx_state: Reg[uint32_t] = 0
    tx_timer: Reg[uint32_t] = 0
    tx_bit: Reg[uint32_t] = 0
    tx_shift: Reg[uint32_t] = 0
    external_seen_seq: Reg[uint8_t] = 0
    out_external_seen_seq: uint8_t = external_seen_seq

    if tx_state == 0:
        # Echo received UART bytes first.  Otherwise accept a new byte from any
        # composed producer that advances tx_request.seq.  The producer keeps
        # its request stable until accepted_seq catches up.
        if rx_pending:
            tx_shift = rx_byte
            tx_bit = 0
            tx_timer = 0
            tx_state = 1
            rx_pending = 0
        elif tx_request.seq != external_seen_seq:
            tx_shift = tx_request.data
            tx_bit = 0
            tx_timer = 0
            tx_state = 1
            external_seen_seq = tx_request.seq
    elif tx_state == 1:
        if tx_timer >= (BAUD_DIV - 1):
            tx_timer = 0
            tx_state = 2
        else:
            tx_timer = tx_timer + 1
    elif tx_state == 2:
        if tx_timer >= (BAUD_DIV - 1):
            tx_timer = 0
            tx_shift = tx_shift >> 1
            if tx_bit == 7:
                tx_state = 3
            else:
                tx_bit = tx_bit + 1
        else:
            tx_timer = tx_timer + 1
    else:
        if tx_timer >= (BAUD_DIV - 1):
            tx_timer = 0
            tx_state = 0
        else:
            tx_timer = tx_timer + 1

    # UART idles high, begins with a low start bit, sends 8 data bits LSB-first,
    # and ends with a high stop bit.
    board_uart.RsTx = 1
    if tx_state == 1:
        board_uart.RsTx = 0
    elif tx_state == 2:
        board_uart.RsTx = tx_shift[0]

    last_rx_byte = out_last_rx_byte
    tx_request.accepted_seq = out_external_seen_seq
