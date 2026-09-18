# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""115200-baud 8-N-1 UART echo on the Basys 3 USB-UART bridge.

The reusable serial transport lives in `uart_echo_transport.py`; this standalone
example adds a simple presentation MAIN that shows the last received byte on
LD7..LD0 and keeps the seven-segment display dark.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.user_io as board_user
import uart_echo_transport as uart


@MAIN(100.0)
def uart_echo_display():
    rx_byte: uint32_t = uart.last_rx_byte

    board_user.LD0 = rx_byte[0]
    board_user.LD1 = rx_byte[1]
    board_user.LD2 = rx_byte[2]
    board_user.LD3 = rx_byte[3]
    board_user.LD4 = rx_byte[4]
    board_user.LD5 = rx_byte[5]
    board_user.LD6 = rx_byte[6]
    board_user.LD7 = rx_byte[7]
    board_user.LD8 = 0
    board_user.LD9 = 0
    board_user.LD10 = 0
    board_user.LD11 = 0
    board_user.LD12 = 0
    board_user.LD13 = 0
    board_user.LD14 = 0
    board_user.LD15 = 0

    # Seven-segment enables and cathodes are active-low; all high keeps it dark.
    board_user.AN0 = 1
    board_user.AN1 = 1
    board_user.AN2 = 1
    board_user.AN3 = 1
    board_user.CA = 1
    board_user.CB = 1
    board_user.CC = 1
    board_user.CD = 1
    board_user.CE = 1
    board_user.CF = 1
    board_user.CG = 1
    board_user.DP = 1
