# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""115200-baud UART echo on the Basys 3 USB-UART bridge.

Top-level examples own board pins and clocks. Reusable UART hardware lives in
`examples/hardware/uart.py` and knows nothing about the Basys 3 pinout.
"""

from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.uart as board_uart
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.seven_segment as board_seven_segment
import hardware.uart as uart


@MAIN(100.0)
def uart_echo():
    transport = uart.uart_echo(board_uart.RsRx, uint8_t(0), uint8_t(0))
    board_uart.RsTx = transport.tx

    rx_byte: uint8_t = transport.last_rx_byte
    board_leds.LD0 = rx_byte[0]
    board_leds.LD1 = rx_byte[1]
    board_leds.LD2 = rx_byte[2]
    board_leds.LD3 = rx_byte[3]
    board_leds.LD4 = rx_byte[4]
    board_leds.LD5 = rx_byte[5]
    board_leds.LD6 = rx_byte[6]
    board_leds.LD7 = rx_byte[7]
    board_leds.LD8 = 0
    board_leds.LD9 = 0
    board_leds.LD10 = 0
    board_leds.LD11 = 0
    board_leds.LD12 = 0
    board_leds.LD13 = 0
    board_leds.LD14 = 0
    board_leds.LD15 = 0

    board_seven_segment.AN0 = 1
    board_seven_segment.AN1 = 1
    board_seven_segment.AN2 = 1
    board_seven_segment.AN3 = 1
    board_seven_segment.CA = 1
    board_seven_segment.CB = 1
    board_seven_segment.CC = 1
    board_seven_segment.CD = 1
    board_seven_segment.CE = 1
    board_seven_segment.CF = 1
    board_seven_segment.CG = 1
    board_seven_segment.DP = 1
