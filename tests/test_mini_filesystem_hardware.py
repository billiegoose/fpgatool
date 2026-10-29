"""Native Pypeline checks for the flash-backed UART mini-filesystem console."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

try:
    import pypeline as p
except ImportError:
    HAS_PYPELINE = False
else:
    HAS_PYPELINE = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
    import mini_filesystem_demo as demo
    from hardware.uart_rx import uart_rx_t
    from hardware.QSPI import qspi_flash_byte_io_t
    from programming.mini_filesystem import content_id, encode_entry


@unittest.skipUnless(HAS_PYPELINE, 'requires the pinned Pypeline runtime')
class MiniFilesystemHardwareTests(unittest.TestCase):
    def setUp(self):
        p.sim_reset()

    def test_reflected_crc32_matches_host(self):
        for value in (b'', b'MFS1', bytes(range(64)), b'\xff' * 58):
            crc = 0xffffffff
            for byte in value:
                crc = int(p.sim_call(demo.crc32_byte, p.uint32_t(crc), p.uint8_t(byte)))
            self.assertEqual((~crc) & 0xffffffff, zlib.crc32(value))

    def test_list_all_types_and_print_only_text(self):
        # A read-only SPI device with one-cycle read replies. It supplies the
        # same 64-byte records and raw blob bytes as the host writer.
        storage = {}
        entries = (
            encode_entry(1, content_id(b'ABC'), 0x230000, 3, b'hello.txt'),
            encode_entry(2, content_id(b'font'), 0x250100, 4, b'font.bin'),
            encode_entry(1, content_id(b'NEW'), 0x250000, 3, b'notes.txt'),
        )
        for slot, record in enumerate(entries):
            for index, byte in enumerate(record):
                storage[0x240100 + slot * 64 + index] = byte
        for offset, byte in enumerate(b'ABC'):
            storage[0x230000 + offset] = byte
        for offset, byte in enumerate(b'font'):
            storage[0x250100 + offset] = byte
        for offset, byte in enumerate(b'NEW'):
            storage[0x250000 + offset] = byte

        pending = [None]
        def fake_flash(dq, op, address, write_data, reset):
            ready, done, data = 1, 0, 0
            if pending[0] is not None:
                data = storage.get(pending[0], 255)
                pending[0] = None
                done = 1
            elif int(op) == 1:
                pending[0] = int(address)
                ready = 0
            return qspi_flash_byte_io_t(
                cclk=0, cs_n=1, dq0=0, dq0_t=1, dq1=1, dq1_t=1,
                dq2=1, dq2_t=1, dq3=1, dq3_t=1, read_data=data,
                ready=ready, busy=not ready, done=done, error=0,
                quad_enabled=0, quad_activity=0, quad_write_activity=0)

        accepted = 0
        output = bytearray()
        def tick(input_byte=None):
            nonlocal accepted
            received = uart_rx_t(data=p.uint8_t(input_byte or 0),
                                 valid=p.uint1_t(input_byte is not None))
            result = p.sim_call(demo.mini_fs_console, p.uint4_t(0), received,
                                p.uint1_t(0), p.uint1_t(0), p.uint8_t(accepted))
            next_seq = int(result.tx_seq)
            if next_seq != accepted:
                output.append(int(result.tx_data))
                accepted = next_seq

        def command(value):
            output.clear()
            for byte in value + b'\n':
                tick(byte)
            for _ in range(2000):
                tick()
            return bytes(output)

        with patch.object(demo.qspi_hw, 'flash_byte_io', side_effect=fake_flash):
            self.assertEqual(command(b'list'), b'hello.txt\nfont.bin\nnotes.txt\n')
            self.assertEqual(command(b'print hello.txt'), b'ABC\n')
            self.assertEqual(command(b'print notes.txt'), b'NEW\n')
            self.assertEqual(command(b'print font.bin'), b'?\n')
            self.assertEqual(command(b'print missing.txt'), b'?\n')


if __name__ == '__main__':
    unittest.main()
