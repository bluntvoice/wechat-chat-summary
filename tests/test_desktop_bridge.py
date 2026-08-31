from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_bridge import _redact_report, build_report_entrypoint, normalize_chat_completions_url
from group_insight.history_store import HistoryStore as ActualHistoryStore
from group_insight.report_paths import allocate_report_paths
from group_insight.report_schema import build_report_document


class DesktopBridgeTests(unittest.TestCase):
    def test_development_report_entrypoint_uses_module(self) -> None:
        self.assertEqual(
            build_report_entrypoint(frozen=False),
            [sys.executable, "-m", "group_insight"],
        )

    def test_frozen_report_entrypoint_reuses_sidecar(self) -> None:
        self.assertEqual(
            build_report_entrypoint(frozen=True),
            [sys.executable, "--run-report"],
        )

    def test_deepseek_base_url_gets_chat_completions_path(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com", "deepseek"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_redaction_rerenders_locally_without_ai(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "reports"
            first_paths = allocate_report_paths(
                root, "测试群", "2026-08-31 00:00:00", "2026-08-31 23:59:59"
            )
            source_path = first_paths.data_dir / f"{first_paths.data_stem}.json"
            document = build_report_document(
                ctx={"username": "room@chatroom", "display_name": "测试群"},
                start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
                stats={"message_count": 2, "participant_count": 1},
                report={"one_line_summary": "摘要", "theme_cards": [{"title": "待屏蔽", "summary": "私密内容"}], "sections": []},
                resources={"count": 0, "groups": []},
                exports={"json": str(source_path), "html": "old.html", "png": "old.png"},
                provider="deepseek", model="model", dry_run=False, chunk_count=1, chunk_plan={},
            )
            source_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

            def fake_export(_html_path: Path, image_path: Path, **_kwargs: object) -> str:
                image_path.write_bytes(b"test-png")
                return ""

            history_path = Path(temp_dir) / "history.sqlite3"
            with (
                patch("group_insight.desktop_bridge.export_report_image", side_effect=fake_export),
                patch("group_insight.desktop_bridge.HistoryStore", side_effect=lambda: ActualHistoryStore(history_path)),
                patch("group_insight.desktop_bridge.DeepSeekClient") as ai_client,
            ):
                result = _redact_report(
                    {"export_root": str(root), "image_dpi": 300},
                    {"json_path": str(source_path), "target_ids": ["themes:0"]},
                )

            self.assertEqual(result["version"], 2)
            self.assertFalse(ai_client.called)
            new_payload = Path(result["json_path"]).read_text(encoding="utf-8")
            self.assertNotIn("私密内容", new_payload)
            self.assertIn("已屏蔽，建议在群内查看", new_payload)


if __name__ == "__main__":
    unittest.main()
