"""MFS1 hardware lookup uses real host records and never exposes raw addresses."""
import unittest
import struct
from unittest.mock import patch

import pypeline as p
from hardware import mini_filesystem as fs
from hardware import QSPI
from hardware.qspi_burst import read_burst, qspi_burst_t
from programming.mini_filesystem import content_id, encode_entry, HEADER_MAGIC


def pins(**overrides):
    values = dict(cclk=0, cs_n=1, dq0=0, dq0_t=1, dq1=1, dq1_t=1,
                  dq2=1, dq2_t=1, dq3=1, dq3_t=1, read_data=0, ready=1,
                  busy=0, done=0, error=0, quad_enabled=1,
                  quad_activity=0, quad_write_activity=0)
    values.update(overrides)
    return QSPI.qspi_flash_byte_io_t(**values)


class FileReaderWireTests(unittest.TestCase):
    def test_startup_adapter_uses_single_spi_and_preserves_configuration(self):
        import inspect
        timers = dict(_BYTE_POWERUP_CYCLES=4, _HALF_PERIOD_CYCLES=2,
                      _STARTUP_PRIME_CYCLES=2, _BYTE_NORMAL_CS_HIGH_CYCLES=2,
                      _BYTE_RECOVERY_CS_HIGH_CYCLES=2, _BYTE_RES_CYCLES=2)
        body = inspect.getclosurevars(QSPI.flash_byte_io).nonlocals['_run_body']
        simulation = inspect.getclosurevars(body).nonlocals['sim_body_fn']
        with patch.dict(simulation.__globals__, timers):
            for initial_config in (0x80, 0x82):
                with self.subTest(initial_config=initial_config):
                    p.sim_reset()
                    config, status, dq = initial_config, 0x1c, 0
                    previous_clock, previous_cs = 0, 1
                    bits = raw = command = 0
                    transactions = []
                    for _ in range(5000):
                        bus = p.sim_call(fs.initialize_quad, dq, 0)
                        self.assertEqual(tuple(map(int, (bus.dq0_t, bus.dq1_t, bus.dq2_t, bus.dq3_t))),
                                         (0, 1, 0, 0))
                        self.assertEqual((int(bus.dq2), int(bus.dq3)), (1, 1))
                        if previous_cs and not bus.cs_n:
                            bits = raw = command = 0
                        if not previous_clock and bus.cclk and not bus.cs_n:
                            raw = (raw << 1) | int(bus.dq0)
                            bits += 1
                            if bits == 8:
                                command = raw
                        if previous_clock and not bus.cclk and not bus.cs_n and bits >= 8:
                            response = status if command == 0x05 else config if command == 0x35 else 0
                            dq = ((response >> (7 - ((bits - 8) & 7))) & 1) << 1
                        if not previous_cs and bus.cs_n:
                            transactions.append((command, bits, raw))
                            if command == 0x01:
                                self.assertEqual(bits, 24)
                                self.assertEqual((raw >> 8) & 255, status)
                                config = raw & 255
                        if bus.ready:
                            self.assertTrue(bus.quad_enabled)
                            self.assertFalse(bus.error)
                            self.assertEqual(config, 0x82)
                            writes = [item for item in transactions if item[0] == 0x01]
                            self.assertEqual(len(writes), int(initial_config == 0x80))
                            break
                        previous_clock, previous_cs = int(bus.cclk), int(bus.cs_n)
                    else:
                        self.fail('SPI startup did not enable quad reads')

    def test_registered_bus_preserves_every_field_and_starts_released(self):
        p.sim_reset()
        previous = pins(busy=1, ready=0, quad_enabled=0)
        for cycle in range(20):
            current = QSPI.qspi_flash_byte_io_t(*(
                ((cycle * 13 + i) & 255) if name == 'read_data' else ((cycle + i) & 1)
                for i, name in enumerate(QSPI.qspi_flash_byte_io_t._fields)))
            out = p.sim_call(fs.registered_flash_bus, current)
            self.assertEqual(tuple(map(int, out)), tuple(map(int, previous)))
            previous = current

    def test_filename_and_payload_through_registered_physical_spi_edges(self):
        p.sim_reset()
        memory = bytearray(b'\xff' * fs.FLASH_END)
        memory[fs.INDEX_START:fs.INDEX_START + len(HEADER_MAGIC)] = HEADER_MAGIC
        payload = bytes([0x12, 0xa5, 0, 0xff, 0x37])
        record = encode_entry(2, content_id(payload), fs.DATA_START, len(payload), b'font.bin')
        memory[fs.INDEX_START + 256:fs.INDEX_START + 320] = record
        memory[fs.DATA_START:fs.DATA_START + len(payload)] = payload
        slots = patch.object(fs, 'INDEX_ENTRIES', 1)
        slots.start()
        self.addCleanup(slots.stop)
        reader = fs.make_file_reader('font.bin', initialize_flash=False)
        previous_clock, previous_cs = 0, 1
        edges = command = dq = delay = pending_dq = 0
        requests, received = [], bytearray()
        started = opened = False
        for cycle in range(15000):
            if delay:
                delay -= 1
                if not delay:
                    dq = pending_dq
            start = int(opened and not started) if cycle else 0
            started |= bool(start)
            out = p.sim_call(reader, dq, int(cycle == 0), start, 0, len(payload), 0)
            opened = bool(out.opened and not out.busy)
            bus = out.flash
            if previous_cs and not bus.cs_n:
                edges = command = 0
            if not previous_clock and bus.cclk:
                if edges < 40:
                    command = (command << 1) | int(bus.dq0)
                else:
                    self.assertEqual(tuple(map(int, (bus.dq0_t, bus.dq1_t, bus.dq2_t, bus.dq3_t))),
                                     (1, 1, 1, 1))
                edges += 1
                if edges == 40:
                    self.assertEqual(command >> 32, 0x6b)
                    requests.append((command >> 8) & 0xffffff)
            if previous_clock and not bus.cclk and not bus.cs_n and edges >= 40:
                nibble = edges - 40
                byte = memory[requests[-1] + nibble // 2]
                pending_dq = (byte >> (0 if nibble & 1 else 4)) & 15
                delay = 2  # Model flash output settling after the falling edge.
            if out.valid:
                received.append(int(out.data))
            self.assertFalse(out.error)
            if out.done:
                self.assertEqual(received, payload)
                self.assertEqual(requests, [fs.INDEX_START, fs.INDEX_START + 256, fs.DATA_START])
                self.assertTrue(bus.cs_n)
                break
            previous_clock, previous_cs = int(bus.cclk), int(bus.cs_n)
        else:
            self.fail('registered SPI filename read did not finish')


class FileReaderTests(unittest.TestCase):
    def test_layout_matches_the_basys3_board_profile(self):
        from fpgatool import board_config
        flash = board_config('basys3')['flash']
        self.assertEqual(fs.INDEX_START, flash['filesystem_index_offset'])
        self.assertEqual(fs.LEGACY_START, flash['user_data_offset'])
        self.assertEqual(fs.DATA_START, fs.INDEX_START + flash['erase_block_bytes'])
        self.assertEqual(fs.FLASH_END, flash['size_bytes'])
        # setUp shortens only the simulated journal; verify the physical
        # sector capacity independently of that simulation fixture.
        self.assertEqual((flash['erase_block_bytes'] - fs.INDEX_HEADER_BYTES) // 64,
                         self.physical_index_entries)

    def setUp(self):
        p.sim_reset()
        self.memory = bytearray(b'\xff' * fs.FLASH_END)
        self.memory[fs.INDEX_START:fs.INDEX_START + len(HEADER_MAGIC)] = HEADER_MAGIC
        self.requests = []
        self.initializations = 0
        self.quad_enabled = True
        owner = self

        class Init:
            def __call__(self, *args):
                owner.initializations += 1
                return pins(quad_enabled=int(owner.quad_enabled))

        class Burst:
            def __init__(self):
                self.stream = None
                self.index = 0
                self.finishing = False

            def __call__(self, dq, start, address, length, abort):
                if abort:
                    self.stream = None
                    self.finishing = False
                elif start:
                    assert self.stream is None, 'overlapping physical reads'
                    address, length = int(address), int(length)
                    owner.requests.append((address, length))
                    self.stream = bytes(owner.memory[address:address + length])
                    self.index = 0
                    return qspi_burst_t(pins=pins(ready=0, busy=1), valid=0)
                elif self.stream is not None:
                    data = self.stream[self.index]
                    self.index += 1
                    if self.index == len(self.stream):
                        self.stream = None
                        self.finishing = True
                    return qspi_burst_t(pins=pins(read_data=data, ready=0, busy=1), valid=1)
                elif self.finishing:
                    self.finishing = False
                    return qspi_burst_t(pins=pins(done=1), valid=0)
                return qspi_burst_t(pins=pins(), valid=0)

        for function, model in ((QSPI.flash_byte_io, Init), (read_burst, Burst)):
            original = function._sim_model_cell.copy()
            self.addCleanup(lambda cell=function._sim_model_cell, original=original: cell.__setitem__(slice(None), original))
            p.sim_model(function)(model)
        # Exercise every slot of a small journal, including erased holes. The
        # synthesized Basys 3 reader uses all 1020 slots in the same state machine.
        self.physical_index_entries = fs.INDEX_ENTRIES
        self.slots = patch.object(fs, 'INDEX_ENTRIES', 8)
        self.slots.start()
        self.addCleanup(self.slots.stop)

    def entry(self, slot, name, data, address=0x250000, kind=2, status=255,
              committed=True, corrupt=False):
        raw = bytearray(encode_entry(kind, content_id(data), address, len(data),
                                     name.encode('utf-8'), committed=committed))
        raw[62] = status
        if corrupt:
            raw[1] ^= 1
        start = fs.INDEX_START + 256 + slot * 64
        self.memory[start:start + 64] = raw
        self.memory[address:address + len(data)] = data

    def tick(self, **kwargs):
        values = dict(open_request=0, start=0, offset=0, length=1, abort=0)
        values.update(kwargs)
        return p.sim_call(self.reader, 0, *values.values())

    def open(self, name):
        self.reader = fs.make_file_reader(name)
        return self.reopen()

    def reopen(self):
        self.tick(open_request=1)
        for _ in range(2000):
            out = self.tick()
            if not out.busy and (out.opened or out.error):
                return out
        self.fail('filename lookup timed out')

    def read(self, length, offset=0):
        self.tick(start=1, length=length, offset=offset)
        data = bytearray()
        for _ in range(length + 20):
            out = self.tick()
            if out.valid:
                data.append(int(out.data))
            if out.done or out.error:
                return bytes(data), out
        self.fail('file read timed out')

    def test_newest_record_after_hole_wins_and_torn_or_bad_crc_records_are_skipped(self):
        self.entry(0, 'font.bin', b'OLD', address=0x220000)
        self.entry(2, 'other.bin', b'OTHER', address=0x260000)
        self.entry(4, 'font.bin', b'NEW', address=0x270000)
        self.entry(5, 'font.bin', b'TORN', address=0x280000, committed=False)
        self.entry(6, 'font.bin', b'BAD', address=0x290000, corrupt=True)
        out = self.open('font.bin')
        self.assertTrue(out.opened)
        self.assertEqual((out.length, out.object_type), (3, 2))
        data, out = self.read(3)
        self.assertEqual(data, b'NEW')
        self.assertFalse(out.error)
        self.assertEqual(self.requests[-1], (0x270000, 3))

    def test_all_32_filename_bytes_and_padding_are_compared(self):
        import zlib
        name = '0123456789abcdef' * 2
        self.entry(0, name, b'OLD')
        self.entry(1, name[:-1] + 'x', b'NEW', address=0x260000)
        self.assertTrue(self.open(name).opened)
        self.assertEqual(self.read(3)[0], b'OLD')
        p.sim_reset()
        name = 'f' * 31
        self.entry(2, name, b'YES', address=0x270000)
        self.entry(3, name, b'BAD', address=0x280000)
        start = fs.INDEX_START + 256 + 3 * 64
        self.memory[start + 54] = 0  # CRC-valid but noncanonical name padding.
        struct.pack_into('<I', self.memory, start + 58,
                         zlib.crc32(self.memory[start:start + 58]))
        self.assertTrue(self.open(name).opened)
        self.assertEqual(self.read(3)[0], b'YES')

    def test_handle_is_stable_until_reopen_and_reads_are_bounded(self):
        self.entry(0, 'font.bin', b'ABCDE')
        self.open('font.bin')
        requests = len(self.requests)
        self.entry(1, 'font.bin', b'12345', address=0x260000)
        self.assertEqual(self.read(3, offset=1)[0], b'BCD')
        self.assertEqual(len(self.requests), requests + 1)
        self.reopen()
        self.assertEqual(self.read(5)[0], b'12345')
        requests = len(self.requests)
        data, out = self.read(5, offset=1)
        self.assertTrue(out.error)
        self.assertEqual(data, b'')
        self.assertEqual(len(self.requests), requests)

    def test_deleted_superseded_and_invalid_locations_hide_older_names(self):
        for status, address, size in ((254, 0x260000, 3), (253, 0x260000, 3),
                                      (255, 0x240000, 3), (255, 0x23ffff, 3),
                                      (255, 0x3fffff, 3)):
            with self.subTest(status=status, address=address):
                p.sim_reset()
                self.entry(0, 'font.bin', b'OLD', address=0x220000)
                # Write metadata only: the rejected blob must not alter header/index.
                raw = bytearray(encode_entry(2, content_id(b'bad'), address, size, b'font.bin'))
                raw[62] = status
                start = fs.INDEX_START + 256 + 64
                self.memory[start:start + 64] = raw
                out = self.open('font.bin')
                self.assertTrue(out.error)
                self.assertFalse(out.opened)

    def test_invalid_header_and_missing_name_do_not_fall_back_to_raw_font(self):
        self.memory[0x220000:0x220004] = b'RFV2'
        out = self.open('font.bin')
        self.assertTrue(out.error)
        self.assertFalse(out.opened)
        self.memory[fs.INDEX_START] = 0
        self.requests.clear()
        self.reopen()
        self.assertEqual(self.requests, [(fs.INDEX_START, 256)])

    def test_case_sensitive_utf8_name_and_empty_file(self):
        self.entry(0, 'éFONT.bin', b'', address=0x220000)
        self.assertTrue(self.open('éFONT.bin').opened)
        requests = len(self.requests)
        data, out = self.read(0)
        self.assertEqual(data, b'')
        self.assertTrue(out.done)
        self.assertEqual(len(self.requests), requests)
        self.assertTrue(self.open('éfont.bin').error)

    def test_abort_suppresses_pending_data_and_retains_handle(self):
        self.entry(0, 'font.bin', b'ABCDEF')
        self.open('font.bin')
        self.tick(start=1, length=6)
        for _ in range(4):
            self.tick()
        out = self.tick(abort=1)
        self.assertFalse(out.valid)
        self.assertFalse(out.done)
        self.tick()
        self.assertEqual(self.read(3)[0], b'ABC')

    def test_qe_failure_and_invalid_names(self):
        self.quad_enabled = False
        self.assertTrue(self.open('font.bin').error)
        self.assertEqual(self.requests, [])
        for name in ('', 'x' * 33, 'é' * 17, 'bad\0name'):
            with self.assertRaises(ValueError):
                fs.make_file_reader(name)

    def test_preinitialized_reader_does_not_reset_the_shared_flash_engine(self):
        self.entry(0, 'font.bin', b'ABC')
        self.reader = fs.make_file_reader('font.bin', initialize_flash=False)
        self.assertTrue(self.reopen().opened)
        self.assertEqual(self.read(3)[0], b'ABC')
        self.assertEqual(self.initializations, 0)

    def test_font_boot_and_reload_follow_the_filename_to_a_new_blob(self):
        from hardware.font_v2.loader import make_font_loader, DEFAULT_FONT_FILENAME
        from hardware import red2_font_v2_data as reference
        words = list(reference.FONT_HEADER_WORDS + reference.FONT_WORDS)
        original = struct.pack('<1064I', *words)
        self.entry(0, DEFAULT_FONT_FILENAME, original, address=0x220000)
        font = make_font_loader(DEFAULT_FONT_FILENAME)
        writes = []

        def tick(blank=0, reload=0, clear=0):
            out = p.sim_call(font, 0, blank, 0, reload, clear)
            if out.font.write_enable:
                writes.append((int(out.font.write_address), int(out.font.write_data)))
            return out

        for _ in range(12000):
            out = tick()
            if out.font.ready and not out.busy:
                break
        else:
            self.fail('font boot did not finish')
        self.assertEqual(writes, list(enumerate(words[40:])))
        self.assertEqual([a for a, n in self.requests if n == 4256], [0x220000] * 2)
        writes.clear()
        corrupt = bytearray(original)
        corrupt[-1] ^= 1
        self.entry(1, DEFAULT_FONT_FILENAME, corrupt, address=0x260000)
        tick(reload=1)
        for _ in range(6000):
            out = tick()
            if out.font.error and not out.busy:
                break
        else:
            self.fail('corrupt font preflight did not finish')
        self.assertTrue(out.font.ready)
        self.assertEqual(writes, [])
        tick(clear=1)
        words[14] = 9
        words[16] = 0
        words[16] = -sum(words) & 0xffffffff
        updated = struct.pack('<1064I', *words)
        self.entry(3, DEFAULT_FONT_FILENAME, updated, address=0x2a0000)
        tick(reload=1)
        for _ in range(6000):
            out = tick()
            self.assertTrue(out.font.ready, 'preflight changed the active font')
        self.assertEqual(writes, [])
        self.assertEqual([a for a, n in self.requests if n == 4256],
                         [0x220000, 0x220000, 0x260000, 0x2a0000])
        tick(blank=1)
        for _ in range(5000):
            out = tick()
            if out.font.ready and not out.busy:
                break
        else:
            self.fail('font copy did not finish')
        self.assertEqual(out.font.config.spacing, 9)
        self.assertEqual(writes, list(enumerate(words[40:])))
        self.assertEqual([a for a, n in self.requests if n == 4256],
                         [0x220000, 0x220000, 0x260000, 0x2a0000, 0x2a0000])
