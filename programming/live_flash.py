"""General live flash writes and optional device-owned reloads over JTAG.

The device arbitrates flash ownership and implements its own reload callback.
PyFtdi owns USB throughout programming; openFPGALoader uses a protected local
XVC relay. This module has no asset-format, flash-address or video knowledge.
"""
import time

from fpgatool import FPGAToolError
from programming.jtag_xvc import JtagRelay
from examples.hardware.live_flash_protocol import (
    MAGIC, BEGIN, RELOAD, RELEASE, READY, GRANTED, BUSY, ERROR, USER2, IR_BITS,
    DEFAULT_URL,
)


class Mailbox:
    def __init__(self, serial=None):
        self.serial = serial

    def __enter__(self):
        try:
            from pyftdi.jtag import JtagEngine
            from pyftdi.bits import BitSequence
            from pyftdi.ftdi import Ftdi
        except ImportError as exc:
            raise FPGAToolError('live uploads require PyFtdi: '
                'uv pip install --python .venv/bin/python pyftdi==0.57.1') from exc
        self.bits = BitSequence
        self.engine = JtagEngine(trst=False, frequency=3_000_000)
        url = DEFAULT_URL
        if self.serial:
            url = f'ftdi://0x0403:0x6010:{self.serial}/1'
        try:
            self.engine.configure(url)
            # Basys 3's Digilent cable also needs its JTAG buffer enable GPIOs.
            # Match openFPGALoader's digilent cable profile (low E8/EB, high 00/60).
            controller = self.engine._ctrl
            # Small JTAG reads otherwise wait for FTDI's default 16 ms USB
            # latency timer. Index scans perform hundreds of these transfers.
            controller._ftdi.set_latency_timer(1)
            controller.direction = 0xeb
            controller._ftdi.write_data(bytes((Ftdi.SET_BITS_LOW, 0xe8, 0xeb,
                                               Ftdi.SET_BITS_HIGH, 0x00, 0x60)))
            self.engine.reset()  # TAP reset only; never JPROGRAM/FPGA reset.
            self.read()  # Refuse an absent/incompatible bridge before any write.
        except Exception as exc:
            self.engine.close(freeze=True)
            raise FPGAToolError(f'cannot access resident live-flash bridge: {exc}') from exc
        return self

    def __exit__(self, *args):
        # read/send already leave the TAP idle. PyFtdi 0.57.1 rejects the
        # empty TMS sequence produced by a second go_idle() in that state.
        try:
            self.engine.sync()
        finally:
            # Keep the Digilent buffer-control pins stable across the USB
            # handoff to openFPGALoader and later mailbox connections.
            self.engine.close(freeze=True)

    def read(self):
        self.engine.write_ir(self.bits(USER2, length=IR_BITS))
        value = int(self.engine.read_dr(64))
        self.engine.go_idle()
        self.engine.sync()
        if value & 0xffffffff != MAGIC:
            raise FPGAToolError('running design has no compatible live-flash bridge '
                f'(USER2 signature 0x{value & 0xffffffff:08x}); '
                'load a design implementing the live-flash mailbox first')
        return value >> 32

    def send(self, command):
        self.engine.write_ir(self.bits(USER2, length=IR_BITS))
        self.engine.write_dr(self.bits((MAGIC << 32) | command, length=64))
        self.engine.go_idle()
        self.engine.sync()

    def wait(self, predicate, message, *, fail_on_error=False, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            status = self.read()
            if fail_on_error and status & ERROR:
                raise FPGAToolError('device rejected the data or failed to reload')
            if predicate(status):
                return status
            if time.monotonic() >= deadline:
                raise FPGAToolError(message)
            time.sleep(0.01)


def program_live_data(binary, program, *, reload=False, reload_timeout=3,
                      serial=None, mailbox_factory=Mailbox, relay_factory=JtagRelay):
    """Run a verified programmer callback under exclusive flash ownership.

    The caller checks board flash ranges. The device's RELOAD hook knows its
    own addresses and formats; no address/length is sent by this mailbox ABI.
    """
    if not binary.is_file() or binary.stat().st_size == 0:
        raise FPGAToolError('live upload requires a nonempty binary file')
    with mailbox_factory(serial) as mailbox:
        status = mailbox.read()
        if status & GRANTED:
            raise FPGAToolError('flash is already granted to an uploader; '
                               'finish or abort that upload first')
        status = mailbox.wait(lambda s: not s & BUSY, 'device is busy')
        generation = status >> 16
        mailbox.send(BEGIN)
        mailbox.wait(lambda s: bool(s & GRANTED), 'FPGA did not grant flash access')
        try:
            with relay_factory(mailbox.engine) as relay:
                program(relay.port)
        except BaseException:
            # Release without activating failed/unverified data.
            try:
                mailbox.send(RELEASE)
            except Exception:
                pass
            raise
        if reload:
            mailbox.send(RELOAD)
            expected = (generation + 1) & 0xffff
            mailbox.wait(lambda s: bool(s & READY) and not s & (BUSY | GRANTED)
                         and s >> 16 == expected,
                         'device did not acknowledge reload completion',
                         fail_on_error=True, timeout=reload_timeout)
        else:
            mailbox.send(RELEASE)
            mailbox.wait(lambda s: not s & (GRANTED | BUSY),
                         'device did not release flash ownership')
