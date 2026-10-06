import queue
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from simulation.compiled import cache_key, driver_source, read_stream


class CompiledSimTests(unittest.TestCase):
    def test_ppm_reader_handles_fragmented_frames_and_eof(self):
        reader, writer = socket.socketpair()
        frames = queue.Queue()
        worker = threading.Thread(target=read_stream, args=(reader, frames))
        worker.start()
        ppm = b'P6\n2 1\n255\n\x00\x00\x00\xff\x80\x40'
        for byte in ppm * 2:
            writer.sendall(bytes([byte]))
        writer.close()
        for _ in range(2):
            frame, received = frames.get(timeout=2)
            self.assertEqual((frame.width, frame.height), (2, 1))
            self.assertEqual(frame.pixel(1, 0), (255, 128, 64))
            self.assertEqual(received, ppm)
        self.assertIsInstance(frames.get(timeout=2), EOFError)
        worker.join(2)
        reader.close()
        self.assertFalse(worker.is_alive())

    def test_cache_includes_helper_contents_source_identity_and_tool_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ('examples', 'simulation', 'toolchain'):
                (root / folder).mkdir()
            (root / 'fpgatool.py').write_text('')
            (root / 'toolchain.lock.toml').write_text('')
            source = root / 'examples/design.py'
            source.write_text('design')
            helper = root / 'examples/helper.py'
            helper.write_text('one')
            key = cache_key(root, source, 'v1')
            (root / 'build').mkdir()
            (root / 'build/ignored.py').write_text('changed output')
            self.assertEqual(key, cache_key(root, source, 'v1'))
            helper.write_text('two')
            self.assertNotEqual(key, cache_key(root, source, 'v1'))
            self.assertNotEqual(cache_key(root, source, 'v1'), cache_key(root, source, 'v2'))

    def test_non_vga_and_multiple_clock_designs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'VGA_R0'):
            driver_source('module top(clk_100p0); input clk_100p0; endmodule')
        with self.assertRaisesRegex(ValueError, 'one input clock'):
            driver_source('module top(clk_100p0, clk_25p0); input clk_100p0; input clk_25p0; endmodule')
