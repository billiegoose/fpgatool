"""Live uploads must preserve GPIOs and filter programmer reset instructions."""
import socket
import struct
import unittest
from unittest.mock import Mock, patch

from fpgatool import FPGAToolError
from programming.jtag_xvc import JtagRelay, LiveTap, receive, shift


def pack(bits):
    return sum(int(bit) << i for i, bit in enumerate(bits)).to_bytes((len(bits)+7)//8, 'little')


def ir_scan(instruction):
    # IDLE -> SELECT_DR -> SELECT_IR -> CAPTURE_IR -> SHIFT_IR, then shift
    # six IR bits and go through UPDATE_IR back to IDLE.
    return [1, 1, 0, 0] + [0]*5 + [1, 1, 0], [0]*4 + [instruction >> i & 1 for i in range(6)] + [0, 0]


def instructions(modes, data, count):
    state, current, result = 1, 0, []
    for bit in range(count):
        mode, value = modes[bit//8] >> (bit%8) & 1, data[bit//8] >> (bit%8) & 1
        if state == 10:
            current = 1
        if state == 11:
            current = current >> 1 | value << 5
        state = LiveTap.transitions[state][mode]
        if state == 15:
            result.append(current)
    return result


class LiveJtagTests(unittest.TestCase):
    def test_reset_cleanup_is_bypassed_and_other_instructions_preserved(self):
        tap = LiveTap()
        modes, data = [], []
        wanted = [0x09, 0x23, 0x02, 0x0d, 0x0b, 0x3f, 0x03]
        for instruction in wanted:
            tms, tdi = ir_scan(instruction)
            modes.extend(tms)
            data.extend(tdi)
        count, safe_modes, safe_data, positions = tap.vectors(len(modes), pack(modes), pack(data))
        self.assertEqual(instructions(safe_modes, safe_data, count),
                         [0x09, 0x23, 0x02, 0x3f, 0x3f, 0x3f, 0x03])
        self.assertEqual(tap.suppressed, [0x0d, 0x0b])
        self.assertEqual(count, len(modes)+12)
        self.assertEqual(len(positions), len(modes))
        self.assertEqual(tap.state, 1)

    def test_fragmented_reset_instruction_and_tdo_alignment(self):
        tap = LiveTap()
        modes, data = ir_scan(0x0b)
        split = 7  # First half of the IR was clocked in a previous request.
        a = tap.vectors(split, pack(modes[:split]), pack(data[:split]))
        tail_modes, tail_data = modes[split:], data[split:]
        with patch('programming.jtag_xvc.shift', side_effect=lambda f, n, m, d: d):
            sampled = tap.shift(Mock(), len(tail_modes), pack(tail_modes), pack(tail_data))
        self.assertEqual(sampled, pack(tail_data))
        self.assertEqual(tap.suppressed, [0x0b])
        self.assertEqual(tap.state, 1)

    def test_configuration_instructions_are_refused(self):
        modes, data = ir_scan(0x05)  # CFG_IN must never reach a live design.
        with self.assertRaisesRegex(FPGAToolError, 'refuses instruction 0x05'):
            LiveTap().vectors(len(modes), pack(modes), pack(data))

    def test_mpsse_bit_order_and_fifo_batches(self):
        try:
            from pyftdi.ftdi import Ftdi
        except ImportError:
            self.skipTest('requires optional PyFtdi')
        ftdi = Mock()
        samples, sizes = [], []

        def write(commands):
            self.assertEqual(commands[-1], Ftdi.SEND_IMMEDIATE)
            batch = []
            for i in range(0, len(commands)-1, 3):
                self.assertEqual(tuple(commands[i:i+2]), (Ftdi.RW_BITS_TMS_PVE_NVE, 0))
                pins = commands[i+2]
                batch.append((((pins >> 7) ^ pins) & 1) << 7)
            sizes.append(len(batch))
            samples.append(bytes(batch))
        ftdi.write_data.side_effect = write
        ftdi.read_data_bytes.side_effect = lambda count, attempt: samples.pop(0)
        modes = [i%3 == 0 for i in range(513)]
        data = [i%5 == 0 for i in range(513)]
        self.assertEqual(shift(ftdi, 513, pack(modes), pack(data)),
                         pack([a ^ b for a, b in zip(modes, data)]))
        self.assertEqual(sizes, [256, 256, 1])

    def test_loopback_protocol_and_tap_resync_without_usb_close(self):
        engine = Mock()
        engine.controller.ftdi.set_frequency.return_value = 3_000_000
        with patch('programming.jtag_xvc.shift', side_effect=lambda f, n, m, d: d):
            with JtagRelay(engine) as relay:
                with socket.create_connection(('127.0.0.1', relay.port), timeout=2) as client:
                    for part in (b'get', b'info:'):
                        client.sendall(part)
                    info = b'xvcServer_v1.0:2048\n'
                    self.assertEqual(receive(client, len(info)), info)
                    client.sendall(b'settck:' + struct.pack('<I', 100))
                    self.assertEqual(struct.unpack('<I', receive(client, 4)), (333,))
                    client.sendall(b'shift:' + struct.pack('<I', 13) + b'\0\0' + b'\x59\x12')
                    self.assertEqual(receive(client, 2), b'\x59\x12')
        engine.controller.ftdi.set_frequency.assert_called_once_with(3_000_000)
        engine.reset.assert_called_once_with()
        engine.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
