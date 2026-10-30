#!/usr/bin/env python3
"""Serve Flash Atlas locally and capture Basys 3 flash through the resident bridge."""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fpgatool import FPGAToolError, board_config
from programming.live_flash import Mailbox
from programming.mini_filesystem import JtagSpiFlash
from examples.hardware.live_flash_protocol import BEGIN, RELEASE, READY, GRANTED, BUSY

FLASH_BYTES = 0x400000
CHUNK_BYTES = 0x4000


def capture_flash(destination, progress, *, serial=None, mailbox_factory=Mailbox,
                  flash_factory=JtagSpiFlash, size=FLASH_BYTES):
    """Read only; publish a complete file after ownership has been released.

    Keep RELEASE in the BEGIN cleanup scope, including a grant timeout. A read
    failure must not leave the application paused or expose a partial capture.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = None
    try:
        with mailbox_factory(serial) as mailbox:
            if mailbox.read() & GRANTED:
                raise FPGAToolError('Flash is owned by another operation; finish that operation first.')
            mailbox.wait(lambda s: bool(s & READY) and not s & BUSY,
                         'FPGA is not ready for a flash capture', fail_on_error=True)
            try:
                mailbox.send(BEGIN)
                mailbox.wait(lambda s: bool(s & GRANTED),
                             'FPGA did not grant flash access', fail_on_error=True)
                flash = flash_factory(mailbox.engine)
                with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.part',
                                                 delete=False) as output:
                    partial_path = Path(output.name)
                    for address in range(0, size, CHUNK_BYTES):
                        count = min(CHUNK_BYTES, size - address)
                        payload = flash.read(address, count)
                        if len(payload) != count:
                            raise FPGAToolError(f'Short flash read at 0x{address:06x}')
                        output.write(payload)
                        progress(address + count)
            except BaseException as original:
                try:
                    mailbox.send(RELEASE)
                    mailbox.wait(lambda s: not s & (BUSY | GRANTED),
                                 'FPGA did not release flash ownership', timeout=15)
                except Exception as cleanup:
                    raise FPGAToolError(f'{original}; flash release also failed: {cleanup}') from original
                raise
            else:
                mailbox.send(RELEASE)
                mailbox.wait(lambda s: not s & (BUSY | GRANTED),
                             'FPGA did not release flash ownership', timeout=15)
        os.replace(partial_path, destination)
        partial_path = None
    finally:
        if partial_path is not None:
            partial_path.unlink(missing_ok=True)


class CaptureBusy(Exception):
    pass


class DumpService:
    def __init__(self, output_dir, *, serial=None, capture=capture_flash):
        self.output_dir = Path(output_dir)
        self.serial = serial
        self.capture = capture
        self.lock = threading.Lock()
        self.jobs = {}
        self.worker = None
        self.closing = threading.Event()

    def start(self):
        with self.lock:
            if self.closing.is_set() or any(j['state'] == 'reading' for j in self.jobs.values()):
                raise CaptureBusy('A flash capture is already running.')
            # Keep a bounded status history; completed dump files remain on disk.
            if len(self.jobs) >= 8:
                del self.jobs[next(iter(self.jobs))]
            job_id = uuid4().hex
            stamp = datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d_%H-%M-%S')
            name = f'flash_dump_{stamp}_{job_id[:8]}.bin'
            job = {'id': job_id, 'state': 'reading', 'bytesRead': 0,
                   'totalBytes': FLASH_BYTES, 'fileName': name, 'error': None}
            self.jobs[job_id] = job
            self.worker = threading.Thread(target=self._run, args=(job_id,), name='flash-capture')
            self.worker.start()
            return dict(job)

    def _run(self, job_id):
        def progress(count):
            if self.closing.is_set():
                raise FPGAToolError('Capture cancelled because the server is stopping')
            with self.lock:
                self.jobs[job_id]['bytesRead'] = count
        with self.lock:
            name = self.jobs[job_id]['fileName']
        try:
            self.capture(self.output_dir / name, progress, serial=self.serial)
        except Exception as error:
            with self.lock:
                self.jobs[job_id].update(state='failed', error=str(error))
        else:
            with self.lock:
                self.jobs[job_id].update(state='complete', bytesRead=FLASH_BYTES)

    def status(self, job_id):
        with self.lock:
            return dict(self.jobs[job_id])

    def image_path(self, job_id):
        job = self.status(job_id)
        if job['state'] != 'complete':
            raise CaptureBusy('Flash capture is not complete.')
        return self.output_dir / job['fileName']

    def close(self):
        self.closing.set()
        if self.worker is not None:
            self.worker.join()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, service, **kwargs):
        self.service = service
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def local_request(self, *, mutation=False):
        # Only this loopback app may initiate board operations. Do not expose a
        # cross-origin API to arbitrary websites or trust a rebound Host name.
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        host = self.headers.get('Host')
        if host not in allowed or (mutation and self.headers.get('Origin') != f'http://{host}'):
            self.json_response(403, {'error': 'Flash capture is available only from this local app.'})
            return False
        return True

    def json_response(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.local_request(mutation=True):
            return
        if self.path != '/api/dump':
            self.json_response(404, {'error': 'Unknown API endpoint'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 1024 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected an empty JSON object')
            if json.loads(self.rfile.read(length)) != {}:
                raise ValueError('Capture takes no request parameters')
        except (ValueError, json.JSONDecodeError) as error:
            self.json_response(400, {'error': str(error)})
            return
        try:
            self.json_response(202, self.service.start())
        except CaptureBusy as error:
            self.json_response(409, {'error': str(error)})

    def do_GET(self):
        if not self.local_request():
            return
        path = urlsplit(self.path).path
        if not path.startswith('/api/'):
            super().do_GET()
            return
        match = re.fullmatch(r'/api/dump/([0-9a-f]{32})(/image)?', path)
        if not match:
            self.json_response(404, {'error': 'Unknown API endpoint'})
            return
        job_id, image = match.groups()
        try:
            if not image:
                self.json_response(200, self.service.status(job_id))
                return
            file_path = self.service.image_path(job_id)
        except KeyError:
            self.json_response(404, {'error': 'Unknown capture'})
            return
        except CaptureBusy as error:
            self.json_response(409, {'error': str(error)})
            return
        with file_path.open('rb') as source:
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(file_path.stat().st_size))
            self.send_header('Content-Disposition', f'attachment; filename="{file_path.name}"')
            self.end_headers()
            self.copyfile(source, self.wfile)

    def list_directory(self, path):
        self.send_error(404, 'Not found')
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--ftdi-serial', help='Select a Digilent FTDI adapter')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/filesystem-visualizer/dumps')
    args = parser.parse_args(argv)
    if int(board_config('basys3')['flash']['size_bytes']) != FLASH_BYTES:
        parser.error('Flash Atlas expects the Basys 3 4 MiB flash layout')
    service = DumpService(args.output_dir, serial=args.ftdi_serial)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, service=service))
    print(f'Flash Atlas: http://127.0.0.1:{server.server_port}/', flush=True)
    print(f'Captures: {args.output_dir.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == '__main__':
    main()
