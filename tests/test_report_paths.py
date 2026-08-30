from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from group_insight.desktop_bridge import normalize_chat_completions_url
from group_insight.report_paths import allocate_report_paths, build_report_date_label


class ReportPathTests(unittest.TestCase):
    def test_single_and_multi_day_labels_keep_hyphenated_dates(self) -> None:
        self.assertEqual(
            build_report_date_label("2026-08-30 00:00:00", "2026-08-30 23:59:59"),
            "2026-08-30",
        )
        self.assertEqual(
            build_report_date_label("2026-08-30 00:00:00", "2026-09-02 23:59:59"),
            "2026-08-30_至_2026-09-02",
        )

    def test_png_and_report_data_are_split_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = allocate_report_paths(
                root,
                "岭下闲棋股东大会读者群",
                "2026-08-30 00:00:00",
                "2026-08-30 23:59:59",
            )
            second = allocate_report_paths(
                root,
                "岭下闲棋股东大会读者群",
                "2026-08-30 00:00:00",
                "2026-08-30 23:59:59",
            )
            self.assertEqual(first.data_dir.name, "2026-08-30报告数据")
            self.assertEqual(first.image_path.name, "2026-08-30报告.png")
            self.assertEqual(first.image_dir.parts[-3:], ("导出图", "2026", "08"))
            self.assertEqual(second.data_dir.name, "2026-08-30报告数据_v2")
            self.assertEqual(second.image_path.name, "2026-08-30报告_v2.png")

    def test_api_base_urls_are_normalized(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com", "deepseek"),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            normalize_chat_completions_url("https://example.com/v1", "openai-compatible"),
            "https://example.com/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
