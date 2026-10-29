# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Read-only mini-filesystem UART shell: `list` and `print NAME`.

Flash layout: index at 0x240000, 256-byte header, then 64-byte records.
The newest committed entry for a filename wins.  Only type=1 (text) is
printable.  The existing Basys 3 live-flash proxy owns the QSPI pins while
JTAG is active; RELOAD discards the console's in-flight index scan.

UART is 115200 8-N-1.  End commands with LF or CR.  Use `program-file` to
populate the flash before issuing commands.
"""
from pypeline import *
import fpgatool_board.basys3.part35t
import fpgatool_board.basys3.qspi as board_qspi
import fpgatool_board.basys3.uart as board_uart
import fpgatool_board.basys3.leds as board_leds
import fpgatool_board.basys3.live_flash as board_live_flash
from hardware.live_flash import live_flash_application_t
from hardware.uart_rx import make_uart_rx, uart_rx_t
import hardware.uart as uart_hw
import hardware.QSPI as qspi_hw

uint256_t = make_uint_t(256)
_receive = make_uart_rx(100.0)

_LEGACY_START = 0x220000
_LEGACY_END = 0x240000
_INDEX_START = 0x240100
_INDEX_ENTRIES = 1020
_DATA_START = 0x250000
_FLASH_END = 0x400000

_IDLE = 0
_PAD_NAME = 1
_SCAN_READY = 2
_SCAN_LAUNCH = 3
_SCAN_WAIT = 4
_SEND_NAME = 5
_SEND_EOL = 6
_FILE_READY = 7
_FILE_LAUNCH = 8
_FILE_WAIT = 9
_FILE_SEND = 10
_FILE_EOL = 11
_NOT_FOUND = 12
_NOT_FOUND_EOL = 13
_SCAN_PROCESS = 14


@hw_func
def crc32_byte(crc: uint32_t, byte: uint8_t) -> uint32_t:
    """Reflected CRC32; zlib.crc32(record[0:58]) is ~final_state."""
    value: uint32_t = crc ^ uint32_t(byte)
    for i in range(8):
        if value[0]:
            value = (value >> 1) ^ uint32_t(0xEDB88320)
        else:
            value = value >> 1
    return value


@struct
class mini_fs_result_t(NamedTuple):
    flash: qspi_hw.qspi_flash_byte_io_t
    tx_data: uint8_t
    tx_seq: uint8_t
    quiescent: uint1_t
    done: uint1_t
    ready: uint1_t
    error: uint1_t


@hw_func
def mini_fs_console(dq: uint4_t, received: uart_rx_t, pause: uint1_t,
                    reload: uint1_t, seen_tx_seq: uint8_t) -> mini_fs_result_t:
    state: Reg[uint4_t] = _IDLE
    mode_print: Reg[uint1_t] = 0
    # Minimal command parser for the exact words `list` and `print NAME`.
    cmd_index: Reg[uint6_t] = 0
    list_match: Reg[uint1_t] = 1
    print_match: Reg[uint1_t] = 1
    query_name: Reg[uint256_t] = 0
    query_len: Reg[uint6_t] = 0

    slot: Reg[uint11_t] = 0
    byte_index: Reg[uint6_t] = 0
    all_erased: Reg[uint1_t] = 1
    crc: Reg[uint32_t] = 0xffffffff
    saved_crc: Reg[uint32_t] = 0
    record_type: Reg[uint8_t] = 255
    record_address: Reg[uint24_t] = 0
    record_length: Reg[uint24_t] = 0
    record_name: Reg[uint256_t] = 0
    record_name_length: Reg[uint6_t] = 0
    record_status: Reg[uint8_t] = 255
    found: Reg[uint1_t] = 0
    found_address: Reg[uint24_t] = 0
    found_length: Reg[uint24_t] = 0

    output_name: Reg[uint256_t] = 0
    output_remaining: Reg[uint6_t] = 0
    file_address: Reg[uint24_t] = 0
    file_remaining: Reg[uint24_t] = 0
    pending_byte: Reg[uint8_t] = 0
    crc_enabled: Reg[uint1_t] = 0
    tx_data: Reg[uint8_t] = 0
    tx_seq: Reg[uint8_t] = 0

    op: uint2_t = qspi_hw.FLASH_OP_NONE
    address: uint32_t = uint32_t(_INDEX_START)
    if not pause:
        if state == _SCAN_LAUNCH:
            op = qspi_hw.FLASH_OP_READ
            address = uint32_t(_INDEX_START) + (uint32_t(slot) << 6) + uint32_t(byte_index)
        elif state == _FILE_LAUNCH:
            op = qspi_hw.FLASH_OP_READ
            address = uint32_t(file_address)
    flash = qspi_hw.flash_byte_io(dq, op, address, uint8_t(0), uint1_t(0))
    # The owner FSM enters RELOADING on the request cycle. Acknowledge on
    # the following clock so the completion cannot be lost in phase HOST.
    done_pending: Reg[uint1_t] = 0
    done: uint1_t = done_pending
    done_pending = 0

    if reload:
        # The proxy has released USER1 and the flash is again available.
        # No index cache survives a host update.
        state = _IDLE
        cmd_index = 0
        list_match = 1
        print_match = 1
        query_len = 0
        found = 0
        done_pending = 1

    elif state == _IDLE:
        if not pause and received.valid:
            ch: uint8_t = received.data
            if ch == 10 or ch == 13:
                if cmd_index == 4 and list_match:
                    mode_print = 0
                    slot = 0
                    byte_index = 0
                    state = _SCAN_READY
                elif cmd_index > 6 and print_match and query_len > 0:
                    mode_print = 1
                    found = 0
                    state = _PAD_NAME
                else:
                    state = _NOT_FOUND
                cmd_index = 0
                list_match = 1
                print_match = 1
            elif cmd_index < 38:
                if cmd_index == 0:
                    list_match = ch == 108  # l
                    print_match = ch == 112  # p
                    query_name = 0
                    query_len = 0
                elif cmd_index == 1:
                    list_match = list_match & (ch == 105)  # i
                    print_match = print_match & (ch == 114)  # r
                elif cmd_index == 2:
                    list_match = list_match & (ch == 115)  # s
                    print_match = print_match & (ch == 105)  # i
                elif cmd_index == 3:
                    list_match = list_match & (ch == 116)  # t
                    print_match = print_match & (ch == 110)  # n
                elif cmd_index == 4:
                    list_match = 0
                    print_match = print_match & (ch == 116)  # t
                elif cmd_index == 5:
                    print_match = print_match & (ch == 32)  # space
                else:
                    query_name = (query_name << 8) | uint256_t(ch)
                    query_len = query_len + 1
                cmd_index = cmd_index + 1

    elif state == _PAD_NAME:
        if query_len < 32:
            query_name = (query_name << 8) | uint256_t(255)
            query_len = query_len + 1
        else:
            slot = 0
            byte_index = 0
            state = _SCAN_READY

    elif state == _SCAN_READY:
        if slot >= _INDEX_ENTRIES:
            if mode_print:
                if found:
                    file_address = found_address
                    file_remaining = found_length
                    state = _FILE_READY
                else:
                    state = _NOT_FOUND
            else:
                state = _IDLE
        elif flash.ready and not pause:
            if byte_index == 0:
                all_erased = 1
                crc = 0xffffffff
                saved_crc = 0
                record_type = 255
                record_address = 0
                record_length = 0
                record_name = 0
                record_name_length = 0
                record_status = 255
            state = _SCAN_LAUNCH

    elif state == _SCAN_LAUNCH:
        if not pause:
            state = _SCAN_WAIT

    elif state == _SCAN_WAIT:
        if flash.done:
            # Register the byte before the CRC and record-decoding path.
            pending_byte = flash.read_data
            crc_enabled = byte_index < 58
            state = _SCAN_PROCESS

    elif state == _SCAN_PROCESS:
        b: uint8_t = pending_byte
        if b != 255:
            all_erased = 0
        if crc_enabled:
            crc = crc32_byte(crc, b)
        if byte_index == 0:
            record_type = b
        elif byte_index >= 17 and byte_index <= 19:
            record_address = (record_address >> 8) | (uint24_t(b) << 16)
        elif byte_index >= 20 and byte_index <= 22:
            record_length = (record_length >> 8) | (uint24_t(b) << 16)
        elif byte_index >= 23 and byte_index <= 54:
            record_name = (record_name << 8) | uint256_t(b)
        elif byte_index == 55:
            record_name_length = uint6_t(b)
        elif byte_index >= 58 and byte_index <= 61:
            saved_crc = (saved_crc >> 8) | (uint32_t(b) << 24)
        elif byte_index == 62:
            record_status = b

        if byte_index == 63:
            slot = slot + 1
            byte_index = 0
            if all_erased:
                # First completely unused record ends the append journal.
                slot = _INDEX_ENTRIES
                state = _SCAN_READY
            elif b == 0 and saved_crc == ~crc and record_name_length <= 32:
                if record_name_length > 0:
                    if mode_print:
                        if record_name == query_name:
                            # Newest committed record wins, including a deletion.
                            found = 0
                            if record_type == 1 and record_status == 255 and ((record_address >= _LEGACY_START and record_address < _LEGACY_END and
                                   uint32_t(record_address) + uint32_t(record_length) <= _LEGACY_END) or
                                  (record_address >= _DATA_START)) and \
                               uint32_t(record_address) + uint32_t(record_length) <= _FLASH_END:
                                found = 1
                                found_address = record_address
                                found_length = record_length
                    elif record_status == 255:
                        output_name = record_name
                        output_remaining = record_name_length
                        state = _SEND_NAME
                if state == _SCAN_PROCESS:
                    state = _SCAN_READY
            else:
                state = _SCAN_READY
        else:
            byte_index = byte_index + 1
            state = _SCAN_READY

    elif state == _SEND_NAME:
        if tx_seq == seen_tx_seq:
            tx_data = uint8_t(output_name >> 248)
            tx_seq = tx_seq + 1
            output_name = output_name << 8
            if output_remaining == 1:
                output_remaining = 0
                state = _SEND_EOL
            else:
                output_remaining = output_remaining - 1

    elif state == _SEND_EOL:
        if tx_seq == seen_tx_seq:
            tx_data = 10
            tx_seq = tx_seq + 1
            state = _SCAN_READY

    elif state == _FILE_READY:
        if file_remaining == 0:
            state = _FILE_EOL
        elif flash.ready and not pause:
            state = _FILE_LAUNCH

    elif state == _FILE_LAUNCH:
        if not pause:
            state = _FILE_WAIT

    elif state == _FILE_WAIT:
        if flash.done:
            pending_byte = flash.read_data
            state = _FILE_SEND

    elif state == _FILE_SEND:
        if tx_seq == seen_tx_seq:
            tx_data = pending_byte
            tx_seq = tx_seq + 1
            file_address = file_address + 1
            file_remaining = file_remaining - 1
            state = _FILE_READY

    elif state == _FILE_EOL:
        if tx_seq == seen_tx_seq:
            tx_data = 10
            tx_seq = tx_seq + 1
            state = _IDLE

    elif state == _NOT_FOUND:
        if tx_seq == seen_tx_seq:
            tx_data = 63  # '?'
            tx_seq = tx_seq + 1
            state = _NOT_FOUND_EOL

    else:  # _NOT_FOUND_EOL
        if tx_seq == seen_tx_seq:
            tx_data = 10
            tx_seq = tx_seq + 1
            state = _IDLE

    return mini_fs_result_t(flash=flash, tx_data=tx_data, tx_seq=tx_seq,
                            quiescent=flash.ready, done=done, ready=1, error=0)


@MAIN(100.0)
def mini_filesystem_demo():
    dq: uint4_t = concat(board_qspi.QspiDQ3_I, board_qspi.QspiDQ2_I,
                         board_qspi.QspiDQ1_I, board_qspi.QspiDQ0_I)
    rx = _receive(board_uart.RsRx)
    seen_tx_seq: Reg[uint8_t] = 0
    fs = mini_fs_console(dq, rx, board_live_flash.pause,
                         board_live_flash.reload_request, seen_tx_seq)
    # Reuse the verified transmitter's one-byte sequence mailbox without echo.
    transport = uart_hw.uart_echo(uint1_t(1), fs.tx_data, fs.tx_seq)
    seen_tx_seq = transport.accepted_seq
    board_uart.RsTx = transport.tx

    selected = board_live_flash.proxy(fs.flash, live_flash_application_t(
        ready=fs.ready, busy=0, quiescent=fs.quiescent,
        done=fs.done, error=fs.error), dq[1])
    flash = selected.flash
    board_qspi.QspiCSn = board_qspi.drive_clock_and_cs(flash.cclk, flash.cs_n,
                                                        not flash.busy)
    board_qspi.QspiDQ0_O = flash.dq0
    board_qspi.QspiDQ0_T = flash.dq0_t
    board_qspi.QspiDQ1_O = flash.dq1
    board_qspi.QspiDQ1_T = flash.dq1_t
    board_qspi.QspiDQ2_O = flash.dq2
    board_qspi.QspiDQ2_T = flash.dq2_t
    board_qspi.QspiDQ3_O = flash.dq3
    board_qspi.QspiDQ3_T = flash.dq3_t

    board_leds.LD0 = fs.ready
    board_leds.LD1 = selected.control.granted
    board_leds.LD2 = selected.control.busy
    board_leds.LD3 = selected.control.reload
    board_leds.LD4 = fs.error
    board_leds.LD5 = flash.quad_enabled
    board_leds.LD6 = flash.quad_activity
    board_leds.LD7 = 0
    board_leds.LD8 = 0
    board_leds.LD9 = 0
    board_leds.LD10 = 0
    board_leds.LD11 = 0
    board_leds.LD12 = 0
    board_leds.LD13 = 0
    board_leds.LD14 = 0
    board_leds.LD15 = 0
