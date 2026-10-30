# pyright: reportInvalidTypeForm=none
"""MFS1 filename lookup and bounded quad reads, above the live-flash proxy.

Open resolves a name to an immutable blob handle. Subsequent reads reuse that
handle until the next open, so a vblank copy never scans the index. Call once
per clock; requests are pulses and returned status/data are registered. Stream
bytes have no backpressure, matching qspi_burst's one byte per 20 clocks.
"""
from pypeline import *
from hardware import QSPI
from hardware.qspi_burst import read_burst

INDEX_START = 0x240000
INDEX_HEADER_BYTES = 256
INDEX_ENTRIES = 1020
LEGACY_START = 0x220000
DATA_START = 0x250000
FLASH_END = 0x400000
TYPE_FONT = 2

uint256_t = make_uint_t(256)


@hw_func
def crc32_byte(crc: uint32_t, byte: uint8_t) -> uint32_t:
    value: uint32_t = crc ^ uint32_t(byte)
    for i in range(8):
        if value[0]:
            value = (value >> 1) ^ uint32_t(0xEDB88320)
        else:
            value = value >> 1
    return value


@struct
class file_read_t(NamedTuple):
    flash: QSPI.qspi_flash_byte_io_t
    opened: uint1_t
    object_type: uint8_t
    length: uint24_t
    busy: uint1_t
    error: uint1_t
    data: uint8_t
    valid: uint1_t
    done: uint1_t


@hw_func
def initialize_quad(dq: uint4_t, reset: uint1_t) -> QSPI.qspi_flash_byte_io_t:
    setup = QSPI.flash_byte_io(dq, uint2_t(0), uint32_t(0), uint8_t(0), reset)
    # With no application operation, this engine only wakes the flash and
    # reads/writes its status/configuration registers using single-bit SPI.
    # Exclude its unused quad-payload pad decoder from the startup bus.
    return QSPI.qspi_flash_byte_io_t(
        cclk=setup.cclk, cs_n=setup.cs_n, dq0=setup.dq0, dq0_t=0,
        dq1=1, dq1_t=1, dq2=1, dq2_t=0, dq3=1, dq3_t=0,
        read_data=0, ready=setup.ready, busy=setup.busy,
        done=setup.done, error=setup.error, quad_enabled=setup.quad_enabled,
        quad_activity=0, quad_write_activity=0)


@hw_func
def preinitialized_quad(dq: uint4_t, reset: uint1_t) -> QSPI.qspi_flash_byte_io_t:
    return QSPI.qspi_flash_byte_io_t(
        cclk=0, cs_n=1, dq0=0, dq0_t=1, dq1=1, dq1_t=1,
        dq2=1, dq2_t=1, dq3=1, dq3_t=1, read_data=0,
        ready=~reset, busy=reset, done=0, error=0, quad_enabled=1,
        quad_activity=0, quad_write_activity=0)


@hw_func
def registered_flash_bus(pins: QSPI.qspi_flash_byte_io_t) -> QSPI.qspi_flash_byte_io_t:
    # Delay the entire selected bus together, isolating the engine/selection
    # logic from the proxy and physical pads. Idle startup: CS high, SCK low,
    # all four pads released, busy asserted. Receive sampling remains four
    # clocks after the physical falling edge (the burst half-period is five).
    bus: Reg[uint25_t] = 0xBF8020
    saved: uint25_t = bus
    bus = concat(pins.cclk, pins.cs_n, pins.dq0, pins.dq0_t,
                 pins.dq1, pins.dq1_t, pins.dq2, pins.dq2_t,
                 pins.dq3, pins.dq3_t, pins.read_data, pins.ready,
                 pins.busy, pins.done, pins.error, pins.quad_enabled,
                 pins.quad_activity, pins.quad_write_activity)
    return QSPI.qspi_flash_byte_io_t(
        cclk=saved[24], cs_n=saved[23], dq0=saved[22], dq0_t=saved[21],
        dq1=saved[20], dq1_t=saved[19], dq2=saved[18], dq2_t=saved[17],
        dq3=saved[16], dq3_t=saved[15], read_data=saved[14:7],
        ready=saved[6], busy=saved[5], done=saved[4], error=saved[3],
        quad_enabled=saved[2], quad_activity=saved[1], quad_write_activity=saved[0])


