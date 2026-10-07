#!/usr/bin/env python3
"""Send text or a file at 115200 8-N-1 using one configured serial connection."""
import argparse
import os
from pathlib import Path
import termios
import time


def send(port, payload, delay_ms=0):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0  # No input transformations or software flow control.
        attrs[1] = 0  # Preserve LF; no terminal output transformations.
        flow = getattr(termios, 'CRTSCTS', 0)
        attrs[2] = ((attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | flow))
                    | termios.CS8 | termios.CREAD | termios.CLOCAL)
        attrs[3] = 0  # No echo or canonical terminal processing.
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        if delay_ms:
            for byte in payload:
                os.write(fd, bytes([byte]))
                termios.tcdrain(fd)
                time.sleep(delay_ms / 1000)
        else:
            remaining = memoryview(payload)
            while remaining:
                count = os.write(fd, remaining)
                if count == 0:
                    raise OSError('Serial write made no progress')
                remaining = remaining[count:]
        termios.tcdrain(fd)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--text', help='ASCII text to send verbatim')
    source.add_argument('--file', type=Path, help='Send the exact bytes of this file')
    parser.add_argument('--newline', action='store_true', help='Append LF')
    parser.add_argument('--delay-ms', type=float, default=0,
                        help='Optional pause after each byte to diagnose continuous-stream issues')
    args = parser.parse_args()
    if args.delay_ms < 0:
        parser.error('--delay-ms must be nonnegative')
    try:
        payload = args.file.read_bytes() if args.file else args.text.encode('ascii')
        if args.newline:
            payload += b'\n'
        send(args.port, payload, args.delay_ms)
    except (OSError, termios.error, UnicodeError) as exc:
        parser.exit(1, f'UART send failed: {exc}\n')
    print(f'Sent {len(payload)} bytes at 115200 8-N-1 to {args.port}')


if __name__ == '__main__':
    main()
