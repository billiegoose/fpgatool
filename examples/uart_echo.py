# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""115200-baud UART echo on the Basys 3 USB-UART bridge.

Top-level examples own board pins and clocks. Reusable UART hardware lives in
`examples/hardware/uart.py` and knows nothing about the Basys 3 pinout.
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.uart as board_uart
import board.basys3.user_io as board_user
import hardware.uart as uart


@MAIN(100.0)
def uart_echo():
    transport = uart.uart_echo(board_uart.RsRx, uint8_t(0), uint8_t(0))
    board_uart.RsTx = transport.tx

    rx_byte: uint8_t = transport.last_rx_byte
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