def make_file_reader(filename: str, initialize_flash: bool = True):
    """Create one reader for a fixed UTF-8 name (1–32 bytes, case-sensitive).

    open_request initializes QE and scans the complete journal, including holes.
    The latest committed CRC-valid matching record determines the handle;
    deleted/superseded records hide older versions. A read is range checked
    against the opened file and accepts at most 8191 bytes per burst. abort
    cancels a transfer, retaining the handle. A new open discards the handle.
    The caller owns physical pins and routes flash through the resident proxy.
    Set initialize_flash=False only after caller-completed startup/quad setup;
    this allows timing the file-reader core separately from initialization.
    """
    encoded = filename.encode('utf-8')
    if not encoded or len(encoded) > 32 or b'\0' in encoded:
        raise ValueError('filename must contain 1–32 UTF-8 bytes without NUL')
    name_bits = int.from_bytes(encoded.ljust(32, b'\xff'), 'big')
    name_length = len(encoded)
    initialize = initialize_quad if initialize_flash else preinitialized_quad

    @hw_func
    def read_file(dq: uint4_t, open_request: uint1_t, start: uint1_t,
                  offset: uint24_t, length: uint13_t, abort: uint1_t) -> file_read_t:
        # INIT, QE wait, idle, header start/read, record start/read/check,
        # open finish, data start/read, record commit.
        phase: Reg[uint4_t] = 2
        cycle_phase: uint4_t = phase
        opened: Reg[uint1_t] = 0
        error: Reg[uint1_t] = 0
        file_address: Reg[uint24_t] = 0
        file_length: Reg[uint24_t] = 0
        file_type: Reg[uint8_t] = 0
        found: Reg[uint1_t] = 0
        slot: Reg[uint11_t] = 0
        index: Reg[uint9_t] = 0
        header_bad: Reg[uint1_t] = 0
        cycle_index: uint9_t = index
        saved_header_bad: uint1_t = header_bad
        crc: Reg[uint32_t] = 0xffffffff
        saved_crc: Reg[uint32_t] = 0
        record_address: Reg[uint24_t] = 0
        record_length: Reg[uint24_t] = 0
        record_type: Reg[uint8_t] = 255
        record_name_ok: Reg[uint1_t] = 1
        record_name_length: Reg[uint8_t] = 0
        record_status: Reg[uint8_t] = 255
        commit: Reg[uint8_t] = 255
        record_end: Reg[uint32_t] = 0
        record_matches: Reg[uint1_t] = 0
        record_in_range: Reg[uint1_t] = 0
        read_address: Reg[uint24_t] = 0
        read_length: Reg[uint13_t] = 0
        initialization_reset: Reg[uint1_t] = 0
        burst_start: Reg[uint1_t] = 0
        burst_address: Reg[uint24_t] = 0
        burst_length: Reg[uint13_t] = 0
        burst_abort: Reg[uint1_t] = 1
        pending_byte: Reg[uint8_t] = 0
        pending_valid: Reg[uint1_t] = 0
        data: Reg[uint8_t] = 0
        valid: Reg[uint1_t] = 0
        done: Reg[uint1_t] = 0
        saved_opened: uint1_t = opened
        saved_error: uint1_t = error
        saved_type: uint8_t = file_type
        saved_length: uint24_t = file_length
        saved_data: uint8_t = data
        saved_valid: uint1_t = valid
        saved_done: uint1_t = done
        process_byte: uint1_t = pending_valid
        byte: uint8_t = pending_byte
        end: uint32_t = record_end
        record_end = uint32_t(record_address) + uint32_t(record_length)
        pending_valid = 0
        valid = 0
        done = 0

        # Register engine controls independently of phase decoding. In
        # particular, the byte engine's wide reset fanout must not also carry
        # the file FSM decode/mux path. Account for this request latency below.
        reset_active: uint1_t = initialization_reset
        initialization = initialize(dq, initialization_reset)
        burst = read_burst(dq, burst_start, burst_address, burst_length, burst_abort)
        initialization_reset = cycle_phase == 0
        burst_start = 0
        burst_abort = abort | open_request | uint1_t(cycle_phase <= 1)
        if cycle_phase == 3:
            burst_start = 1
            burst_address = uint24_t(INDEX_START)
            burst_length = INDEX_HEADER_BYTES
        elif cycle_phase == 5:
            burst_start = 1
            burst_address = uint24_t(INDEX_START + INDEX_HEADER_BYTES) + (uint24_t(slot) << 6)
            burst_length = 64
        elif cycle_phase == 9:
            burst_start = 1
            burst_address = read_address
            burst_length = read_length
        if (cycle_phase == 4) | (cycle_phase == 6):
            if burst.valid:
                pending_byte = burst.pins.read_data
                pending_valid = 1
        elif cycle_phase == 10:
            data = burst.pins.read_data
            valid = burst.valid
            done = burst.pins.done

        if cycle_phase == 0:
            phase = 1
        elif cycle_phase == 1:
            if initialization.ready & (~reset_active):
                if initialization.quad_enabled & (~initialization.error):
                    phase = 3
                else:
                    error = 1
                    phase = 2
        elif cycle_phase == 2:
            if start:
                # Widen before adding: neither file offsets nor flash addresses
                # may wrap their 24-bit representation into a permitted range.
                if (~opened) | (uint32_t(offset) + uint32_t(length) > uint32_t(file_length)):
                    error = 1
                elif length == 0:
                    done = 1
                else:
                    read_address = file_address + offset
                    read_length = length
                    phase = 9
        elif cycle_phase == 3:
            index = 0
            header_bad = 0
            phase = 4
        elif cycle_phase == 4:
            if process_byte:
                expected: uint8_t = 255
                if index == 0:
                    expected = 0x4d
                elif index == 1:
                    expected = 0x46
                elif index == 2:
                    expected = 0x53
                elif index == 3:
                    expected = 0x31
                elif index == 4:
                    expected = 1
                elif index == 5:
                    expected = 64
                header_bad = header_bad | (byte != expected)
                index = index + 1
            # Completion uses the registered counter/faults, not this tick's
            # increment and header decode forwarded into another state change.
            if (cycle_index == INDEX_HEADER_BYTES) & burst.pins.ready:
                if saved_header_bad:
                    error = 1
                    phase = 2
                else:
                    phase = 5
        elif cycle_phase == 5:
            index = 0
            crc = 0xffffffff
            saved_crc = 0
            record_address = 0
            record_length = 0
            record_name_ok = 1
            phase = 6
        elif cycle_phase == 6:
            if process_byte:
                if index < 58:
                    crc = crc32_byte(crc, byte)
                if index == 0:
                    record_type = byte
                elif (index >= 17) & (index <= 19):
                    record_address = (record_address >> 8) | (uint24_t(byte) << 16)
                elif (index >= 20) & (index <= 22):
                    record_length = (record_length >> 8) | (uint24_t(byte) << 16)
                elif (index >= 23) & (index <= 54):
                    name_shift: uint8_t = uint8_t((uint9_t(54) - index) << 3)
                    expected_name_byte: uint8_t = uint8_t(uint256_t(name_bits) >> name_shift)
                    record_name_ok = record_name_ok & (byte == expected_name_byte)
                elif index == 55:
                    record_name_length = byte
                elif (index >= 58) & (index <= 61):
                    saved_crc = (saved_crc >> 8) | (uint32_t(byte) << 24)
                elif index == 62:
                    record_status = byte
                elif index == 63:
                    commit = byte
                index = index + 1
            if (cycle_index == 64) & burst.pins.ready:
                phase = 7
        elif cycle_phase == 7:
            # Register the wide name/CRC reduction and range checks before
            # they enable the resolved handle's address/length registers.
            record_matches = (commit == 0) & (saved_crc == ~crc) & (record_name_length == name_length) & record_name_ok
            legacy: uint1_t = (record_address >= LEGACY_START) & (record_address < INDEX_START) & (end <= INDEX_START)
            allocated: uint1_t = (record_address >= DATA_START) & (record_address < FLASH_END) & (end <= FLASH_END)
            record_in_range = legacy | allocated
            phase = 11
        elif cycle_phase == 11:
            if record_matches:
                found = 0
                if (record_status == 255) & record_in_range:
                    found = 1
                    file_address = record_address
                    file_length = record_length
                    file_type = record_type
            if slot == (INDEX_ENTRIES - 1):
                phase = 8
            else:
                slot = slot + 1
                phase = 5
        elif cycle_phase == 8:
            opened = found
            error = ~found
            phase = 2
        elif cycle_phase == 9:
            phase = 10
        elif cycle_phase == 10:
            if burst.pins.error:
                error = 1
                phase = 2
            elif burst.pins.done:
                phase = 2

        if abort:
            phase = 2
            burst_start = 0
            pending_valid = 0
            valid = 0
            done = 0
            saved_valid = 0
            saved_done = 0
        if open_request:
            phase = 0
            burst_start = 0
            opened = 0
            error = 0
            found = 0
            slot = 0
            pending_valid = 0
            valid = 0
            done = 0
            saved_opened = 0
            saved_error = 0
            saved_valid = 0
            saved_done = 0
        flash = burst.pins
        if cycle_phase <= 1:
            flash = initialization
        return file_read_t(flash=registered_flash_bus(flash), opened=saved_opened, object_type=saved_type,
            length=saved_length, busy=uint1_t(cycle_phase != 2), error=saved_error,
            data=saved_data, valid=saved_valid, done=saved_done)

    return read_file
