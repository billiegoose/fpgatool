# pyright: reportInvalidTypeForm=none
"""Board-agnostic PS/2 mouse host and IntelliMouse wheel protocol hardware.

The caller supplies sampled open-drain clock/data levels and applies the returned
``*_release`` drive intents to its physical pins: 1 releases the line, 0 pulls
it low.  No board pins, constraints, or PipelineC board package are referenced
here.
"""

import math

from pypeline import *


@struct
class ps2_mouse_t(NamedTuple):
    x: uint12_t
    y: uint12_t
    left: uint1_t
    middle: uint1_t
    right: uint1_t
    wheel: uint8_t
    wheel_mode: uint1_t
    ready: uint1_t


@struct
class ps2_mouse_io_t(NamedTuple):
    clk_release: uint1_t
    data_release: uint1_t
    x: uint12_t
    y: uint12_t
    left: uint1_t
    middle: uint1_t
    right: uint1_t
    wheel: uint8_t
    wheel_mode: uint1_t
    ready: uint1_t


# Link states.
_ST_POWER_WAIT = 0
_ST_TX_INHIBIT = 1
_ST_TX_RTS = 2
_ST_TX_START = 3
_ST_TX_BITS = 4
_ST_TX_STOP_ACK = 5
_ST_TX_RELEASE = 6
_ST_WAIT_FA = 7
_ST_WAIT_ID = 8
_ST_STREAM = 9


