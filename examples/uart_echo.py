# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""115200-baud 8-N-1 UART echo on the Basys 3 USB-UART bridge.

Each received byte is echoed back and displayed in binary on LD7..LD0.
The implementation deliberately uses only a one-byte holding register so the
UART framing and buffering machinery stays visible.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


# 100 MHz / 115200 baud = 868.055... clocks per bit.
BAUD_DIV = 868
HALF_BAUD_DIV = 434


@MAIN(100.0)
def uart_echo():
    # Synchronize the asynchronous RX input into the FPGA clock domain.
    rx_meta: Reg[uint1_t] = 1
    rx_sync: Reg[uint1_t] = 1
    rx_meta = board.RsRx
    rx_sync = rx_meta

    # RX states: 0=idle, 1=verify start, 2=data, 3=stop.
    rx_state: Reg[uint32_t] = 0
    rx_timer: Reg[uint32_t] = 0
    rx_bit: Reg[uint32_t] = 0
    rx_shift: Reg[uint32_t] = 0

    # One-byte mailbox between the receiver and transmitter.
    rx_byte: Reg[uint32_t] = 0
    rx_pending: Reg[uint1_t] = 0

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

    if tx_state == 0:
        if rx_pending:
            tx_shift = rx_byte
            tx_bit = 0
            tx_timer = 0
            tx_state = 1
            rx_pending = 0
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
    board.RsTx = 1
    if tx_state == 1:
        board.RsTx = 0
    elif tx_state == 2:
        board.RsTx = tx_shift[0]

    # Show the most recently accepted byte on the low eight LEDs.
    board.LD0 = rx_byte[0]
    board.LD1 = rx_byte[1]
    board.LD2 = rx_byte[2]
    board.LD3 = rx_byte[3]
    board.LD4 = rx_byte[4]
    board.LD5 = rx_byte[5]
    board.LD6 = rx_byte[6]
    board.LD7 = rx_byte[7]
    board.LD8 = 0
    board.LD9 = 0
    board.LD10 = 0
    board.LD11 = 0
    board.LD12 = 0
    board.LD13 = 0
    board.LD14 = 0
    board.LD15 = 0

    # This example does not use the seven-segment display. Its enables and
    # cathodes are active-low, so drive everything high to keep it dark.
    board.AN0 = 1
    board.AN1 = 1
    board.AN2 = 1
    board.AN3 = 1
    board.CA = 1
    board.CB = 1
    board.CC = 1
    board.CD = 1
    board.CE = 1
    board.CF = 1
    board.CG = 1
    board.DP = 1
