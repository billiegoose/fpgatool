"""Mini-filesystem format, append-only semantics, and USER1 SPI-over-JTAG."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fpgatool
from programming.mini_filesystem import (
    COMMIT_VALUE, ENTRY_BYTES, HEADER_MAGIC, INDEX_HEADER_BYTES, PAGE_BYTES,
    STATUS_ACTIVE, JtagSpiFlash, MiniFileSystem, content_id, decode_entry,
    encode_entry, validate_name,
)

START = 0x220000
SECTOR = 0x10000
END = START + 3 * SECTOR


class MemoryFlash:
    def __init__(self):
        self.data = bytearray(b'\xff' * END)
        self.programs = []
        self.erases = []

    def read(self, address, length):
        assert START <= address <= END and address + length <= END
        return bytes(self.data[address:address + length])

    def program(self, address, data):
        assert START <= address < END and address + len(data) <= END
        assert (address % PAGE_BYTES) + len(data) <= PAGE_BYTES
        for i, b in enumerate(data):
            old = self.data[address + i]
            assert old & b == b, 'a program attempted a 0 -> 1 transition'
            self.data[address + i] = b
        self.programs.append((address, bytes(data)))

    def clear_bits(self, address, data):
        self.program(address, data)

    def erase_sector(self, address, size):
        assert size == SECTOR and address % SECTOR == 0
        assert START <= address < END
        self.data[address:address + size] = b'\xff' * size
        self.erases.append(address)


class FakeJtagEngine:
    """Simulate SPI bytes transmitted MSB-first through USER1 SHIFT_DR."""
    def __init__(self):
        self.memory = MemoryFlash()
        self.commands = []
        self.wren = False
        self.states = []

    def write_ir(self, bits):
        assert int(bits) == 0x02 and len(bits) == 6

    def change_state(self, state):
        assert state == 'shift_dr'
        self.states.append(state)

    def shift_and_update_register(self, bits):
        from pyftdi.bits import BitSequence
        tx = bytes(bits.tobytes(msb=True, msby=False))
        self.commands.append(tx)
        op = tx[0]
        rx = bytearray(len(tx))
        if op == 0x03:
            address = int.from_bytes(tx[1:4], 'big')
            rx[4:] = self.memory.read(address, len(tx) - 4)
        elif op == 0x05:
            rx[1] = 0
        elif op == 0x06:
            self.wren = True
        elif op == 0x02:
            assert self.wren
            self.wren = False
            address = int.from_bytes(tx[1:4], 'big')
            self.memory.program(address, tx[4:])
        elif op == 0xD8:
            assert self.wren
            self.wren = False
            address = int.from_bytes(tx[1:4], 'big')
            self.memory.erase_sector(address, SECTOR)
        else:
            raise AssertionError(f'unknown SPI opcode 0x{op:02x}')
        # USER1 samples MISO one bit before the matching SPI advancement.
        shifted = bytearray(len(rx))
        carry = 0x80
        for i, value in enumerate(rx):
            shifted[i] = (value >> 1) | carry
            carry = (value & 1) << 7
        return BitSequence(bytes_=bytes(shifted), msb=True, msby=True)

    def go_idle(self):
        self.states.append('idle')

    def sync(self):
        pass


class MiniFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.flash = MemoryFlash()
        self.fs = MiniFileSystem(self.flash, start=START, end=END, sector_size=SECTOR)

    def test_content_ids_are_native_blake2s_128(self):
        self.assertEqual(content_id(b'test'), hashlib.blake2s(b'test', digest_size=16).digest())
        self.assertNotEqual(content_id(b'test'), hashlib.blake2s(b'test', digest_size=32).digest()[:16])

    def test_record_layout_and_crc(self):
        raw = encode_entry(1, content_id(b'abc'), START + SECTOR, 3, b'hello.txt')
        self.assertEqual(len(raw), 64)
        self.assertEqual(raw[0], 1)
        self.assertEqual(raw[1:17], content_id(b'abc'))
        self.assertEqual(raw[17:20], (START + SECTOR).to_bytes(3, 'little'))
        self.assertEqual(raw[20:23], (3).to_bytes(3, 'little'))
        self.assertEqual(raw[23:32], b'hello.txt')
        self.assertEqual(raw[55], 9)
        self.assertEqual(raw[62:64], bytes((STATUS_ACTIVE, COMMIT_VALUE)))
        self.assertEqual(decode_entry(raw, 7).name, b'hello.txt')
        corrupt = bytearray(raw)
        corrupt[22] ^= 1
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'CRC'):
            decode_entry(bytes(corrupt), 7)
        corrupt[63] = 0xff
        self.assertIsNone(decode_entry(bytes(corrupt), 7))

    def test_append_update_alias_and_idempotency(self):
        first, changed = self.fs.add(b'hello world', 'hello.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(first.slot, 0)
        self.assertEqual(first.address, START + SECTOR)
        self.assertEqual(self.flash.read(START, len(HEADER_MAGIC)), HEADER_MAGIC)
        self.assertEqual(self.flash.erases, [])
        self.assertEqual(self.fs.read_index()[0], [first])
        same, changed = self.fs.add(b'hello world', 'hello.txt', 1)
        self.assertFalse(changed)
        self.assertEqual(first, same)
        alias, changed = self.fs.add(b'hello world', 'copy.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(alias.slot, 1)
        self.assertEqual(alias.address, first.address)
        updated, changed = self.fs.add(b'new version', 'hello.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(updated.slot, 2)
        self.assertNotEqual(updated.address, first.address)
        self.assertEqual(updated.address % PAGE_BYTES, 0)
        self.assertEqual(self.flash.erases, [])
        records = self.fs.read_index()[0]
        self.assertEqual([record.name for record in records],
                         [b'hello.txt', b'copy.txt', b'hello.txt'])
        self.assertEqual([record.active for record in records], [False, True, True])
        self.assertEqual(self.flash.read(START + INDEX_HEADER_BYTES + 62, 1), b'\xfd')

    def test_torn_entry_is_skipped_not_overwritten(self):
        self.fs.add(b'a', 'a.txt', 1)
        dead_slot = START + INDEX_HEADER_BYTES + ENTRY_BYTES
        self.flash.program(dead_slot, b'\x01' * 12)  # Torn/uncommitted index write.
        next_entry, changed = self.fs.add(b'b', 'b.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(next_entry.slot, 2)
        self.assertEqual(self.flash.read(dead_slot, 12), b'\x01' * 12)
        self.assertEqual([e.slot for e in self.fs.read_index()[0]], [0, 2])

    def test_erased_gap_does_not_hide_later_records_or_reuse_earlier_slots(self):
        self.fs.add(b'FIRST', 'first.txt', 1)
        late_address = START + SECTOR + PAGE_BYTES
        self.flash.program(late_address, b'LATE')
        late = encode_entry(1, content_id(b'LATE'), late_address, 4, b'late.txt')
        self.flash.program(START + INDEX_HEADER_BYTES + 8 * ENTRY_BYTES, late)
        entries, free_slot = self.fs.read_index()
        self.assertEqual([(entry.slot, entry.name) for entry in entries],
                         [(0, b'first.txt'), (8, b'late.txt')])
        self.assertEqual(free_slot, 9)
        created, _ = self.fs.add(b'NEXT', 'next.txt', 1)
        self.assertEqual(created.slot, 9)
        self.assertEqual(self.flash.read(START + INDEX_HEADER_BYTES + ENTRY_BYTES,
                                        7 * ENTRY_BYTES), b'\xff' * (7 * ENTRY_BYTES))

    def test_upload_scans_index_once_and_rechecks_it_on_each_operation(self):
        with patch.object(self.flash, 'read', wraps=self.flash.read) as read:
            for data in (b'first', b'replacement'):
                read.reset_mock()
                _, changed = self.fs.add(data, 'file.txt', 1)
                self.assertTrue(changed)
                self.assertEqual(sum(call.args == (START, SECTOR)
                                     for call in read.call_args_list), 1)
        self.assertEqual(self.flash.read(START, len(HEADER_MAGIC)), HEADER_MAGIC)

    def test_legacy_registration_scans_index_once_per_operation(self):
        fs = MiniFileSystem(self.flash, start=START + SECTOR, end=END,
                            sector_size=SECTOR, legacy_start=START)
        self.flash.program(START, b'LEGACY')
        with patch.object(self.flash, 'read', wraps=self.flash.read) as read:
            for name in ('first.bin', 'alias.bin'):
                read.reset_mock()
                _, changed = fs.register_existing(START, 6, name, 2)
                self.assertTrue(changed)
                self.assertEqual(sum(call.args == (START + SECTOR, SECTOR)
                                     for call in read.call_args_list), 1)
        self.assertEqual(self.flash.read(START, 6), b'LEGACY')

    def test_orphan_blob_pages_are_skipped_after_interruption(self):
        self.fs.add(b'a', 'a.txt', 1)
        # Flash page partially written, but no committed index entry.
        self.flash.program(START + SECTOR + PAGE_BYTES, b'X')
        next_entry, _ = self.fs.add(b'b', 'b.txt', 1)
        self.assertEqual(next_entry.address, START + SECTOR + 2 * PAGE_BYTES)

    def test_foreign_data_is_protected_until_explicit_format(self):
        self.flash.program(START, b'not a filesystem')
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'unrecognized'):
            self.fs.add(b'a', 'a.txt', 1)
        self.assertEqual(self.flash.erases, [])
        self.fs.format()
        self.assertEqual(self.flash.erases, [START])
        entry, _ = self.fs.add(b'a', 'a.txt', 1)
        self.assertEqual(entry.slot, 0)

    def test_empty_file_and_utf8_names(self):
        entry, changed = self.fs.add(b'', 'é.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(entry.length, 0)
        self.assertEqual(entry.name.decode(), 'é.txt')
        self.assertEqual(len(validate_name('é.txt')), 6)
        with self.assertRaisesRegex(fpgatool.FPGAToolError, '32 UTF-8 bytes'):
            validate_name('é' * 17)

    def test_jtag_spi_roundtrip_and_page_boundaries(self):
        engine = FakeJtagEngine()
        spi = JtagSpiFlash(engine)
        data = bytes(range(256)) + b'abc'
        spi.program(START + SECTOR, data)
        self.assertEqual(engine.commands[0], b'\x05' + bytes(11))
        self.assertEqual(spi.read(START + SECTOR, len(data)), data)
        programs = [cmd for cmd in engine.commands if cmd[0] == 0x02]
        self.assertEqual([len(cmd) - 4 for cmd in programs], [252, 4, 3])
        self.assertTrue(all(len(cmd) <= 256 for cmd in engine.commands))
        self.assertEqual(engine.memory.erases, [])
        self.assertTrue(all(engine.states[i + 1] == 'idle'
                            for i in range(0, len(engine.states), 2)))

    def test_register_existing_legacy_and_high_blob_without_rewriting_bytes(self):
        index_start = START + SECTOR
        fs = MiniFileSystem(self.flash, start=index_start, end=END,
                            sector_size=SECTOR, legacy_start=START)
        font = b'RFV2' + bytes(range(32))
        ebook = b'THE TINY E BOOK\n'
        ebook_address = START + 2 * SECTOR + 2 * PAGE_BYTES
        self.flash.program(START, font)
        self.flash.program(ebook_address, ebook)
        self.flash.programs.clear()

        registered_font, changed = fs.register_existing(
            START, len(font), 'RED2-Regular-v2.bin', 2,
            expected_digest=content_id(font))
        self.assertTrue(changed)
        self.assertEqual(registered_font.address, START)
        registered_ebook, changed = fs.register_existing(
            ebook_address, len(ebook), 'tiny_e_book.txt', 1,
            expected_digest=content_id(ebook))
        self.assertTrue(changed)
        self.assertEqual(registered_ebook.address, ebook_address)
        self.assertTrue(all(index_start <= address < index_start + SECTOR
                            for address, _ in self.flash.programs))
        self.assertEqual(self.flash.read(START, len(font)), font)
        self.assertEqual(self.flash.read(ebook_address, len(ebook)), ebook)
        writes_before_retry = len(self.flash.programs)
        repeated, changed = fs.register_existing(
            START, len(font), 'RED2-Regular-v2.bin', 2,
            expected_digest=content_id(font))
        self.assertFalse(changed)
        self.assertEqual(repeated, registered_font)
        self.assertEqual(len(self.flash.programs), writes_before_retry)

        # A legacy asset near the end must not move the new-data allocation
        # frontier forward. The first erased data page is still usable.
        created, changed = fs.add(b'new payload', 'new.txt', 1)
        self.assertTrue(changed)
        self.assertEqual(created.address, index_start + SECTOR)
        self.assertEqual(self.flash.read(ebook_address, len(ebook)), ebook)

    def test_register_existing_rejects_wrong_hash_and_index_overlap(self):
        index_start = START + SECTOR
        fs = MiniFileSystem(self.flash, start=index_start, end=END,
                            sector_size=SECTOR, legacy_start=START)
        self.flash.program(START, b'legacy')
        self.flash.programs.clear()
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'BLAKE2s-128'):
            fs.register_existing(START, 6, 'legacy.bin', 0,
                                 expected_digest=content_id(b'different'))
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'overlaps index'):
            fs.register_existing(index_start, 6, 'index.bin', 0)
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'overlaps index'):
            fs.register_existing(index_start - 2, 6, 'crossing.bin', 0)
        self.assertEqual(self.flash.programs, [])
        self.assertEqual(self.flash.erases, [])

    def test_index_reset_preserves_legacy_and_new_blob_bytes(self):
        index_start = START + SECTOR
        fs = MiniFileSystem(self.flash, start=index_start, end=END,
                            sector_size=SECTOR, legacy_start=START)
        self.flash.program(START, b'FONT')
        created, _ = fs.add(b'PAYLOAD', 'payload.bin', 0)
        self.assertEqual(created.address, index_start + SECTOR)
        fs.format()
        self.assertEqual(self.flash.erases, [index_start])
        self.assertEqual(self.flash.read(START, 4), b'FONT')
        self.assertEqual(self.flash.read(created.address, 7), b'PAYLOAD')
        self.assertEqual(fs.read_index(), ([], 0))

    def test_cli_program_file_dispatch_and_options(self):
        args = fpgatool.parser().parse_args(['program-file', 'a.txt', '--name', 'new.txt',
                                            '--type', 'text', '--format-filesystem'])
        self.assertEqual(args.command, 'program-file')
        self.assertTrue(args.format_filesystem)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'a.txt'
            path.write_bytes(b'hello')
            args.source = str(path)
            with patch('programming.mini_filesystem.program_live_file') as upload:
                entry = EntryForCli(content_id(b'hello'), START + SECTOR, 5)
                upload.return_value = (entry, True)
                fpgatool.cmd_program_file(args)
                self.assertEqual(upload.call_args.kwargs['name'], 'new.txt')
                self.assertTrue(upload.call_args.kwargs['format_filesystem'])

    def test_live_upload_reload_noop_release_and_failure_cleanup(self):
        from programming.mini_filesystem import program_live_file
        from examples.hardware.live_flash_protocol import BEGIN, RELEASE, RELOAD, READY, GRANTED, BUSY

        class FakeMailbox:
            def __init__(self):
                self.engine = object()
                self.status = READY | (9 << 16)
                self.events = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self.status
            def wait(self, predicate, message, **kwargs):
                if not predicate(self.status):
                    raise AssertionError(message)
                return self.status
            def send(self, opcode):
                self.events.append(opcode)
                generation = self.status >> 16
                if opcode == BEGIN:
                    self.status |= GRANTED | BUSY
                elif opcode == RELOAD:
                    self.status = READY | (((generation + 1) & 65535) << 16)
                elif opcode == RELEASE:
                    self.status = READY | (generation << 16)

        mailbox = FakeMailbox()
        board = {'flash': {'size_bytes': END, 'user_data_offset': START,
                           'erase_block_bytes': SECTOR}}
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'hello.txt'
            source.write_bytes(b'hello')
            with patch('programming.live_flash.Mailbox', return_value=mailbox), \
                 patch('programming.mini_filesystem.JtagSpiFlash', return_value=self.flash):
                first, changed = program_live_file(source, board=board,
                                                   name='hello.txt', object_type=1)
                self.assertTrue(changed)
                self.assertEqual(mailbox.events, [BEGIN, RELOAD])
                self.assertEqual(mailbox.status, READY | (10 << 16))
                self.assertEqual(first.address, START + SECTOR)

                mailbox.events.clear()
                same, changed = program_live_file(source, board=board,
                                                  name='hello.txt', object_type=1)
                self.assertFalse(changed)
                self.assertEqual(same, first)
                self.assertEqual(mailbox.events, [BEGIN, RELEASE])
                self.assertEqual(mailbox.status, READY | (10 << 16))

                source.write_bytes(b'changed')
                mailbox.events.clear()
                with patch.object(self.flash, 'program', side_effect=RuntimeError('SPI write failed')):
                    with self.assertRaisesRegex(RuntimeError, 'SPI write failed'):
                        program_live_file(source, board=board,
                                          name='hello.txt', object_type=1)
                self.assertEqual(mailbox.events, [BEGIN, RELEASE])
                self.assertEqual(mailbox.status, READY | (10 << 16))


class EntryForCli:
    def __init__(self, digest, address, length):
        self.content_id = digest
        self.address = address
        self.length = length


if __name__ == '__main__':
    unittest.main()
