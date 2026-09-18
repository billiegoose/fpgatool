# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Reusable board-agnostic 115200-baud 8-N-1 UART echo hardware."""

from pypeline import *


BAUD_DIV = 868
HALF_BAUD_DIV = 434


@struct
class uart_echo_t(NamedTuple):
    tx: uint1_t
    last_rx_byte: uint8_t
    accepted_seq: uint8_t


@hw_func
def uart_echo(rx: uint1_t, request_data: uint8_t, request_seq: uint8_t) -> uart_echo_t:
    """Echo received bytes and optionally transmit bytes from a one-byte request mailbox."""
    rx_meta: Reg[uint1_t] = 1
    rx_sync: Reg[uint1_t] = 1
    rx_sync = rx_meta
    rx_meta = rx

    # RX states: 0=idle, 1=verify start, 2=data, 3=stop.
    rx_state: Reg[uint2_t] = 0
    rx_timer: Reg[uint16_t] = 0
    rx_bit: Reg[uint3_t] = 0
    rx_shift: Reg[uint8_t] = 0
    rx_byte: Reg[uint8_t] = 0
    rx_pending: Reg[uint1_t] = 0

    out_last_rx_byte: uint8_t = rx_byte

    if rx_state == 0:
        if rx_sync == 0:
            rx_timer = 0
            rx_state = 1
    elif rx_state == 1:
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
        if rx_timer >= (BAUD_DIV - 1):
            rx_timer = 0
            rx_state = 0
            if rx_sync & ~rx_pending:
                rx_byte = rx_shift
                rx_pending = 1
        else:
            rx_timer = rx_timer + 1

    # TX states: 0=idle, 1=start, 2=data, 3=stop.
    tx_state: Reg[uint2_t] = 0
    tx_timer: Reg[uint16_t] = 0
    tx_bit: Reg[uint3_t] = 0
    tx_shift: Reg[uint8_t] = 0
    external_seen_seq: Reg[uint8_t] = 0
    out_external_seen_seq: uint8_t = external_seen_seq

    if tx_state == 0:
        if rx_pending:
            tx_shift = rx_byte
            tx_bit = 0
            tx_timer = 0
            tx_state = 1
            rx_pending = 0
        elif request_seq != external_seen_seq:
            tx_shift = request_data
            tx_bit = 0
            tx_timer = 0
            tx_state = 1
            external_seen_seq = request_seq
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

    tx: uint1_t = 1
    if tx_state == 1:
        tx = 0
    elif tx_state == 2:
        tx = tx_shift[0]

    return uart_echo_t(
        tx=tx,
        last_rx_byte=out_last_rx_byte,
        accepted_seq=out_external_seen_seq,
    )
