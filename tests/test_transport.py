from __future__ import annotations

import struct
import os
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from group_insight.transport import (
    MAX_SINGLE_SCREENSHOT_DEVICE_HEIGHT,
    PNG_SIGNATURE,
    export_report_image,
    find_local_browser_executable,
    plan_png_slices,
    set_png_dpi_metadata,
    validate_png_dimensions,
)
from group_insight.settings import DEFAULT_REPORT_IMAGE_WIDTH


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


class PngExportTests(unittest.TestCase):
    def test_slice_plan_is_contiguous_and_exact(self) -> None:
        cases = (
            (1000, [(0, 1000)]),
            (MAX_SINGLE_SCREENSHOT_DEVICE_HEIGHT // 2, [(0, 6000)]),
            (6001, [(0, 5000), (5000, 1001)]),
            (10000, [(0, 5000), (5000, 5000)]),
            (15437, [(0, 5000), (5000, 5000), (10000, 5000), (15000, 437)]),
        )
        for height, expected in cases:
            with self.subTest(height=height):
                plan = plan_png_slices(height, 2)
                self.assertEqual(plan, expected)
                self.assertEqual(plan[0][0], 0)
                self.assertEqual(sum(length for _, length in plan), height)
                for previous, following in zip(plan, plan[1:]):
                    self.assertEqual(previous[0] + previous[1], following[0])
                    self.assertGreater(following[1], 0)

    def test_png_dimension_validation_rejects_missing_height(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "report.png"
            Image.new("RGB", (600, 1000), "red").save(image_path)
            self.assertEqual(validate_png_dimensions(image_path, 600, 1001), (600, 1000))
            with self.assertRaisesRegex(ValueError, "预期 600×2000"):
                validate_png_dimensions(image_path, 600, 2000)

    def test_existing_png_is_replaced_only_after_validated_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "report.png"
            Image.new("RGB", (1, 1), "red").save(original)
            before = original.read_bytes()
            with patch("group_insight.transport.export_report_image_with_playwright", return_value="截图失败"):
                self.assertIn("截图失败", export_report_image(root / "report.html", original))
            self.assertEqual(original.read_bytes(), before)

            def render(_html, target, *, render_info, **_kwargs):
                Image.new("RGB", (600, 1000), "blue").save(target)
                render_info.update(expected_png_width=600, expected_png_height=1000)
                return ""

            with patch("group_insight.transport.export_report_image_with_playwright", side_effect=render):
                self.assertEqual(export_report_image(root / "report.html", original), "")
            self.assertNotEqual(original.read_bytes(), before)
            with Image.open(original) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
                self.assertAlmostEqual(image.info["dpi"][0], 300, delta=1)

    def test_invalid_new_png_does_not_replace_existing_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "report.png"
            Image.new("RGB", (1, 1), "red").save(original)
            before = original.read_bytes()

            def render(_html, target, *, render_info, **_kwargs):
                Image.new("RGB", (600, 100), "blue").save(target)
                render_info.update(expected_png_width=600, expected_png_height=1000)
                return ""

            with patch("group_insight.transport.export_report_image_with_playwright", side_effect=render):
                self.assertIn("PNG 尺寸异常", export_report_image(root / "report.html", original))
            self.assertEqual(original.read_bytes(), before)

    @unittest.skipUnless(os.getenv("RUN_BROWSER_LONG_PNG_TEST") == "1" and find_local_browser_executable(),
                         "本地 Chrome/Edge 长图测试需显式启用")
    def test_browser_long_report_has_distinct_head_middle_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            html_path = root / "long.html"
            png_path = root / "long.png"
            html_path.write_text(
                '<body style="margin:0">'
                '<div style="height:5500px;background:red">顶部标记</div>'
                '<div style="height:5500px;background:blue">中部标记</div>'
                '<div style="height:5500px;background:green">尾部标记</div></body>',
                encoding="utf-8",
            )
            info = {}
            self.assertEqual(export_report_image(html_path, png_path, viewport_width=300, render_info=info), "")
            self.assertEqual(info["device_scale_factor"], 2)
            self.assertTrue(info["segmented"])
            self.assertEqual(info["segment_count"], 4)
            with Image.open(png_path) as image:
                self.assertEqual(image.size, (600, 33000))
                self.assertEqual(image.getpixel((100, 100)), (255, 0, 0))
                self.assertEqual(image.getpixel((100, 15000)), (0, 0, 255))
                self.assertEqual(image.getpixel((100, 32900)), (0, 128, 0))
                self.assertEqual(image.getpixel((100, 10999)), (255, 0, 0))
                self.assertEqual(image.getpixel((100, 11000)), (0, 0, 255))

    @unittest.skipUnless(os.getenv("RUN_BROWSER_LONG_PNG_TEST") == "1" and find_local_browser_executable(),
                         "本地 Chrome/Edge 截图对照需显式启用")
    def test_short_report_pixels_match_original_full_page_screenshot(self) -> None:
        from playwright.sync_api import sync_playwright
        from group_insight.rendering import render_html_report
        from tests.test_history_center import history_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            html_path = root / "report.html"
            html_path.write_text(render_html_report(history_document(root)), encoding="utf-8")
            new_png = root / "new.png"
            baseline_png = root / "baseline.png"
            info = {}
            self.assertEqual(export_report_image(html_path, new_png, render_info=info), "")
            self.assertFalse(info["segmented"])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=find_local_browser_executable(),
                    args=["--allow-file-access-from-files", "--disable-web-security"],
                )
                try:
                    page = browser.new_page(
                        viewport={"width": DEFAULT_REPORT_IMAGE_WIDTH, "height": 1600},
                        device_scale_factor=2,
                    )
                    page.goto(html_path.resolve().as_uri(), wait_until="load")
                    page.wait_for_load_state("networkidle")
                    page.evaluate("() => document.fonts.ready")
                    page.wait_for_timeout(300)
                    page.screenshot(path=str(baseline_png), full_page=True, type="png")
                finally:
                    browser.close()
            with Image.open(new_png) as new, Image.open(baseline_png) as baseline:
                self.assertEqual(new.size, baseline.size)
                self.assertIsNone(ImageChops.difference(new.convert("RGBA"), baseline.convert("RGBA")).getbbox())


if __name__ == "__main__":
    unittest.main()
