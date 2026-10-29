"""Append-only content-addressed storage in Basys 3 user QSPI flash.

This is a *flash-format* module, not a general-purpose filesystem.  An entry
combines an immutable BLAKE2s-128 content ID and an optional mutable UTF-8 name.
The last committed entry for a name wins.  Flash writes use resident USER1
SPI-over-JTAG, without openFPGALoader's destructive sector erase.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
import zlib

from fpgatool import FPGAToolError


INDEX_HEADER_BYTES = 256
ENTRY_BYTES = 64
PAGE_BYTES = 256
HEADER_MAGIC = b'MFS1\x01\x40'
ERASED = 0xFF
STATUS_ACTIVE = 0xFF
STATUS_DELETED = 0xFE
STATUS_SUPERSEDED = 0xFD  # Clear bit 1 only after replacement has committed.
COMMIT_VALUE = 0x00
TYPE_NAMES = {'blob': 0, 'text': 1, 'font': 2, 'scene': 3}


@dataclass(frozen=True)
class Entry:
    slot: int
    object_type: int
    content_id: bytes
    address: int
    length: int
    name: bytes
    status: int = STATUS_ACTIVE

    @property
    def active(self) -> bool:
        return self.status == STATUS_ACTIVE


def content_id(data: bytes) -> bytes:
    """Version-one content identity: unkeyed BLAKE2s with 16-byte output."""
    return hashlib.blake2s(data, digest_size=16).digest()


def validate_name(name: str) -> bytes:
    if '\x00' in name:
        raise FPGAToolError('filenames cannot contain NUL')
    encoded = name.encode('utf-8')
    if len(encoded) > 32:
        raise FPGAToolError('filename must fit in 32 UTF-8 bytes')
    return encoded


def encode_entry(object_type: int, digest: bytes, address: int, length: int,
                 name: bytes, *, committed: bool = True) -> bytes:
    if not 0 <= object_type <= 254:
        raise ValueError('invalid object type')
    if len(digest) != 16 or not 0 <= address < 1 << 24 or not 0 <= length < 1 << 24:
        raise ValueError('invalid blob identity or location')
    if len(name) > 32:
        raise ValueError('filename exceeds 32 bytes')
    raw = bytearray(b'\xff' * ENTRY_BYTES)
    raw[0] = object_type
    raw[1:17] = digest
    raw[17:20] = address.to_bytes(3, 'little')
    raw[20:23] = length.to_bytes(3, 'little')
    raw[23:23 + len(name)] = name
    raw[55] = len(name)
    raw[58:62] = (zlib.crc32(raw[:58]) & 0xffffffff).to_bytes(4, 'little')
    raw[62] = STATUS_ACTIVE
    raw[63] = COMMIT_VALUE if committed else ERASED
    return bytes(raw)


def decode_entry(raw: bytes, slot: int) -> Entry | None:
    if len(raw) != ENTRY_BYTES:
        raise ValueError('index record must be 64 bytes')
    if raw == b'\xff' * ENTRY_BYTES:
        return None
    # Uncommitted (possibly torn) entries must never be reused.
    if raw[63] != COMMIT_VALUE:
        return None
    if int.from_bytes(raw[58:62], 'little') != zlib.crc32(raw[:58]) & 0xffffffff:
        raise FPGAToolError(f'index record {slot} has invalid CRC')
    name_len = raw[55]
    if name_len > 32 or raw[23 + name_len:55] != b'\xff' * (32 - name_len):
        raise FPGAToolError(f'index record {slot} has invalid filename padding')
    name = raw[23:23 + name_len]
    try:
        name.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise FPGAToolError(f'index record {slot} has invalid UTF-8 filename') from exc
    return Entry(slot, raw[0], raw[1:17], int.from_bytes(raw[17:20], 'little'),
                 int.from_bytes(raw[20:23], 'little'), name, raw[62])


class JtagSpiFlash:
    """SPI 1-1-1 commands over the resident USER1 JTAG bridge.

    CAPTURE_DR asserts the bridge's chip select before SHIFT_DR clocks data;
    RUNTEST/idle releases it. Both wire directions transmit MSB-first.
    """

    def __init__(self, engine):
        from pyftdi.bits import BitSequence
        self.engine = engine
        self.bits = BitSequence
        self._primed = False

    def exchange(self, tx: bytes) -> bytes:
        if not tx:
            return b''
        # STARTUPE2 consumes the first CCLK pulses after configuration.
        # Discard one harmless status transaction before the first real SPI
        # command; this also protects writes initiated immediately after load.
        if not self._primed:
            self._primed = True
            try:
                self.exchange(b'\x05' + bytes(11))
            except BaseException:
                self._primed = False
                raise
        self.engine.write_ir(self.bits(0x02, length=6))  # USER1
        self.engine.change_state('shift_dr')
        out = self.engine.shift_and_update_register(
            self.bits(bytes_=tx, msb=True, msby=True))
        self.engine.go_idle()
        self.engine.sync()
        # The PyFtdi default reverses byte order; preserve transfer order.
        return bytes(out.tobytes(msb=True, msby=False))

    def read(self, address: int, length: int) -> bytes:
        result = bytearray()
        while length:
            # The USER1 bridge leaves MISO one bit behind the JTAG sample
            # with the JTAG stream. Four command/address bytes leave room for
            # 251 payload bytes plus one lookahead byte in PyFtdi's 256-byte DR transfer.
            count = min(length, PAGE_BYTES - 5)
            tx = b'\x03' + address.to_bytes(3, 'big') + bytes(count + 1)
            sampled = self.exchange(tx)
            result.extend(((sampled[i] << 1) & 0xff) | (sampled[i + 1] >> 7)
                          for i in range(4, 4 + count))
            address += count
            length -= count
        return bytes(result)

    def _write_enable(self) -> None:
        self.exchange(b'\x06')

    def _wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            sampled = self.exchange(b'\x05\x00\x00')
            status = ((sampled[1] << 1) & 0xff) | (sampled[2] >> 7)
            if not status & 1:
                return
            if time.monotonic() >= deadline:
                raise FPGAToolError('QSPI flash did not become ready')
            time.sleep(0.001)

    def program(self, address: int, data: bytes) -> None:
        """Program erased bytes only; never implicitly erase a sector."""
        start = 0
        while start < len(data):
            pos = address + start
            count = min(PAGE_BYTES - pos % PAGE_BYTES, len(data) - start,
                        PAGE_BYTES - 4)
            part = data[start:start + count]
            current = self.read(pos, len(part))
            if current != b'\xff' * len(part):
                raise FPGAToolError(f'flash at 0x{pos:06x} is not erased; refusing overwrite')
            if part != b'\xff' * len(part):
                self._write_enable()
                self.exchange(b'\x02' + pos.to_bytes(3, 'big') + part)
                self._wait_ready(3)
            if self.read(pos, len(part)) != part:
                raise FPGAToolError(f'flash verify failed at 0x{pos:06x}')
            start += count

    def clear_bits(self, address: int, data: bytes) -> None:
        """Modify status bits in place without erasing or setting a zero bit."""
        if (address % PAGE_BYTES) + len(data) > PAGE_BYTES:
            raise ValueError('status update crosses a programming page')
        previous = self.read(address, len(data))
        if any(old & new != new for old, new in zip(previous, data)):
            raise FPGAToolError('status update would require an erase')
        self._write_enable()
        self.exchange(b'\x02' + address.to_bytes(3, 'big') + data)
        self._wait_ready(3)
        if self.read(address, len(data)) != data:
            raise FPGAToolError('status update readback verification failed')

    def erase_sector(self, address: int, sector_size: int) -> None:
        if address % sector_size:
            raise ValueError('sector erase address must be aligned')
        self._write_enable()
        self.exchange(b'\xd8' + address.to_bytes(3, 'big'))
        self._wait_ready(30)
        if self.read(address, sector_size) != b'\xff' * sector_size:
            raise FPGAToolError(f'sector erase verification failed at 0x{address:06x}')


class MiniFileSystem:
    """No RAM index required: scan one sector, append a 64-byte record."""

    def __init__(self, flash, *, start: int, end: int, sector_size: int,
                 legacy_start: int | None = None):
        self.flash = flash
        self.start = start
        self.legacy_start = start if legacy_start is None else legacy_start
        self.end = end
        self.sector_size = sector_size
        self.data_start = start + sector_size
        self.index_entries = (sector_size - INDEX_HEADER_BYTES) // ENTRY_BYTES
        if self.data_start >= end or start % sector_size or not 0 <= self.legacy_start <= start:
            raise FPGAToolError('filesystem needs one index sector and at least one data sector')

    def format(self) -> None:
        """Reset only the index sector; preserve legacy assets and immutable blob data."""
        self.flash.erase_sector(self.start, self.sector_size)
        self.flash.program(self.start, HEADER_MAGIC)

    def read_index(self) -> tuple[list[Entry], int | None]:
        raw = self.flash.read(self.start, self.sector_size)
        if raw == b'\xff' * self.sector_size:
            return [], 0  # New, completely erased partition index.
        if raw[:len(HEADER_MAGIC)] != HEADER_MAGIC:
            raise FPGAToolError('unrecognized data at filesystem index; --format-filesystem resets only the index sector')
        if raw[len(HEADER_MAGIC):INDEX_HEADER_BYTES] != b'\xff' * (INDEX_HEADER_BYTES - len(HEADER_MAGIC)):
            raise FPGAToolError('unsupported filesystem index header')
        entries = []
        next_slot = 0
        for slot in range(self.index_entries):
            record = raw[INDEX_HEADER_BYTES + slot * ENTRY_BYTES:
                         INDEX_HEADER_BYTES + (slot + 1) * ENTRY_BYTES]
            if record != b'\xff' * ENTRY_BYTES:
                next_slot = slot + 1
                parsed = decode_entry(record, slot)
                if parsed is not None:
                    if not ((self.data_start <= parsed.address < self.end and
                            parsed.address + parsed.length <= self.end) or
                            (self.legacy_start <= parsed.address < self.start and
                             parsed.address + parsed.length <= self.start)):
                        raise FPGAToolError(f'index record {slot} points outside data partition')
                    entries.append(parsed)
        return entries, next_slot if next_slot < self.index_entries else None

    def _empty_slot(self, slot: int) -> int:
        return self.start + INDEX_HEADER_BYTES + slot * ENTRY_BYTES

    def _find_erased_span(self, length: int, entries: list[Entry]) -> int:
        cursor = self.data_start
        # Allocate from the beginning of the new-data area. Existing objects
        # at high flash addresses must not force every upload after them.
        cursor = (cursor + PAGE_BYTES - 1) & ~(PAGE_BYTES - 1)
        size = (length + PAGE_BYTES - 1) & ~(PAGE_BYTES - 1)
        while cursor + size <= self.end:
            if any(entry.length and cursor < entry.address + entry.length and
                   entry.address < cursor + size for entry in entries):
                cursor += PAGE_BYTES
                continue
            if self.flash.read(cursor, size) == b'\xff' * size:
                return cursor
            cursor += PAGE_BYTES
        raise FPGAToolError('no erased space left for blob; garbage collection not implemented')

    def register_existing(self, address: int, length: int, name: str,
                          object_type: int, *, expected_digest: bytes | None = None
                          ) -> tuple[Entry, bool]:
        """Index verified bytes already in flash without modifying the blob.

        A legacy object must fit entirely before the index sector; an object
        in the new data area must fit entirely within the flash. Neither may
        overlap the index sector. Only the index header/journal is programmed.
        """
        encoded_name = validate_name(name)
        if not encoded_name:
            raise FPGAToolError('registering existing flash requires a filename')
        if not 0 <= object_type <= 254:
            raise ValueError('invalid object type')
        if length <= 0:
            raise FPGAToolError('existing blob must have a positive length')
        legacy_range = (self.legacy_start <= address < self.start and
                        address + length <= self.start)
        data_range = (self.data_start <= address < self.end and
                      address + length <= self.end)
        if not (legacy_range or data_range):
            raise FPGAToolError('existing blob overlaps index or lies outside allowed flash')
        if expected_digest is not None and len(expected_digest) != 16:
            raise ValueError('expected BLAKE2s-128 digest must be 16 bytes')

        entries, free_slot = self.read_index()
        digest = content_id(self.flash.read(address, length))
        if expected_digest is not None and digest != expected_digest:
            raise FPGAToolError(
                f'existing flash at 0x{address:06x} has BLAKE2s-128 '
                f'{digest.hex()}, expected {expected_digest.hex()}')

        latest = {}
        for entry in entries:
            if entry.name:
                latest[entry.name] = entry
        current = latest.get(encoded_name)
        if (current is not None and current.active and
                current.content_id == digest and current.address == address and
                current.length == length and current.object_type == object_type):
            return current, False
        if free_slot is None:
            raise FPGAToolError('filesystem index full; compaction not implemented')

        record_address = self._empty_slot(free_slot)
        if self.flash.read(self.start, self.sector_size) == b'\xff' * self.sector_size:
            self.flash.program(self.start, HEADER_MAGIC)
        record = encode_entry(object_type, digest, address, length, encoded_name)
        self.flash.program(record_address, record[:63])
        self.flash.program(record_address + 63, record[63:])
        if self.flash.read(record_address, ENTRY_BYTES) != record:
            raise FPGAToolError('existing-blob index record readback failed')
        if current is not None and current.active:
            self.flash.clear_bits(self._empty_slot(current.slot) + 62,
                                  bytes((STATUS_SUPERSEDED,)))
        return Entry(free_slot, object_type, digest, address, length, encoded_name), True

    def add(self, data: bytes, name: str, object_type: int) -> tuple[Entry, bool]:
        encoded_name = validate_name(name)
        if len(data) > self.end - self.data_start:
            raise FPGAToolError('file exceeds filesystem data capacity')
        digest = content_id(data)
        entries, free_slot = self.read_index()
        latest = {}
        for entry in entries:
            if entry.name:
                latest[entry.name] = entry
        current = latest.get(encoded_name) if encoded_name else None
        if current is not None and current.active and current.content_id == digest and current.object_type == object_type:
            return current, False
        if free_slot is None:
            raise FPGAToolError('filesystem index full; compaction not implemented')
        existing = next((entry for entry in entries if (entry.status & 1) and
                         entry.content_id == digest and entry.length == len(data)), None)
        if existing is not None:
            address = existing.address
        elif data:
            address = self._find_erased_span(len(data), entries)
            for pos in range(0, len(data), PAGE_BYTES):
                self.flash.program(address + pos, data[pos:pos + PAGE_BYTES])
            if content_id(self.flash.read(address, len(data))) != digest:
                raise FPGAToolError('BLAKE2s readback verification failed')
        else:
            address = self.data_start
        record_address = self._empty_slot(free_slot)
        # Initialize only an entirely blank index; never overwrite foreign data.
        if self.flash.read(self.start, self.sector_size) == b'\xff' * self.sector_size:
            self.flash.program(self.start, HEADER_MAGIC)
        record = encode_entry(object_type, digest, address, len(data), encoded_name)
        self.flash.program(record_address, record[:63])
        self.flash.program(record_address + 63, record[63:])
        if decode_entry(self.flash.read(record_address, ENTRY_BYTES), free_slot) is None:
            raise FPGAToolError('index record was not committed')
        if current is not None and current.active:
            # The replacement is already durable.  An interrupted status update
            # can at worst leave two visible journal entries, never lose the name.
            self.flash.clear_bits(self._empty_slot(current.slot) + 62,
                                  bytes((STATUS_SUPERSEDED,)))
        return Entry(free_slot, object_type, digest, address, len(data), encoded_name), True


def program_live_file(path: Path, *, board: dict, name: str, object_type: int,
                      format_filesystem: bool = False, serial: str | None = None,
                      reload_timeout: int = 3) -> tuple[Entry, bool]:
    """Upload through the resident proxy, then request cache invalidation."""
    from programming.live_flash import Mailbox
    from examples.hardware.live_flash_protocol import BEGIN, GRANTED, BUSY, READY, RELOAD, RELEASE

    data = path.read_bytes()
    validate_name(name)
    size = int(board['flash']['size_bytes'])
    legacy_start = int(board['flash']['user_data_offset'])
    start = int(board['flash'].get('filesystem_index_offset', legacy_start))
    sector = int(board['flash']['erase_block_bytes'])
    if len(data) > size - start - sector:
        raise FPGAToolError('file exceeds filesystem data capacity')
    with Mailbox(serial) as mailbox:
        status = mailbox.read()
        if status & GRANTED:
            raise FPGAToolError('flash is already granted to another uploader')
        status = mailbox.wait(lambda s: not s & BUSY, 'device is busy')
        generation = status >> 16
        mailbox.send(BEGIN)
        mailbox.wait(lambda s: bool(s & GRANTED), 'FPGA did not grant flash access')
        try:
            fs = MiniFileSystem(JtagSpiFlash(mailbox.engine), start=start, end=size,
                                sector_size=sector, legacy_start=legacy_start)
            if format_filesystem:
                fs.format()
            entry, changed = fs.add(data, name, object_type)
        except BaseException:
            try:
                mailbox.send(RELEASE)
            except Exception:
                pass
            raise
        if changed or format_filesystem:
            mailbox.send(RELOAD)
            expected = (generation + 1) & 65535
            mailbox.wait(lambda s: bool(s & READY) and not s & (BUSY | GRANTED)
                         and s >> 16 == expected,
                         'device did not acknowledge filesystem reload',
                         fail_on_error=True, timeout=reload_timeout)
        else:
            mailbox.send(RELEASE)
            mailbox.wait(lambda s: not s & (GRANTED | BUSY),
                         'device did not release flash ownership')
        return entry, changed
