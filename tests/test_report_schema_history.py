from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from group_insight.history_store import HistoryStore
from group_insight.models import StructuredMessage
from group_insight.report_model import repair_final_report
from group_insight.report_schema import build_report_document
from group_insight.redaction import REDACTION_NOTICE, list_redaction_targets, redact_report_document
from group_insight.rendering import render_html_report
from group_insight.resources import build_resource_catalog, extract_resources


def message(message_id: str, text: str, metadata=None) -> StructuredMessage:
    return StructuredMessage(
        id=message_id, local_id=1, timestamp=1788134400, time="2026-08-31 08:00:00",
        sender_username="wxid_a", sender="小甲", text=text, msg_type="链接/文件" if metadata else "文本",
        chat_id="room@chatroom", chat_name="测试群", table_name="api", metadata=metadata or {},
    )


class ReportSchemaHistoryTests(unittest.TestCase):
    def test_resources_merge_links_and_files_under_one_topic(self):
        messages = [
            message("m1", "资料 https://example.com/a"),
            message("m2", "[文件] 清单.xlsx", {"rich_kind": "file_card", "title": "清单.xlsx", "file_ext": "xlsx"}),
        ]
        resources = extract_resources(messages)
        catalog = build_resource_catalog(resources, [{"topic": "项目资料", "resource_ids": [item["id"] for item in resources]}], [])
        self.assertEqual(catalog["count"], 2)
        self.assertEqual({item["type"] for item in catalog["groups"][0]["items"]}, {"link", "file"})

    def test_jokes_do_not_become_serious_items(self):
        report = repair_final_report(
            {
                "lead_summary": "今天讨论项目安排。",
                "decisions": [{"content": "明天收购月球", "tone": "joke", "confidence": 0.99}],
                "action_items": [{"task": "认真提交清单", "tone": "formal", "confidence": 0.9}],
                "risk_flags": [{"content": "只是调侃", "tone": "sarcasm", "confidence": 0.8}],
                "light_moments": [{"content": "收购月球是群友玩笑", "tone": "joke"}],
            },
            "测试群", "2026-08-31 00:00:00", "2026-08-31 23:59:59",
            {"message_count": 2, "effective_message_count": 2, "participant_count": 1}, [],
        )
        self.assertEqual(report["decisions"], [])
        self.assertEqual(report["risk_flags"], [])
        self.assertEqual(len(report["action_items"]), 1)
        self.assertEqual(len(report["light_moments"]), 1)

    def test_report_document_is_saved_to_sqlite_without_raw_messages(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={
                "message_count": 3, "effective_message_count": 2, "effective_char_count": 20, "participant_count": 1,
                "top_speakers": [{"rank": 1, "name": "小甲", "message_count": 3}],
                "known_speakers": ["小甲"],
                "member_aliases": [{"sender_id": "wxid_a", "sender_name": "小甲", "mention_token": "[[user:wxid_a]]"}],
            },
            report={"one_line_summary": "今天围绕项目清单展开讨论。", "theme_cards": [], "sections": []},
            resources={"count": 0, "groups": []}, exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={"strategy": "map-reduce"},
        )
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(path) as store:
                report_id = store.upsert_report(document)
                self.assertEqual(store.summarized_chat_ids(), ["room@chatroom"])
                row = store.connection.execute("SELECT schema_version, json_path FROM reports WHERE report_id=?", (report_id,)).fetchone()
                self.assertEqual(row["schema_version"], "2.0")
                self.assertEqual(row["json_path"], "a.json")
            self.assertNotIn("完整原始聊天", path.read_bytes().decode("utf-8", errors="ignore"))

    def test_redaction_creates_detail_free_new_version(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={"message_count": 3, "effective_message_count": 2, "effective_char_count": 20, "participant_count": 1},
            report={
                "one_line_summary": "当日摘要。",
                "theme_cards": [{"title": "敏感热点", "summary": "热点总结正文"}],
                "sections": [{"title": "敏感话题", "summary": "不能进入屏蔽版", "start_time": "09:00", "end_time": "09:30"}],
                "participant_insights": [{"name": "小甲", "insight": "参与人员观察"}],
                "light_moments": [{"content": "不会进入对外报告"}],
            },
            resources={
                "count": 1,
                "groups": [{"topic_id": "g1", "topic": "资料", "summary": "资料说明", "items": [{"id": "r1", "type": "link", "title": "私密链接", "url": "https://example.com", "sender": "小乙", "sent_at": "2026-08-31 10:00:00", "context_summary": "链接上下文"}]}],
            },
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={"strategy": "map-reduce"},
        )
        target_ids = {item["id"] for item in list_redaction_targets(document)}
        self.assertIn("topics:0", target_ids)
        self.assertIn("resources:0:0", target_ids)
        self.assertNotIn("light_moments", document["content"])
        redacted = redact_report_document(
            document,
            ["topics:0", "members:0", "resources:0:0"],
            version=2,
            exports={"json": "b.json", "html": "b.html", "png": "b.png"},
        )
        serialized = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn("不能进入屏蔽版", serialized)
        self.assertNotIn("私密链接", serialized)
        self.assertNotIn("小乙", serialized)
        self.assertNotIn("参与人员观察", serialized)
        self.assertNotIn("小甲", serialized)
        self.assertIn(REDACTION_NOTICE, serialized)
        self.assertEqual(redacted["metadata"]["version"], 2)
        self.assertEqual(document["content"]["topics"][0]["title"], "敏感话题")
        html = render_html_report(redacted)
        self.assertIn(REDACTION_NOTICE, html)
        self.assertNotIn("不能进入屏蔽版", html)

        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as store:
                report_id = store.upsert_report(redacted)
                count = store.connection.execute(
                    "SELECT COUNT(*) FROM report_redactions WHERE report_id=?", (report_id,)
                ).fetchone()[0]
                self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
