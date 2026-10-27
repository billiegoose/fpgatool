# Resident live flash programming

`program-data --live` writes arbitrary binary data without replacing or
resetting the FPGA design. A resident USER1 SPI bridge and USER2 ownership
mailbox are required. The host validates user-data flash ranges and verifies
the programmed bytes. It has no asset-specific address or file-size limits.

```sh
# Store data; keep the application's currently active data.
fpgatool program-data assets.bin --offset 0x300000 --live

# Also ask the design to validate and activate its stored data.
fpgatool program-data assets.bin --offset 0x300000 --live --reload

# Allow a longer device reload operation (default: three seconds).
fpgatool program-data assets.bin --live --reload --reload-timeout 10
```

The application owns its storage layout and reload operation. The current
mailbox carries no address, length or asset selector. A design may reload one
configured region, inspect an application manifest, or refresh several resources.
The caller must write the region expected by that design. The font demo's hook
loads the font at `0x220000`; its update command now needs **both `--live` and
`--reload`**. File content does not automatically select a reload handler.

## Ownership and activation contract

1. Host checks that the mailbox is idle and sends BEGIN.
2. Application completes its current flash transaction, prevents new ones,
   grants exclusive USER1 access, and acknowledges GRANTED.
3. Host erases/programs/verifies flash while the application runs.
4. Host sends RELEASE for a write-only update, or RELOAD after successful
   verification when `--reload` was requested. Programming failure attempts
   RELEASE and reports the original error; it never requests activation.
5. RELEASE returns flash to the application without activating stored data.
   RELOAD returns flash and invokes the application's reload state machine.
6. Successful RELOAD sets READY, clears BUSY/GRANTED/ERROR, and increments the
   16-bit generation counter. Failed validation/activation sets ERROR. The host
   reports device rejection or an acknowledgement timeout separately from
   successful flash verification.

The design decides how to keep running while flash is unavailable and when new
data becomes visible. Seamless activation needs an application-specific boundary
and enough time/buffering. The font demo preflights the image while rendering
from BRAM, waits for vblank, pauses BRAM reads, copies the payload, and publishes
new header registers with ready. A failed preflight preserves the old active
font; failure during the single-BRAM copy disables scanout until recovery.
The programmer does not promise vblank timing for arbitrary applications.

The producer/consumer validates asset meaning: a font's table bounds and row
indices differ from a palette's color count or an audio buffer's sample format.
The transport's readback verification checks that stored bytes match the file;
it does not prove the application can use them. A rejected image remains in
flash even when an application retains an older active copy in BRAM.

## Wire ABI and board transport

The `digilent-xc7-user2-v1` transport is selected in `[live_programming]` in the
board profile. The current physical implementation uses Digilent FTDI GPIOs,
an Artix-7 six-bit instruction register, and the protected XVC relay. Other
cables/FPGA instruction layouts need a transport implementation and profile.
Adding another asset type to a compatible design needs no host transport change.

USER1 supplies the openFPGALoader v1 SPI-over-JTAG interface. USER4 returns zero
for legacy bridge-version selection. USER2 (IR `0x03`) shifts 64 bits LSB first:

| Direction | Low 32 bits | High 32 bits |
| --- | --- | --- |
| Host command | Opcode: BEGIN=1, RELOAD=2, RELEASE=3; remaining bits zero | Signature `0x52464C32` |
| Captured response | Signature `0x52464C32` | Status |

The signature retains its original `RFL2` value for compatibility with already
loaded bitstreams; it identifies this protocol, not the contents being uploaded.
Status bits are READY=0, GRANTED=1, BUSY=2, ERROR=3; bits 16–31 contain generation.
Other bits are reserved. BUSY covers flash ownership and reload work. BEGIN
clears the previous update error to allow retry. RELEASE leaves generation
unchanged. Generation increments modulo 65536 on each successful RELOAD.
The mailbox request crosses into the application clock using a held command
and toggle synchronizer; refer to the Basys 3 `jtag_flash.py` wrapper.

PyFtdi owns USB throughout the operation and preserves GPIOs on close.
The host implementation lives in `programming/live_flash.py` and
`programming/jtag_xvc.py`; it contains no font compiler or validator.
openFPGALoader connects only to a loopback XVC relay. The relay replaces cleanup
JSHUTDOWN/JPROGRAM instructions with BYPASS and refuses other configuration
instructions. This avoids both FTDI teardown changes and openFPGALoader 1.1.1's
unconditional reset after SPI programming despite `--skip-reset`.

The existing font-demo bitstream implements this contract unchanged. Host
generalization requires no FPGA rebuild. Interrupted hosts can leave ownership
granted; reconnect/recovery policy remains the application's responsibility.

Basys 3 validation on 2026-10-27 confirmed that a write-only update preserves
the active generation (6 → 6), while a subsequent `--live --reload` advances it
(6 → 7), retaining READY with GRANTED/BUSY/ERROR clear. Host tests also exercise
non-font data at another user-data address, device rejection, timeout, generation
wraparound, failed-program cleanup, and configuration-region protection.
