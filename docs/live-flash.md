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

## Adding the hardware to a demo

Import `fpgatool_board.basys3.live_flash` and call its `service()` once per
application clock. It owns the physical QSPI outputs, STARTUPE2 clock routing,
USER1 SPI bridge, USER2 mailbox, USER4 compatibility response, ownership state
machine, status register, and generation counter. The font demo uses this same
module; there is no font dependency in the service.

```python
import fpgatool_board.basys3.live_flash as live_flash
from hardware.live_flash import live_flash_application_t

# Inside your clocked @hw_func, using your own loader/controller:
asset = load_asset(dq, live_flash.pause,
                   live_flash.reload_request, live_flash.clear_error)
live_flash.service(asset.flash, live_flash_application_t(
    ready=asset.ready,
    busy=asset.busy,
    quiescent=asset.quiescent,
    done=asset.done,
    error=asset.error))
```

`load_asset` above is an application-defined function. Its `flash` output uses
`hardware.QSPI.qspi_flash_byte_io_t`. Sample the four input pads through
`fpgatool_board.basys3.qspi.QspiDQ0_I` through `QspiDQ3_I`, as in the font demo.
The exported request wires connect the service to your loader without extra
top-level JTAG or pin-routing code. Instantiate one service, in one clock domain;
other logic must not drive those QSPI outputs or use its three USER chains.

| Signal | Application contract |
| --- | --- |
| `pause` | Stop starting flash transactions; finish any transaction already in flight. Remains asserted while the host owns flash. |
| `quiescent` | Acknowledge that all application flash users have stopped and will remain stopped while paused. The service also checks CS high and SCK low before granting. |
| `reload_request` | One-clock pulse after the host relinquishes ownership with RELOAD. Validate and activate your configured flash data. |
| `clear_error` | One-clock pulse on accepted BEGIN. Clear the previous update error so an upload can retry. |
| `ready` | Currently active application data is usable. May stay asserted during upload and preflight if cached data remains usable. |
| `busy` | Boot or activation is in progress. BEGIN is accepted only when this is clear; ordinary flash transfers can instead hold `quiescent` low. |
| `done` | One-clock pulse on successful activation, including initial boot. Increments generation modulo 65536. |
| `error` | Latched validation/activation failure; clear in response to `clear_error`. A failure must also finish application work and clear application `busy`. |

When using flash continuously, every client must observe `pause` and contribute
to `quiescent`. Return idle pins while quiescent. RELOAD drops host ownership
before application work starts; RELEASE resumes ordinary access without a reload
pulse. The service keeps protocol BUSY asserted until `done` or `error`, even
if the application takes a cycle to respond to the reload request.

The font loader only accesses flash during boot or reload, so its idle state is
already quiescent. It takes `reload_request` and `clear_error` directly and
reports its loading status, leaving all host commands outside the loader.
Its font-specific bounds checks, single-BRAM writes, and vblank scheduling stay
in `hardware/font_v2_loader.py`.

For another board, reuse `hardware/live_flash.py`, the application-independent
ownership/reload controller. Supply the board's mailbox, SPI bridge, and pin
routing around it, following `fpgatool_board/basys3/live_flash.py`. The existing
`jtag_flash.py` contains the low-level Xilinx primitive wrappers.

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
Before reporting success or sending RELOAD, `program-data` requires a completed
readback-verification transcript and rejects programmer error messages even
when openFPGALoader returns exit code zero. Verbose runs retain the same log
while streaming output. A failed upload releases ownership without reloading.
openFPGALoader connects only to a loopback XVC relay. The relay replaces cleanup
JSHUTDOWN/JPROGRAM instructions with BYPASS and refuses other configuration
instructions. This avoids both FTDI teardown changes and openFPGALoader 1.1.1's
unconditional reset after SPI programming despite `--skip-reset`.

The resident SPI bridge asserts CS on DRCK's falling edge during CAPTURE, after
BSCAN controls have settled and before the first SHIFT rising edge. Sampling
CAPTURE on the same rising edge can miss chip selection after placement changes.
The GHDL regression delays CAPTURE relative to DRCK to exercise this case.
Board validation must exercise USER1 flash readback and a verified upload/reload;
boot READY and a functioning USER2 mailbox alone do not test the SPI bridge.

The existing font-demo bitstream implements this contract unchanged. Host
generalization requires no FPGA rebuild. Interrupted hosts can leave ownership
granted; reconnect/recovery policy remains the application's responsibility.

Basys 3 validation on 2026-10-27 confirmed that a write-only update preserves
the active generation (6 → 6), while a subsequent `--live --reload` advances it
(6 → 7), retaining READY with GRANTED/BUSY/ERROR clear. Host tests also exercise
non-font data at another user-data address, device rejection, timeout, generation
wraparound, failed-program cleanup, and configuration-region protection.
