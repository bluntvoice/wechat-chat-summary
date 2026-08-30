from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from group_insight.transport import PNG_SIGNATURE, set_png_dpi_metadata


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def one_pixel_png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixel = zlib.compress(b"\x00\x00\x00\x00\xff")
    return PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", pixel) + png_chunk(b"IEND", b"")


class PngDpiMetadataTests(unittest.TestCase):
    def test_writes_300_dpi_phys_chunk_without_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            image_path = Path(temporary_dir) / "report.png"
            image_path.write_bytes(one_pixel_png())

            set_png_dpi_metadata(image_path, dpi=300)

            data = image_path.read_bytes()
            phys_offset = data.index(b"pHYs")
            x_ppm, y_ppm, unit = struct.unpack(">IIB", data[phys_offset + 4 : phys_offset + 13])
            self.assertEqual((x_ppm, y_ppm, unit), (11811, 11811, 1))
            self.assertEqual(data.count(b"IHDR"), 1)
            self.assertEqual(data.count(b"IDAT"), 1)


if __name__ == "__main__":
    unittest.main()
