"""Pin-level VGA receiver and dependency-free RGB/PNG frames.

The timing specification supplies porches; HS/VS edges supply raster alignment.
Black pixels are ordinary pixels, never an indication of blanking.
"""
from dataclasses import dataclass
from pathlib import Path
import struct
import zlib


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    rgb: bytes

    def pixel(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError((x, y))
        offset = (y * self.width + x) * 3
        return tuple(self.rgb[offset:offset + 3])

    def png(self):
        def chunk(kind, data):
            return (struct.pack('>I', len(data)) + kind + data
                    + struct.pack('>I', zlib.crc32(kind + data)))
        stride = self.width * 3
        rows = b''.join(b'\0' + self.rgb[y:y + stride]
                        for y in range(0, len(self.rgb), stride))
        return (b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', self.width, self.height, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Browser readers never see a partially written PNG.
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(self.png())
        tmp.replace(path)


class VgaMonitor:
    """Sample one RGB444/HS/VS tuple per pixel clock; return complete Frame(s).

    Uses Pypeline VgaTimingSpec's XOR polarity convention: the pulse level is
    1 ^ h_pol/v_pol. Discards the initial partial raster while acquiring sync.
    """
    def __init__(self, spec):
        self.spec = spec
        if not (0 < spec.frame_width <= spec.frame_width + spec.h_fp
                < spec.frame_width + spec.h_fp + spec.h_pw <= spec.h_max
                and 0 < spec.frame_height <= spec.frame_height + spec.v_fp
                < spec.frame_height + spec.v_fp + spec.v_pw <= spec.v_max):
            raise ValueError('invalid VGA timing geometry')
        self.buffer = bytearray(spec.frame_width * spec.frame_height * 3)
        self.x = self.y = None
        self.prev_hs = self.prev_vs = None
        self.h_edge = self.v_edge = None
        self.samples = self.frames = self.pixels = 0
        self.collecting = False

    def sample(self, r, g, b, hs, vs):
        s = self.spec
        tick = self.samples
        self.samples += 1
        hs, vs = int(hs), int(vs)
        h_start = self.prev_hs is not None and hs != self.prev_hs and hs == (1 ^ s.h_pol)
        v_start = self.prev_vs is not None and vs != self.prev_vs and vs == (1 ^ s.v_pol)
        self.prev_hs, self.prev_vs = hs, vs
        if h_start:
            if self.h_edge is not None and tick - self.h_edge != s.h_max:
                raise ValueError(f'HSYNC period {tick - self.h_edge} pixels; expected {s.h_max}')
            self.h_edge = tick
            self.x = s.frame_width + s.h_fp
        if v_start:
            if self.v_edge is not None and tick - self.v_edge != s.h_max * s.v_max:
                raise ValueError(f'VSYNC period {tick - self.v_edge} pixels; expected {s.h_max * s.v_max}')
            self.v_edge = tick
            self.y = s.frame_height + s.v_fp
        frame = None
        if self.x is not None and self.y is not None:
            if self.x == 0 and self.y == 0:
                self.collecting = True
                self.pixels = 0
            if self.collecting and self.x < s.frame_width and self.y < s.frame_height:
                offset = (self.y * s.frame_width + self.x) * 3
                self.buffer[offset:offset + 3] = bytes((int(r) * 17, int(g) * 17, int(b) * 17))
                self.pixels += 1
                if self.x == s.frame_width - 1 and self.y == s.frame_height - 1:
                    if self.pixels != s.frame_width * s.frame_height:
                        raise ValueError('incomplete VGA raster after sync acquisition')
                    frame = Frame(s.frame_width, s.frame_height, bytes(self.buffer))
                    self.frames += 1
                    self.collecting = False
        if self.x is not None:
            self.x += 1
            if self.x == s.h_max:
                self.x = 0
                if self.y is not None:
                    self.y = (self.y + 1) % s.v_max
        return frame
