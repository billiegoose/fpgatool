"""Live programming is independent of asset format, address and activation."""
import contextlib
import io
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch

import fpgatool
from programming.live_flash import Mailbox, program_live_data
from examples.hardware.live_flash_protocol import BEGIN, RELOAD, RELEASE, READY, GRANTED, BUSY, ERROR


class GeneralLiveTests(unittest.TestCase):
    def test_mailbox_reenumerates_usb_after_device_reconnects(self):
        device = {'current': 1, 'cached': 0}
        engine = Mock()

        def enumerate_again():
            device['cached'] = device['current']

        def configure(url):
            if device['cached'] != device['current']:
                raise OSError(19, 'No such device (it may have been disconnected)')

        engine.configure.side_effect = configure
        with patch('pyftdi.jtag.JtagEngine', return_value=engine), \
             patch('pyftdi.usbtools.UsbTools.flush_cache', side_effect=enumerate_again), \
             patch.object(Mailbox, 'read', return_value=READY):
            with Mailbox('adapter'):
                pass
            device['current'] += 1  # Another process reconnected the adapter.
            with Mailbox('adapter'):
                pass
        self.assertEqual(engine.configure.call_count, 2)
        self.assertEqual(engine.close.call_count, 2)

    def test_mailbox_cleanup_does_not_repeat_idle_and_always_closes_usb(self):
        mailbox = Mailbox()
        mailbox.engine = Mock()
        mailbox.__exit__(None, None, None)
        mailbox.engine.go_idle.assert_not_called()
        mailbox.engine.sync.assert_called_once_with()
        mailbox.engine.close.assert_called_once_with(freeze=True)
        mailbox.engine.reset_mock()
        mailbox.engine.sync.side_effect = RuntimeError('USB disconnected')
        with self.assertRaisesRegex(RuntimeError, 'USB disconnected'):
            mailbox.__exit__(None, None, None)
        mailbox.engine.close.assert_called_once_with(freeze=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.binary = Path(self.tmp.name) / 'arbitrary.bin'
        self.binary.write_bytes(b'raw data, no font header\x00\xff')
        self.events = []
        self.status = READY | (7 << 16)
        self.open = False
        self.reject_reload = False
        owner = self

        class FakeMailbox(Mailbox):
            def __init__(self, serial):
                self.engine = Mock()
            def __enter__(self):
                owner.open = True
                return self
            def __exit__(self, *args):
                owner.open = False
            def read(self):
                return owner.status
            def send(self, command):
                owner.events.append(command)
                if command == BEGIN:
                    owner.status |= GRANTED | BUSY
                elif command == RELEASE:
                    owner.status &= ~(GRANTED | BUSY)
                elif command == RELOAD:
                    generation = ((owner.status >> 16)+1) & 65535
                    owner.status = ERROR if owner.reject_reload else READY | generation << 16
        self.mailbox = FakeMailbox
        self.relay = Mock()
        self.relay.return_value.__enter__ = Mock(return_value=Mock(port=12345))
        self.relay.return_value.__exit__ = Mock(return_value=False)

    def upload(self, **kwargs):
        def program(port):
            self.assertTrue(self.open)
            self.assertEqual(port, 12345)
            self.assertTrue(self.status & GRANTED)
            self.events.append('verified')
        program_live_data(self.binary, program, mailbox_factory=self.mailbox,
                          relay_factory=self.relay, **kwargs)

    def test_arbitrary_bytes_release_without_reload_or_generation_change(self):
        self.upload()
        self.assertEqual(self.events, [BEGIN, 'verified', RELEASE])
        self.assertEqual(self.status, READY | (7 << 16))
        self.assertFalse(self.open)

    def test_reload_uses_device_acknowledgement_and_wraps_generation(self):
        self.status = READY | (65535 << 16)
        self.upload(reload=True)
        self.assertEqual(self.events, [BEGIN, 'verified', RELOAD])
        self.assertEqual(self.status, READY)

    def test_device_validation_error_is_reported_after_verified_write(self):
        self.reject_reload = True
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'device rejected'):
            self.upload(reload=True)
        self.assertEqual(self.events, [BEGIN, 'verified', RELOAD])
        self.assertFalse(self.open)

    def test_failed_programming_releases_without_reload(self):
        with self.assertRaisesRegex(RuntimeError, 'verify failed'):
            program_live_data(self.binary, Mock(side_effect=RuntimeError('verify failed')),
                              reload=True, mailbox_factory=self.mailbox, relay_factory=self.relay)
        self.assertEqual(self.events, [BEGIN, RELEASE])

    def test_zero_exit_programmer_error_releases_without_reload(self):
        log = Path(self.tmp.name) / 'program.log'
        command = [sys.executable, '-c',
                   "print('Jedec ID : ff'); print('Error: block protection is set')"]
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                self.events.clear()
                with patch.object(fpgatool, 'VERBOSE', verbose), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(fpgatool.FPGAToolError, 'block protection'):
                        program_live_data(self.binary,
                            lambda port: fpgatool.run_data_programmer(command, log_path=log),
                            reload=True, mailbox_factory=self.mailbox, relay_factory=self.relay)
                self.assertEqual(self.events, [BEGIN, RELEASE])
                self.assertEqual(self.status >> 16, 7)
                self.assertIn('Error: block protection', log.read_text())

    def test_programmer_must_finish_readback_verification(self):
        log = Path(self.tmp.name) / 'program.log'
        for transcript, success in (
            ('Writing: [====] 100.00%\nDone\n', False),
            ('Verifying write (May take time)\nReading: [=   ] 25.00%\n', False),
            ('Verifying write (May take time)\nReading: [====] 100.00%\n', True),
            ('Verifying write\nReading: [====] 100.00%\nVerification failed at 2228224\n', False),
            ('Verifying write\nReading: [====] 100.00%\n\x1b[31mSPIFlash Error: failed to disable write\x1b[0m\n', False),
        ):
            with self.subTest(transcript=transcript):
                command = [sys.executable, '-c', f'print({transcript!r})']
                if success:
                    fpgatool.run_data_programmer(command, log_path=log)
                else:
                    with self.assertRaises(fpgatool.FPGAToolError):
                        fpgatool.run_data_programmer(command, log_path=log)

    def test_empty_file_is_rejected_before_usb_access(self):
        self.binary.write_bytes(b'')
        mailbox = Mock()
        with self.assertRaisesRegex(fpgatool.FPGAToolError, 'nonempty'):
            program_live_data(self.binary, Mock(), mailbox_factory=mailbox)
        mailbox.assert_not_called()

    def test_reload_timeout_uses_device_generic_message(self):
        mailbox = Mailbox()
        mailbox.read = Mock(return_value=BUSY)
        with patch('programming.live_flash.time.monotonic', side_effect=[0, 5]):
            with self.assertRaisesRegex(fpgatool.FPGAToolError, 'reload completion'):
                mailbox.wait(lambda s: not s & BUSY, 'device did not acknowledge reload completion',
                             timeout=4)

    def test_cli_accepts_non_font_binary_at_another_offset_and_generic_output(self):
        for reload in (False, True):
            argv = ['program-data', str(self.binary), '--live', '--offset', '0x300000']
            if reload:
                argv += ['--reload', '--reload-timeout', '12']
            args = fpgatool.parser().parse_args(argv)
            output = io.StringIO()
            def upload(binary, program, **kwargs):
                self.assertEqual(binary, self.binary.resolve())
                self.assertEqual(kwargs['reload'], reload)
                self.assertEqual(kwargs['reload_timeout'], 12 if reload else 3)
                program(12345)
            with patch('programming.live_flash.program_live_data', side_effect=upload), \
                 patch.object(fpgatool, 'require_tool', return_value='loader'), \
                 patch.object(fpgatool, 'run_data_programmer') as run, contextlib.redirect_stdout(output):
                fpgatool.cmd_program_data(args)
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[cmd.index('--offset')+1], str(0x300000))
            self.assertIn('xvc-client', cmd)
            for flag in ('--skip-load-bridge', '--skip-reset', '--verify'):
                self.assertIn(flag, cmd)
            self.assertNotIn('font', output.getvalue().lower())
            self.assertIn('reload acknowledged' if reload else 'ownership released', output.getvalue())

    def test_reload_options_require_live_program_data(self):
        for argv in (['program-data', str(self.binary), '--reload'],
                     ['load', 'demo.bit', '--reload'],
                     ['program-data', str(self.binary), '--live', '--reload-timeout', '12']):
            with patch('sys.argv', ['fpgatool', *argv]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as status:
                    fpgatool.main()
            self.assertEqual(status.exception.code, 2)

    def test_configuration_flash_is_protected_before_opening_live_transport(self):
        args = fpgatool.parser().parse_args(['program-data', str(self.binary), '--live',
                                           '--offset', '0x10000'])
        with patch('programming.live_flash.program_live_data') as upload:
            with self.assertRaisesRegex(fpgatool.FPGAToolError, 'configuration|below'):
                fpgatool.cmd_program_data(args)
        upload.assert_not_called()
