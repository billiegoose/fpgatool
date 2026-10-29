"""Register physically verified legacy Basys 3 assets in the new MFS1 index.

Dry-run by default. --commit writes only index records at 0x240000; it never
programs or erases any legacy blob sector. Run with the updated FPGA design.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from fpgatool import FPGAToolError, board_config
from programming.mini_filesystem import (
    JtagSpiFlash, MiniFileSystem, TYPE_NAMES, content_id,
)
from programming.live_flash import Mailbox
from examples.hardware.live_flash_protocol import (
    BEGIN, RELEASE, RELOAD, READY, GRANTED, BUSY,
)


@dataclass(frozen=True)
class LegacyBlob:
    name: str
    kind: str
    address: int
    length: int
    digest: str


# Addresses, lengths and hashes obtained by read-only physical flash probes.
# The scene's length is inferred from its final non-0xff byte. Its historical
# serialization format has not yet been identified independently.
LEGACY_BLOBS = (
    LegacyBlob('RED2-Regular-v2.bin', 'font', 0x220000, 4256,
               '57598c8276f2482a16195479e417738b'),
    LegacyBlob('legacy-scene.bin', 'scene', 0x230000, 37590,
               'd93b6485cb677ccf15a050e475279c05'),
    LegacyBlob('tiny_e_book.txt', 'text', 0x3e0000, 497,
               'a140fda45ea7df781189c92964780287'),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', action='store_true',
                        help='append verified metadata to flash index at 0x240000')
    parser.add_argument('--ftdi-serial', help='select a Digilent FTDI adapter')
    parser.add_argument('--reload-timeout', type=float, default=10.0)
    args = parser.parse_args(argv)

    board = board_config('basys3')
    config = board['flash']
    index_start = int(config['filesystem_index_offset'])
    legacy_start = int(config['user_data_offset'])
    if index_start != 0x240000 or legacy_start != 0x220000:
        raise FPGAToolError('unexpected Basys 3 flash layout; refusing migration')

    with Mailbox(args.ftdi_serial) as mailbox:
        status = mailbox.read()
        if status & GRANTED:
            raise FPGAToolError('flash already granted to another uploader')
        status = mailbox.wait(lambda s: not s & BUSY, 'device is busy')
        generation = status >> 16
        mailbox.send(BEGIN)
        released = False
        try:
            mailbox.wait(lambda s: bool(s & GRANTED),
                         'device did not grant flash ownership')
            flash = JtagSpiFlash(mailbox.engine)
            fs = MiniFileSystem(
                flash, start=index_start, end=int(config['size_bytes']),
                sector_size=int(config['erase_block_bytes']),
                legacy_start=legacy_start)
            entries, free_slot = fs.read_index()
            print(f'Index at 0x{index_start:06x}: {len(entries)} committed records, '
                  f'next slot {free_slot}')

            # Verify ALL source bytes before contemplating ANY persistent write.
            for blob in LEGACY_BLOBS:
                actual = content_id(flash.read(blob.address, blob.length)).hex()
                if actual != blob.digest:
                    raise FPGAToolError(
                        f'{blob.name} hash mismatch at 0x{blob.address:06x}: '
                        f'got {actual}, expected {blob.digest}; no metadata written')
                print(f'VERIFIED {blob.name}: {blob.length} bytes '
                      f'at 0x{blob.address:06x}, BLAKE2s-128 {actual}')

            if args.commit:
                changed_any = False
                for blob in LEGACY_BLOBS:
                    entry, changed = fs.register_existing(
                        blob.address, blob.length, blob.name,
                        TYPE_NAMES[blob.kind],
                        expected_digest=bytes.fromhex(blob.digest))
                    changed_any |= changed
                    print(f'{"REGISTERED" if changed else "ALREADY INDEXED"} '
                          f'{blob.name}: slot {entry.slot}')
                if changed_any:
                    mailbox.send(RELOAD)
                    expected_generation = (generation + 1) & 0xffff
                    mailbox.wait(
                        lambda s: bool(s & READY) and not s & (BUSY | GRANTED)
                        and s >> 16 == expected_generation,
                        'device did not acknowledge filesystem reload',
                        fail_on_error=True, timeout=args.reload_timeout)
                else:
                    mailbox.send(RELEASE)
                    mailbox.wait(lambda s: not s & (GRANTED | BUSY),
                                 'flash release timed out')
                released = True
                print('Metadata import complete; existing blob data untouched.')
            else:
                mailbox.send(RELEASE)
                mailbox.wait(lambda s: not s & (GRANTED | BUSY),
                             'flash release timed out')
                released = True
                print('DRY RUN COMPLETE: no flash bytes programmed or erased.')
                print('Before --commit, confirm the relocated-index FPGA design is loaded.')
        finally:
            if not released:
                try:
                    mailbox.send(RELEASE)
                except Exception:
                    pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