def make_ps2_mouse(clock_mhz=100.0, frame_width=640, frame_height=480):
    """Create a mouse host with clock-scaled timeouts and frame-sized bounds."""
    if not math.isfinite(clock_mhz) or not 10 <= clock_mhz <= 800:
        raise ValueError("clock_mhz must be finite and within 10..800 MHz")
    for name, value in (("frame_width", frame_width), ("frame_height", frame_height)):
        if type(value) is not int or not 1 <= value <= 4096:
            raise ValueError(f"{name} must be an integer in 1..4096")
    _CENTER_X = frame_width // 2
    _CENTER_Y = frame_height // 2
    _MAX_X = frame_width - 1
    _MAX_Y = frame_height - 1
    # Preserve protocol durations when running in a different clock domain.
    _POWER_WAIT_CYCLES = math.ceil(clock_mhz * 20_000)  # 20 ms
    _INHIBIT_CYCLES = math.ceil(clock_mhz * 120)  # 120 us (minimum 100 us)
    _RTS_SETUP_CYCLES = math.ceil(clock_mhz * 20)  # 20 us
    _LINK_TIMEOUT_CYCLES = math.ceil(clock_mhz * 20_000)  # 20 ms
    _RESPONSE_TIMEOUT_CYCLES = math.ceil(clock_mhz * 50_000)  # 50 ms
    _timer_t = make_uint_t((_RESPONSE_TIMEOUT_CYCLES - 1).bit_length())

    @hw_func
    def ps2_mouse(ps2_clk: uint1_t, ps2_data: uint1_t) -> ps2_mouse_io_t:
        # Two-stage synchronizers for the asynchronous PS/2 wires, plus delayed clock
        # for edge detection in the caller's clock domain.
        clk_meta: Reg[uint1_t] = 1
        clk_sync: Reg[uint1_t] = 1
        clk_prev: Reg[uint1_t] = 1
        data_meta: Reg[uint1_t] = 1
        data_sync: Reg[uint1_t] = 1

        state: Reg[uint4_t] = _ST_POWER_WAIT
        timer: Reg[_timer_t] = _timer_t(0)
        power_expired: Reg[uint1_t] = 0
        inhibit_expired: Reg[uint1_t] = 0
        setup_expired: Reg[uint1_t] = 0
        link_expired: Reg[uint1_t] = 0
        response_expired: Reg[uint1_t] = 0
        tx_bit: Reg[uint4_t] = 0
        tx_byte: Reg[uint8_t] = 243  # 0xF3, first IntelliMouse negotiation command.
        init_step: Reg[uint4_t] = 0

        # Device-to-host byte receiver.
        rx_bit: Reg[uint4_t] = 0
        rx_shift: Reg[uint8_t] = 0
        rx_parity: Reg[uint1_t] = 0
        rx_parity_ok: Reg[uint1_t] = 0

        # Three- or four-byte packet assembly (four bytes in IntelliMouse wheel mode).
        packet_byte: Reg[uint2_t] = 0
        status: Reg[uint8_t] = 0
        dx: Reg[uint8_t] = 0
        dy: Reg[uint8_t] = 0

        # Public mouse state.  `wheel` is a wrapping cumulative position so a wheel
        # detent remains observable long after the packet-level delta has passed.
        x: Reg[uint12_t] = _CENTER_X
        y: Reg[uint12_t] = _CENTER_Y
        left: Reg[uint1_t] = 0
        middle: Reg[uint1_t] = 0
        right: Reg[uint1_t] = 0
        wheel: Reg[uint8_t] = 0
        wheel_mode: Reg[uint1_t] = 0
        ready: Reg[uint1_t] = 0

        # Publish only registered state.  Pypeline forwards later Reg assignments
        # within this function, so constructing `mouse` directly from x/y/buttons at
        # the end would expose their combinational next-state logic to every consumer
        # (notably the VGA renderer).  These snapshots deliberately add one caller-clock
        # cycle of output latency and keep the module boundary register-to-register.
        out_x: uint12_t = x
        out_y: uint12_t = y
        out_left: uint1_t = left
        out_middle: uint1_t = middle
        out_right: uint1_t = right
        out_wheel: uint8_t = wheel
        out_wheel_mode: uint1_t = wheel_mode
        out_ready: uint1_t = ready

        # Sample first; edge flags intentionally describe the previously synchronized
        # values, which is exactly what a synchronous edge detector needs.
        clk_fall: uint1_t = clk_prev & (~clk_sync)
        # Pypeline forwards sequential assignments within a hardware function, so
        # shift-register transfers must be written oldest-destination first.  This
        # preserves the previous-cycle values instead of collapsing every stage to
        # the current asynchronous pad sample.
        clk_prev = clk_sync
        clk_sync = clk_meta
        clk_meta = ps2_clk
        data_sync = data_meta
        data_meta = ps2_data

        # Open-drain defaults: release both lines.  States below only ever pull low.
        clk_release: uint1_t = 1
        data_release: uint1_t = 1

        # Byte-complete pulse and value derived by the receive state machine below.
        rx_valid: uint1_t = 0
        rx_byte: uint8_t = rx_shift

        # Never let our receiver interpret device clocks used while transmitting.
        # During initialization we receive command ACKs and, after F2, the device ID.
        receiving: uint1_t = (
            (state == _ST_WAIT_FA) | (state == _ST_WAIT_ID) | (state == _ST_STREAM)
        )
        if receiving:
            if clk_fall:
                if rx_bit == 0:
                    # Start bit must be zero.  Ignore idle/noise falling edges.
                    if data_sync == 0:
                        rx_bit = 1
                        rx_shift = 0
                        rx_parity = 0
                        rx_parity_ok = 0
                elif rx_bit < 9:
                    # D0..D7 arrive LSB-first.  Shifting each new bit into bit 7
                    # yields the normal byte ordering after all eight samples.
                    rx_shift = concat(data_sync, rx_shift[7:1])
                    rx_parity = rx_parity ^ data_sync
                    rx_bit = rx_bit + 1
                elif rx_bit == 9:
                    # Odd parity: eight data bits plus parity bit contain odd 1s.
                    rx_parity_ok = rx_parity ^ data_sync
                    rx_bit = 10
                else:
                    # Stop bit is one.  rx_shift already contains the complete byte.
                    if rx_parity_ok & data_sync:
                        rx_valid = 1
                        rx_byte = rx_shift
                    rx_bit = 0
        else:
            rx_bit = 0

        timer_reset: uint1_t = 0
        timer_tick: uint1_t = 0

        # Minimal host initialization: repeatedly send F4 until the mouse returns the
        # normal command response 0xFA, then leave the bus entirely device-driven.
        if state == _ST_POWER_WAIT:
            ready = 0
            if power_expired:
                timer_reset = 1
                init_step = 0
                tx_byte = 243  # 0xF3 Set Sample Rate
                wheel_mode = 0
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_TX_INHIBIT:
            clk_release = 0
            if inhibit_expired:
                timer_reset = 1
                state = _ST_TX_RTS
            else:
                timer_tick = 1

        elif state == _ST_TX_RTS:
            clk_release = 0
            data_release = 0
            if setup_expired:
                timer_reset = 1
                state = _ST_TX_START
            else:
                timer_tick = 1

        elif state == _ST_TX_START:
            # Clock is released; Data low is the start bit.  After the device's first
            # falling edge, present D0 while Clock is low.
            data_release = 0
            if clk_fall:
                timer_reset = 1
                tx_bit = 0
                state = _ST_TX_BITS
            elif link_expired:
                timer_reset = 1
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_TX_BITS:
            # Commands and parameters are sent LSB-first.  Bit 8 supplies odd parity.
            if tx_bit == 0:
                data_release = tx_byte[0]
            elif tx_bit == 1:
                data_release = tx_byte[1]
            elif tx_bit == 2:
                data_release = tx_byte[2]
            elif tx_bit == 3:
                data_release = tx_byte[3]
            elif tx_bit == 4:
                data_release = tx_byte[4]
            elif tx_bit == 5:
                data_release = tx_byte[5]
            elif tx_bit == 6:
                data_release = tx_byte[6]
            elif tx_bit == 7:
                data_release = tx_byte[7]
            else:
                data_release = ~(
                    tx_byte[0] ^ tx_byte[1] ^ tx_byte[2] ^ tx_byte[3]
                    ^ tx_byte[4] ^ tx_byte[5] ^ tx_byte[6] ^ tx_byte[7]
                )

            if clk_fall:
                timer_reset = 1
                if tx_bit == 8:
                    state = _ST_TX_STOP_ACK
                else:
                    tx_bit = tx_bit + 1
            elif link_expired:
                timer_reset = 1
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_TX_STOP_ACK:
            # Releasing Data supplies the stop bit.  After the device samples it on a
            # rising edge, it pulls Data low for the link-layer ACK; observe that on
            # the following falling edge.
            if clk_fall:
                timer_reset = 1
                if data_sync == 0:
                    state = _ST_TX_RELEASE
                else:
                    state = _ST_TX_INHIBIT
            elif link_expired:
                timer_reset = 1
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_TX_RELEASE:
            if clk_sync & data_sync:
                timer_reset = 1
                rx_bit = 0
                state = _ST_WAIT_FA
            elif link_expired:
                timer_reset = 1
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_WAIT_FA:
            if rx_valid:
                timer_reset = 1
                if rx_byte == 250:  # 0xFA command acknowledge
                    # IntelliMouse wheel negotiation is the canonical sample-rate
                    # sequence 200, 100, 80 followed by F2 Read Device ID.  Every
                    # command byte and parameter byte is separately acknowledged.
                    if init_step == 0:
                        tx_byte = 200
                        init_step = 1
                        state = _ST_TX_INHIBIT
                    elif init_step == 1:
                        tx_byte = 243  # F3
                        init_step = 2
                        state = _ST_TX_INHIBIT
                    elif init_step == 2:
                        tx_byte = 100
                        init_step = 3
                        state = _ST_TX_INHIBIT
                    elif init_step == 3:
                        tx_byte = 243  # F3
                        init_step = 4
                        state = _ST_TX_INHIBIT
                    elif init_step == 4:
                        tx_byte = 80
                        init_step = 5
                        state = _ST_TX_INHIBIT
                    elif init_step == 5:
                        tx_byte = 242  # F2 Read Device ID
                        init_step = 6
                        state = _ST_TX_INHIBIT
                    elif init_step == 6:
                        state = _ST_WAIT_ID
                    else:
                        # F4 Enable Data Reporting has been acknowledged.
                        ready = 1
                        packet_byte = 0
                        state = _ST_STREAM
                else:
                    # Retry the current byte after an unexpected response.
                    state = _ST_TX_INHIBIT
            elif response_expired:
                timer_reset = 1
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        elif state == _ST_WAIT_ID:
            if rx_valid:
                timer_reset = 1
                # ID 3 is IntelliMouse wheel mode; accept ID 4 too in case a bridge
                # exposes the five-button extension.  ID 0 gracefully retains the
                # working classic three-byte packet format.
                wheel_mode = (rx_byte == 3) | (rx_byte == 4)
                tx_byte = 244  # F4 Enable Data Reporting
                init_step = 7
                state = _ST_TX_INHIBIT
            elif response_expired:
                # Failure to obtain an ID must not regress ordinary mouse support.
                timer_reset = 1
                wheel_mode = 0
                tx_byte = 244
                init_step = 7
                state = _ST_TX_INHIBIT
            else:
                timer_tick = 1

        else:  # _ST_STREAM
            ready = 1
            if rx_valid:
                if packet_byte == 0:
                    # Byte 0 bit 3 is always one; use it as a cheap packet resync.
                    if rx_byte[3]:
                        status = rx_byte
                        packet_byte = 1
                elif packet_byte == 1:
                    dx = rx_byte
                    packet_byte = 2
                elif packet_byte == 2:
                    dy = rx_byte

                    left = status[0]
                    right = status[1]
                    middle = status[2]

                    # Ignore overflowing movement axes; buttons still update.
                    if status[6] == 0:
                        if status[4]:
                            x_mag: uint9_t = 256 - dx
                            if x >= x_mag:
                                x = x - x_mag
                            else:
                                x = 0
                        else:
                            x_sum: uint13_t = x + dx
                            if x_sum > _MAX_X:
                                x = _MAX_X
                            else:
                                x = x_sum

                    # PS/2 positive Y is upward; VGA Y increases downward.
                    if status[7] == 0:
                        if status[5]:
                            y_mag: uint9_t = 256 - rx_byte
                            y_sum: uint13_t = y + y_mag
                            if y_sum > _MAX_Y:
                                y = _MAX_Y
                            else:
                                y = y_sum
                        else:
                            if y >= rx_byte:
                                y = y - rx_byte
                            else:
                                y = 0

                    if wheel_mode:
                        packet_byte = 3
                    else:
                        packet_byte = 0
                else:
                    # IntelliMouse Z is a signed four-bit two's-complement delta.
                    # Accumulate modulo 256 so every detent remains visible to a
                    # slow video consumer without needing a pulse stretcher.
                    z: uint4_t = rx_byte[3:0]
                    if z[3]:
                        z_mag: uint5_t = 16 - z
                        wheel = wheel - z_mag
                    else:
                        wheel = wheel + z
                    packet_byte = 0

        # One shared increment/reset path keeps arithmetic out of the state
        # selection muxes and preserves the original per-state timer behavior.
        if timer_reset:
            timer = 0
            power_expired = 0
            inhibit_expired = 0
            setup_expired = 0
            link_expired = 0
            response_expired = 0
        elif timer_tick:
            # Predict expiry for the next counter value using the old count.
            # Registering these flags removes timeout decoding from the
            # counter's increment/reset feedback path without adding a cycle.
            power_expired = timer >= (_POWER_WAIT_CYCLES - 2)
            inhibit_expired = timer >= (_INHIBIT_CYCLES - 2)
            setup_expired = timer >= (_RTS_SETUP_CYCLES - 2)
            link_expired = timer >= (_LINK_TIMEOUT_CYCLES - 2)
            response_expired = timer >= (_RESPONSE_TIMEOUT_CYCLES - 2)
            timer = timer + 1

        return ps2_mouse_io_t(
            clk_release=clk_release,
            data_release=data_release,
            x=out_x,
            y=out_y,
            left=out_left,
            middle=out_middle,
            right=out_right,
            wheel=out_wheel,
            wheel_mode=out_wheel_mode,
            ready=out_ready,
        )

    return ps2_mouse


# Keep the original 100 MHz, 640x480 interface for the standalone mouse demo.
ps2_mouse = make_ps2_mouse()
