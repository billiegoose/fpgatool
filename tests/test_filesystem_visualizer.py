"""Read-only capture ownership, atomic files, and the local visualizer API."""
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'filesystem_visualizer_server', ROOT / 'tools/filesystem-visualizer/server.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class FakeMailbox:
    def __init__(self, *, granted=False, grant_timeout=False, release_timeout=False):
        self.engine = object()
        self.status = backend.GRANTED if granted else backend.READY
        self.commands = []
        self.grant_timeout = grant_timeout
        self.release_timeout = release_timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.status

    def send(self, command):
        self.commands.append(command)
        if command == backend.BEGIN and not self.grant_timeout:
            self.status |= backend.GRANTED | backend.BUSY
        elif command == backend.RELEASE and not self.release_timeout:
            self.status &= ~(backend.GRANTED | backend.BUSY)

    def wait(self, predicate, message, **kwargs):
        if not predicate(self.status):
            raise backend.FPGAToolError(message)
        return self.status


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / 'capture.bin'

    def capture(self, mailbox, read, *, size=37):
        class Flash:
            def __init__(self, engine):
                self.engine = engine

            def read(self, address, count):
                return read(address, count)
        progress = []
        backend.capture_flash(self.destination, progress.append,
                              mailbox_factory=lambda serial: mailbox,
                              flash_factory=Flash, size=size)
        return progress

    def test_read_only_capture_publishes_after_release(self):
        mailbox = FakeMailbox()
        size = backend.CHUNK_BYTES + 7
        def read(address, count):
            self.assertTrue(mailbox.status & backend.GRANTED)
            self.assertFalse(self.destination.exists())
            return bytes([address % 251]) * count
        progress = self.capture(mailbox, read, size=size)
        self.assertEqual(mailbox.commands, [backend.BEGIN, backend.RELEASE])
        self.assertEqual(mailbox.status, backend.READY)
        self.assertEqual(progress, [backend.CHUNK_BYTES, size])
        self.assertEqual(self.destination.stat().st_size, size)
        self.assertEqual(list(self.destination.parent.glob('*.part')), [])

    def test_read_failure_and_short_reads_release_and_remove_partial_file(self):
        for short in [False, True]:
            with self.subTest(short=short):
                mailbox = FakeMailbox()
                def read(address, count):
                    if short:
                        return bytes(count - 1)
                    raise RuntimeError('USB disconnected')
                with self.assertRaisesRegex(Exception, 'Short flash read|USB disconnected'):
                    self.capture(mailbox, read)
                self.assertEqual(mailbox.commands, [backend.BEGIN, backend.RELEASE])
                self.assertFalse(self.destination.exists())
                self.assertEqual(list(self.destination.parent.glob('*.part')), [])

    def test_grant_timeout_releases_even_before_any_read(self):
        mailbox = FakeMailbox(grant_timeout=True)
        with self.assertRaisesRegex(backend.FPGAToolError, 'did not grant'):
            self.capture(mailbox, lambda *_: self.fail('must not read without ownership'))
        self.assertEqual(mailbox.commands, [backend.BEGIN, backend.RELEASE])
        self.assertFalse(self.destination.exists())

    def test_existing_owner_is_not_released_or_interrupted(self):
        mailbox = FakeMailbox(granted=True)
        with self.assertRaisesRegex(backend.FPGAToolError, 'another operation'):
            self.capture(mailbox, lambda *_: self.fail('must not access another owner'))
        self.assertEqual(mailbox.commands, [])

    def test_failed_release_does_not_publish_a_capture(self):
        mailbox = FakeMailbox(release_timeout=True)
        with self.assertRaisesRegex(backend.FPGAToolError, 'did not release'):
            self.capture(mailbox, lambda address, count: bytes(count))
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob('*.part')), [])

    def test_read_and_cleanup_errors_are_both_reported(self):
        mailbox = FakeMailbox(release_timeout=True)
        def read(*_):
            raise RuntimeError('USB disconnected')
        with self.assertRaisesRegex(backend.FPGAToolError, 'USB disconnected; flash release also failed'):
            self.capture(mailbox, read)


class ServiceTests(unittest.TestCase):
    def test_serialized_captures_and_failure_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            finish = threading.Event()
            attempts = []
            def capture(path, progress, serial=None):
                attempts.append(serial)
                progress(backend.CHUNK_BYTES)
                if not finish.wait(5):
                    raise RuntimeError('test capture did not finish')
                if len(attempts) == 1:
                    raise RuntimeError('board unavailable')
                path.write_bytes(b'captured')
            service = backend.DumpService(directory, serial='adapter', capture=capture)
            first = service.start()
            try:
                with self.assertRaises(backend.CaptureBusy):
                    service.start()
                with self.assertRaises(backend.CaptureBusy):
                    service.image_path(first['id'])
                finish.set()
                service.worker.join(5)
                self.assertEqual(service.status(first['id'])['state'], 'failed')
                self.assertEqual(service.status(first['id'])['error'], 'board unavailable')
                second = service.start()
                service.worker.join(5)
                self.assertEqual(service.status(second['id'])['state'], 'complete')
                self.assertEqual(service.image_path(second['id']).read_bytes(), b'captured')
                self.assertEqual(attempts, ['adapter', 'adapter'])
            finally:
                finish.set()
                service.close()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.captures = []
        self.payload = bytes([123]) * backend.FLASH_BYTES
        def capture(path, progress, **kwargs):
            self.captures.append(path)
            path.write_bytes(self.payload)
            progress(len(self.payload))
        self.service = backend.DumpService(self.temp.name, capture=capture)
        class Handler(backend.Handler):
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, service=self.service))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.close)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.close()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_capture_status_and_exact_binary_download(self):
        status, headers, body = self.request('POST', '/api/dump', '{}',
            {'Content-Type': 'application/json', 'Origin': self.origin})
        self.assertEqual(status, 202)
        job_id = json.loads(body)['id']
        self.service.worker.join(5)
        status, headers, body = self.request('GET', f'/api/dump/{job_id}')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], 'complete')
        status, headers, body = self.request('GET', f'/api/dump/{job_id}/image')
        self.assertEqual(status, 200)
        self.assertEqual(body, self.payload)
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(len(self.captures), 1)

    def test_cross_origin_and_rebound_host_cannot_start_hardware_operations(self):
        for headers in [{'Origin': 'https://unrelated.example'}, {},
                        {'Host': 'unrelated.example', 'Origin': 'http://unrelated.example'}]:
            status, _, _ = self.request('POST', '/api/dump', '{}',
                {'Content-Type': 'application/json', **headers})
            self.assertEqual(status, 403)
        self.assertEqual(self.captures, [])

    def test_capture_parameters_and_unknown_ids_are_rejected(self):
        status, _, _ = self.request('POST', '/api/dump', '{"path":"/tmp/other"}',
            {'Content-Type': 'application/json', 'Origin': self.origin})
        self.assertEqual(status, 400)
        status, _, _ = self.request('GET', '/api/dump/' + '0' * 32)
        self.assertEqual(status, 404)
        status, _, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'id="read-flash"', body)
        self.assertEqual(self.captures, [])


if __name__ == '__main__':
    unittest.main()
