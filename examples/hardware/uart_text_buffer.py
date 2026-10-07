# pyright: reportInvalidTypeForm=none
"""UART byte-buffer writes: append text or erase the last byte."""
from pypeline import *
from ram import make_ram
from hardware.uart_rx import uart_rx_t


@struct
class uart_text_write_t(NamedTuple):
    address: uint14_t
    data: uint8_t
    tail: uint14_t
    committed: uint1_t


def make_uart_text_writer(capacity=8192):
    if capacity < 2 or capacity > 8192 or capacity & (capacity - 1):
        raise ValueError('UART buffer capacity must be a power of two from 2 to 8192')

    @hw_func
    def uart_text_writer(received: uart_rx_t, written: uint14_t) -> uart_text_write_t:
        erase: uint1_t = (received.data == 8) | (received.data == 127)
        commit: uint1_t = received.valid & (((~erase) & (written < capacity))
                                           | (erase & (written != 0)))
        address: uint14_t = written
        data: uint8_t = received.data
        tail: uint14_t = written
        if erase:
            data = 0  # Unsupported byte: old frame snapshots skip deleted ink.
            if written != 0:
                address = written - 1
            if commit:
                tail = written - 1
        elif commit:
            tail = written + 1
        return uart_text_write_t(address=address, data=data, tail=tail,
                                 committed=commit)

    return uart_text_writer


@struct
class uart_text_buffer_t(NamedTuple):
    data: uint8_t
    tail: uint14_t
    committed: uint1_t
    full: uint1_t


def make_uart_text_buffer(capacity=8192):
    """Small BRAM harness for testing the same writer used by the VGA demo."""
    writer = make_uart_text_writer(capacity)
    address_bits = (capacity - 1).bit_length()
    memory, _ = make_ram(uint8_t, capacity, ports=("w", "r"), read_latency=1)

    @hw_func
    def uart_text_buffer(received: uart_rx_t, read_index: uint14_t) -> uart_text_buffer_t:
        written: Reg[uint14_t] = 0
        # Frame snapshots see the pre-edit tail, after previous writes committed.
        tail: uint14_t = written
        edit = writer(received, written)
        chars = memory(memory.p0_in_t(addr=edit.address[address_bits - 1:0],
                                      wr_data=edit.data, wr_en=edit.committed, valid=1),
                       memory.p1_in_t(addr=read_index[address_bits - 1:0], valid=1))
        if edit.committed:
            written = edit.tail
        return uart_text_buffer_t(data=chars.p1.rd_data, tail=tail,
                                  committed=edit.committed, full=(written == capacity))

    return uart_text_buffer
