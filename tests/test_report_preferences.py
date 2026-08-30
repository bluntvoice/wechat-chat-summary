from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from group_insight.models import StructuredMessage
from group_insight.rendering import invalidate_cached_outputs_if_needed, render_html_report
from group_insight.stats import build_interaction_rankings


class ReportPreferenceTests(unittest.TestCase):
    def test_header_uses_single_summary_date_label(self):
        html = render_html_report(
            chat_name="测试群",
            chat_id="room@chatroom",
            start_time="2026-08-28 00:00:00",
            end_time="2026-08-28 23:59:59",
            stats={"message_count": 1, "participant_count": 1},
            report={},
        )
        self.assertEqual(html.count("群聊总结：2026-08-28"), 1)
        self.assertNotIn("统计区间：", html)

    def test_pat_rankings_are_not_exposed(self):
        message = StructuredMessage(
            id="m1",
            local_id=1,
            timestamp=1,
            time="2026-08-28 00:00",
            sender_username="wxid_a",
            sender="小甲",
            text='"小甲"拍了拍"小乙"',
            msg_type="链接/文件",
            chat_id="room@chatroom",
            chat_name="测试群",
            table_name="api",
            metadata={
                "interaction_kind": "pat",
                "pat_from_name": "小甲",
                "pat_to_name": "小乙",
            },
        )
        rankings = build_interaction_rankings([message])
        self.assertNotIn("pat_sender", rankings)
        self.assertNotIn("pat_target", rankings)

    def test_signature_change_clears_stage_cache(self):
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            snapshot_dir = output_dir / "snapshot"
            snapshot_dir.mkdir()
            (snapshot_dir / "run_signature.json").write_text(
                '{"dry_run": true}', encoding="utf-8"
            )
            map_dir = output_dir / "map"
            map_dir.mkdir()
            (map_dir / "old.json").write_text("{}", encoding="utf-8")
            invalidate_cached_outputs_if_needed(output_dir, {"dry_run": False})
            self.assertFalse(map_dir.exists())


if __name__ == "__main__":
    unittest.main()
