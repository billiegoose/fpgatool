# Basys 3 mini-filesystem

This experimental, append-only user-flash store gives raw blobs immutable content IDs and optional mutable UTF-8 names. The Mac host calculates an unkeyed BLAKE2s digest with a **16-byte output** (BLAKE2s-128). Re-uploading identical content under a new name reuses the existing flash bytes; updating a name appends a new record and marks its previous record superseded. There is no garbage collection or index compaction.

## Bring up the UART reader

```sh
./fpgatool.sh build examples/mini_filesystem_demo.py --comb
./fpgatool.sh load build/basys3/mini_filesystem_demo/mini_filesystem_demo.bit
```

The FPGA must be running this design (or another compatible live-flash bridge and filesystem reload handler) before `program-file`. Connect to the Basys 3 USB-UART port at **115200 baud, 8-N-1**. End commands with Enter:

```text
list
print hello.txt
```

`list` emits the filenames of active text/blob/font/scene records, one name per line. `print NAME` streams the bytes only for an active `text` record; absent names and non-text objects produce `?`. The FPGA reads flash directly and does not cache the index. During an upload the resident JTAG proxy pauses new application flash transactions; after a verified upload it releases flash and acknowledges a filesystem reload without resetting the FPGA. The simple UART command interpreter is not designed for concurrent terminal commands during a scan or while printing.

## Upload files

```sh
# An erased index initializes automatically. No formatting required.
./fpgatool.sh program-file assets/hello.txt --name hello.txt --type text

# Later uploads append to that same index. Do not specify --format-filesystem.
./fpgatool.sh program-file assets/notes.txt --name notes.txt
./fpgatool.sh program-file assets/font.bin --name font.bin --type font

# Optional: select one FTDI adapter or extend the device reload acknowledgement timeout.
./fpgatool.sh program-file assets/notes.txt --ftdi-serial SERIAL --reload-timeout 10
```

`--format-filesystem` erases **only the 64 KiB index sector at `0x240000`**. It destroys the filename/content-ID journal, but does not erase existing blob bytes in other sectors. Those blobs become unindexed, and formatting does not reclaim their space. This option does not prompt before erasing; **never use it for ordinary uploads or after importing legacy records unless you deliberately want to discard the index**. An entirely erased index initializes automatically. `program-file` requests a filesystem reload after a changed upload. It uses the resident JTAG SPI bridge rather than openFPGALoader's implicit sector erases. Raw `program-data` can still destroy existing objects or index entries; avoid mixing raw writes and mini-filesystem allocations in overlapping areas.

Uploaded file paths can be outside the checkout. The default stored name is the local basename (maximum 32 **UTF-8 bytes**). Supported metadata types are `blob`, `text`, `font`, and `scene`; `text` is the default. Names are compared byte-for-byte (case-sensitive). There is no directory hierarchy, delete command, or rename command yet. Empty files are allowed.

## Register existing flash objects

The Basys 3 used for development already contains a RED2 font at `0x220000`, a legacy scene payload at `0x230000`, and `tiny_e_book.txt` at `0x3e0000`. Their full byte ranges and BLAKE2s-128 hashes were verified over USER1 JTAG without modifying flash. These objects can be **registered in place**: only the index sector receives new records; the original blob bytes are never copied or reprogrammed.

First build and load the updated `mini_filesystem_demo.py` reader, whose index starts at `0x240000`. Then preflight the import:

```sh
PYTHONPATH=. .venv/bin/python -m programming.import_legacy_flash
```

The default is a **read-only dry run**. It checks every existing blob against the expected hash, examines the index, and releases flash ownership without programming or erasing any bytes. Only after verifying the output, explicitly request the metadata writes:

```sh
PYTHONPATH=. .venv/bin/python -m programming.import_legacy_flash --commit
```

`--commit` verifies all three hashes before making any change, appends records with a final commit byte, and requests a live reload. Retries are idempotent. The scene is named `legacy-scene.bin` because its historical binary format has not been independently identified; its 37,590-byte length was inferred from the final programmed (non-`0xff`) byte. The four unrelated bytes at `0x3f0000` remain unmodified and unindexed.

## Version-one layout

Basys 3 has a 4 MiB flash. The first `0x220000` bytes remain reserved for the FPGA configuration image. Legacy raw objects occupy some later sectors. The mini-filesystem index has its own previously erased sector at `0x240000`; new blobs are allocated beginning at `0x250000`, skipping existing programmed or indexed ranges.

| Flash range | Use |
| --- | --- |
| `0x220000..0x23ffff` | Preserved legacy blob region; importable by verified index references |
| `0x240000..0x2400ff` | 256-byte index header; `MFS1` format/version signature |
| `0x240100..0x24ffff` | Append-only journal of 1,020 fixed 64-byte entries |
| `0x250000..0x3fffff` | New immutable blobs, allocated at 256-byte page boundaries while avoiding existing data |

Each 64-byte entry stores: type (1 byte), BLAKE2s-128 ID (16), blob address (3, little-endian), length (3, little-endian), filename (32, `0xff` padded), filename length (1), reserved (2), CRC32 of bytes 0–57 (4, little-endian), status (1), commit byte (1). The commit byte is programmed to zero **last**, after the blob and record bytes have been read back and verified. Status `0xff` means active, `0xfd` superseded, and `0xfe` reserved for deletion. Superseding an entry clears bits in place without erasing its sector; a failed upload does not activate unverified data.

On a retry, partially written but uncommitted journal records are skipped and never reused. Orphan blob pages can be bypassed. **There is no garbage collection**: resetting the index does not erase or reclaim blob bytes. Journal capacity is at most 1,020 committed/attempted slots. The new-data region spans 1.6875 MiB before subtracting existing blobs and allocation gaps. BLAKE2s digests provide content identity and deduplication, **not** authentication.

## Validation status

The relocated-index design and registered one-clock RELOAD acknowledgement have now been verified on physical Basys 3 hardware. The index at `0x240000` contains three committed legacy references, and all three original blob hashes were verified without altering their bytes. Physical UART `list` and `print` matched the imported index and ebook byte-for-byte; non-text and absent names were rejected correctly. The USER2 BEGIN/RELOAD handshake was also verified without writing flash: generation advanced from 0 to 1 while the FPGA kept running. The later coherent-status CDC build was routed (109.54 MHz against 100 MHz), loaded only into volatile SRAM, and passed that same no-write handshake and UART regression. USER1 read-only JEDEC returned `01 02 15`, and index readback matched the archived flash image. Four GHDL bridge tests and all 13 host mini-filesystem tests pass. The separate flash engine + JTAG bridge routed at 157.43 MHz against 100 MHz. External I/O and CDC timing signoff is still incomplete; see [flash, JTAG, and CDC timing audit](mini-filesystem-interface-timing.md) for the measured margins and precise limitations.
