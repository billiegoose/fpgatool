"""Raster alignment, screenshot encoding, and native pin-output integration."""
from dataclasses import dataclass, replace
import json
import http.client
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from simulation.vga import VgaMonitor
from simulation.run import Viewer

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Timing:
    frame_width: int = 4
    frame_height: int = 3
    h_fp: int = 1
    h_pw: int = 1
    h_max: int = 8
    v_fp: int = 1
    v_pw: int = 1
    v_max: int = 6
    h_pol: int = 0
    v_pol: int = 0


def rgb(x, y):
    return x * 5, y * 7, 15 if x == 3 else 0


def png_pixels(path):
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, compressed = 8, b''
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            width, height = struct.unpack('>II', payload[:8])
        if kind == b'IDAT':
            compressed += payload
        pos += length + 12
    rows = zlib.decompress(compressed)
    stride = width * 3 + 1
    assert all(rows[y * stride] == 0 for y in range(height))
    return width, height, b''.join(rows[y * stride + 1:(y + 1) * stride] for y in range(height))


class MonitorTests(unittest.TestCase):
    def test_browser_serves_status_and_current_image(self):
        with mock.patch('webbrowser.open') as open_browser:
            viewer = Viewer(True)
        try:
            open_browser.assert_called_once()
            viewer.message = 'Captured frame 1'
            viewer.png = b'PNG test payload'
            viewer.revision = 3
            client = http.client.HTTPConnection('127.0.0.1', viewer.server.server_port, timeout=2)
            client.request('GET', '/')
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'VGA monitor', response.read())
            client.request('GET', '/status')
            self.assertEqual(json.loads(client.getresponse().read()), dict(message='Captured frame 1', frame=3))
            client.request('GET', '/frame.png?v=3')
            response = client.getresponse()
            self.assertEqual(response.getheader('Content-Type'), 'image/png')
            self.assertEqual(response.read(), viewer.png)
            client.close()
        finally:
            viewer.close()

    def test_pixels_after_arbitrary_start_and_both_polarities(self):
        for polarity in (0, 1):
            for start in (0, 11, 38):
                spec = replace(Timing(), h_pol=polarity, v_pol=polarity)
                monitor = VgaMonitor(spec)
                frames = []
                for tick in range(start, start + 3 * spec.h_max * spec.v_max):
                    x = tick % spec.h_max
                    y = (tick // spec.h_max) % spec.v_max
                    hs = int(5 <= x < 6) ^ polarity
                    vs = int(4 <= y < 5) ^ polarity
                    color = rgb(x, y) if x < 4 and y < 3 else (0, 0, 0)
                    frame = monitor.sample(*color, hs, vs)
                    if frame:
                        frames.append(frame)
                self.assertGreaterEqual(len(frames), 1)
                for frame in frames:
                    for y in range(3):
                        for x in range(4):
                            self.assertEqual(frame.pixel(x, y), tuple(c * 17 for c in rgb(x, y)))
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'frame.png'
                    frames[0].save(path)
                    self.assertEqual(png_pixels(path), (4, 3, frames[0].rgb))

    def test_bad_horizontal_period_is_rejected(self):
        monitor = VgaMonitor(Timing())
        monitor.sample(0, 0, 0, 0, 0)
        monitor.sample(0, 0, 0, 1, 0)
        monitor.sample(0, 0, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, 'HSYNC period'):
            monitor.sample(0, 0, 0, 1, 0)

    def test_no_vsync_never_publishes_partial_frame(self):
        monitor = VgaMonitor(Timing())
        for tick in range(500):
            self.assertIsNone(monitor.sample(0, 0, 0, int(tick % 8 == 5), 0))
        self.assertEqual(monitor.frames, 0)


@unittest.skipUnless((ROOT / '.fpgatool/cache/PipelineC/src/pypeline.py').is_file(),
                     'requires the pinned PipelineC runtime checkout')
class NativeMonitorTests(unittest.TestCase):
    def run_design(self, clock_setup, main_clock, divider, ready='1'):
        pins = '\n'.join(f'    board.VGA_{color}{bit} = px.{color.lower()}[{bit}]'
                         for color in 'RGB' for bit in range(4))
        design = f'''from pypeline import *
from vga.timing import make_vga_timing, VgaTimingSpec
from vga.types import vga_12bpp_t
import fpgatool_board.basys3.vga as board
spec = VgaTimingSpec(4, 3, 1, 1, 8, 1, 1, 6, 0, 0, 25.0)
timing = make_vga_timing(spec)
{clock_setup}
@hw_func
def write_pins(px: vga_12bpp_t):
{pins}
    board.VGA_HS = px.hs
    board.VGA_VS = px.vs
@MAIN({main_clock})
def video():
    phase: Reg[uint2_t] = 0
    px: Reg[vga_12bpp_t]
    ready = {ready}
    if phase == {divider - 1} and ready:
        phase = 0
        sig = timing()
        r: uint4_t = 0
        g: uint4_t = 0
        b: uint4_t = 0
        if sig.active:
            r = sig.pos.x * 5
            g = sig.pos.y * 7
            if sig.pos.x == 3:
                b = 15
        px = vga_12bpp_t(r=r, g=g, b=b, hs=sig.hsync, vs=sig.vsync)
    else:
        phase = phase + 1
    write_pins(px)
'''
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            source = Path(tmp) / 'tiny_vga.py'
            source.write_text(design)
            screen = Path(tmp) / 'screenshot.png'
            proc = subprocess.run([sys.executable, str(ROOT / 'fpgatool.py'), 'sim', str(source),
                '--no-open', '--frames', '2', '--cycles', '2000', '--screenshot', str(screen)],
                cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            expected = bytes(c * 17 for y in range(3) for x in range(4) for c in rgb(x, y))
            self.assertEqual(png_pixels(screen), (4, 3, expected))
            capture_dir = ROOT / 'build/basys3/tiny_vga/sim'
            self.assertEqual(json.loads((capture_dir / 'capture.json').read_text())['frames'], 2)
            self.assertEqual(png_pixels(capture_dir / 'frame-0002.png'), (4, 3, expected))

    def test_registered_pixels_and_divided_clock(self):
        self.run_design('', '50.0', 2)

    def test_mmcm_and_multiple_clock_domains(self):
        setup = '''from hardware.xilinx7_clock import MmcmStage, make_mmcm_clock, synchronize_clock_lock
clock_gen = make_mmcm_clock(100.0, MmcmStage(8, 1, 32))
clock: Wire[uint1_t] = make_clock(25.0)
locked: AsyncWire[uint1_t]
@MAIN(100.0)
def clock_source():
    c = clock_gen(0)
    clock = c.clock
    locked = c.locked
'''
        self.run_design(setup, '25.0', 1, 'synchronize_clock_lock(locked)')


if __name__ == '__main__':
    unittest.main()
