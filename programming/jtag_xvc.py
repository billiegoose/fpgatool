"""Loopback XVC relay: keep Digilent GPIOs owned throughout live programming.

openFPGALoader's native FTDI destructor tri-states GPIOs and resets the cable,
even with --skip-reset. Its XVC client only closes a socket. Relay those JTAG
vectors through our existing PyFtdi connection, preserving the physical pins.
Protocol: https://github.com/Xilinx/XilinxVirtualCable#xvc-10-protocol
"""
import socket
import socketserver
import struct
import threading

from fpgatool import FPGAToolError


def receive(connection, size):
    data = bytearray()
    while len(data) < size:
        part = connection.recv(size-len(data))
        if not part:
            raise EOFError('XVC connection closed')
        data.extend(part)
    return bytes(data)


def shift(ftdi, length, tms, tdi):
    """Shift exact LSB-first vectors; sample TDO on TCK's rising edge.

    Single-clock TMS commands handle arbitrary TMS/TDI changes. Small batches
    keep both MPSSE FIFOs flowing without blocking on unread TDO bytes.
    """
    from pyftdi.ftdi import Ftdi
    result = bytearray((length+7)//8)
    for start in range(0, length, 256):
        end = min(start+256, length)
        commands = bytearray()
        for bit in range(start, end):
            index, offset = divmod(bit, 8)
            pins = ((tdi[index] >> offset) & 1) << 7 | ((tms[index] >> offset) & 1)
            commands.extend((Ftdi.RW_BITS_TMS_PVE_NVE, 0, pins))
        commands.append(Ftdi.SEND_IMMEDIATE)
        ftdi.write_data(commands)
        sampled = ftdi.read_data_bytes(end-start, 20)
        if len(sampled) != end-start:
            raise FPGAToolError('short USB read during live JTAG transfer')
        for bit, value in enumerate(sampled, start):
            result[bit//8] |= (value >> 7) << (bit%8)
    return bytes(result)


class LiveTap:
    """Preserve the application even on openFPGALoader 1.1.1's reset path.

    Xilinx::program calls reset() after program_spi(), unconditionally, despite
    --skip-reset. Substitute BYPASS for JSHUTDOWN/JPROGRAM before UPDATE_IR.
    All other instructions must be part of the resident bridge protocol.
    """
    transitions = ((1, 0), (1, 2), (3, 9), (4, 5), (4, 5), (6, 8),
                   (6, 7), (4, 8), (1, 2), (10, 0), (11, 12), (11, 12),
                   (13, 15), (13, 14), (11, 15), (1, 2))

    def __init__(self):
        self.state = 1  # Mailbox leaves the TAP in RUN_TEST_IDLE.
        self.instruction = 0
        self.suppressed = []

    def vectors(self, length, tms, tdi):
        modes, data, positions = bytearray(), bytearray(), []
        count = 0

        def append(mode, value):
            nonlocal count
            if count % 8 == 0:
                modes.append(0)
                data.append(0)
            modes[-1] |= mode << (count%8)
            data[-1] |= value << (count%8)
            count += 1

        for bit in range(length):
            mode, value = (tms[bit//8] >> (bit%8)) & 1, (tdi[bit//8] >> (bit%8)) & 1
            positions.append(count)
            if self.state == 10:  # CAPTURE_IR
                self.instruction = 1
            if self.state == 11:  # SHIFT_IR, six-bit Artix-7 instruction
                self.instruction = (self.instruction >> 1) | (value << 5)
                if mode and self.instruction in (0x0b, 0x0d):
                    self.suppressed.append(self.instruction)
                    # Keep SHIFT_IR for this clock, then overwrite the full IR
                    # with six ones before exiting. Extra TDO samples are
                    # discarded, so the client's requested vector is intact.
                    append(0, value)
                    for extra in range(6):
                        append(int(extra == 5), 1)
                    self.instruction = 0x3f
                elif mode and self.instruction not in (0x02, 0x03, 0x09, 0x23, 0x3f):
                    raise FPGAToolError(f'live JTAG refuses instruction 0x{self.instruction:02x}')
                else:
                    append(mode, value)
            else:
                append(mode, value)
            self.state = self.transitions[self.state][mode]
        return count, bytes(modes), bytes(data), positions

    def shift(self, ftdi, length, tms, tdi):
        count, modes, data, positions = self.vectors(length, tms, tdi)
        sampled = shift(ftdi, count, modes, data)
        result = bytearray((length+7)//8)
        for bit, position in enumerate(positions):
            result[bit//8] |= ((sampled[position//8] >> (position%8)) & 1) << (bit%8)
        return bytes(result)


class JtagRelay:
    def __init__(self, engine):
        self.engine = engine
        self.error = None
        self.tap = LiveTap()

    def __enter__(self):
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                connection = self.request
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                connection.settimeout(10)
                try:
                    while True:
                        command = bytearray()
                        while not command.endswith(b':'):
                            command.extend(receive(connection, 1))
                            if len(command) > 8:
                                raise FPGAToolError('invalid local XVC command')
                        if command == b'getinfo:':
                            connection.sendall(b'xvcServer_v1.0:2048\n')
                        elif command == b'settck:':
                            period, = struct.unpack('<I', receive(connection, 4))
                            frequency = owner.engine.controller.ftdi.set_frequency(
                                min(3_000_000, 1e9/max(period, 1)))
                            connection.sendall(struct.pack('<I', round(1e9/frequency)))
                        elif command == b'shift:':
                            length, = struct.unpack('<I', receive(connection, 4))
                            if not 1 <= length <= 16384:
                                raise FPGAToolError('invalid local XVC vector length')
                            size = (length+7)//8
                            tms, tdi = receive(connection, size), receive(connection, size)
                            connection.sendall(owner.tap.shift(owner.engine.controller.ftdi,
                                                               length, tms, tdi))
                        else:
                            raise FPGAToolError('unsupported local XVC command')
                except EOFError:
                    pass
                except Exception as exc:
                    owner.error = exc

        self.engine.sync()
        self.server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(0.05), daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        # The programmer changed TAP state outside JtagEngine's tracker.
        # Reset only the TAP; the application and all GPIO levels stay intact.
        self.engine.reset()
        if self.error is not None and args[0] is None:
            raise FPGAToolError(f'live JTAG relay failed: {self.error}') from self.error
