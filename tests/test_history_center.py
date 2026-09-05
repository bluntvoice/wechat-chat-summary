from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.history_store import (
    BASE_SCHEMA_STATEMENTS,
    DATABASE_SCHEMA_VERSION,
    HistoryStore,
)
from group_insight.redaction import list_redaction_targets
from group_insight.report_schema import build_report_document


def history_document(root: Path, *, version: int = 1, schema_version: str = "2.2") -> dict:
    document = build_report_document(
        ctx={"username": "history@chatroom", "display_name": "跨境项目讨论群"},
        start_time="2026-08-31 00:00:00",
        end_time="2026-08-31 23:59:59",
        version=version,
        stats={
            "message_count": 18,
            "effective_message_count": 16,
            "participant_count": 3,
            "top_speakers": [{"name": "张三", "message_count": 8}],
            "word_cloud": [{"word": "清关", "count": 6}],
            "resource_breakdown": {"link": 1, "file": 1},
        },
        report={
            "one_line_summary": "今天确认 Tail clearance 清关方案与交付安排",
            "theme_cards": [{"title": "清关方案", "summary": "核对资料与风险"}],
            "sections": [
                {
                    "id": "topic-clearance",
                    "title": "美国尾程清关",
                    "discussion_flow": "围绕美国尾程清关资料、时效和责任分工展开讨论。",
                    "outcome": {"content": "采用新清关渠道。"},
                    "action_items": [{"task": "准备尾程清关资料", "owner": "张三"}],
                    "open_questions": [{"question": "海关编码是否需要调整"}],
                    "risk_flags": [{"content": "资料缺失可能导致延误"}],
                    "quotes": [{"speaker": "李四", "quote": "先把清单核完再发。"}],
                    "resource_ids": ["res-link", "res-file"],
                }
            ],
            "ai_observations": [{"title": "讨论节奏", "content": "先核对风险，再落实负责人。"}],
            "participant_insights": [{"name": "张三", "insight": "负责资料复核"}],
        },
        resources={
            "count": 2,
            "groups": [
                {
                    "topic_id": "topic-clearance",
                    "topic": "清关资料",
                    "items": [
                        {
                            "id": "res-link",
                            "type": "link",
                            "title": "美国海关政策说明",
                            "url": "https://example.com/customs-guide",
                            "sender": "李四",
                            "sent_at": "2026-08-31 10:00:00",
                            "context_summary": "尾程政策资源",
                        },
                        {
                            "id": "res-file",
                            "type": "file",
                            "title": "清关资料清单.xlsx",
                            "url": "",
                            "sender": "王五",
                            "sent_at": "2026-08-31 10:05:00",
                            "context_summary": "待填写文件",
                        },
                    ],
                }
            ],
        },
        exports={
            "json": str(root / f"report-v{version}.json"),
            "html": str(root / f"report-v{version}.html"),
            "png": str(root / f"report-v{version}.png"),
        },
        provider="deepseek",
        model="deepseek-v4-flash",
        dry_run=False,
        chunk_count=1,
        chunk_plan={},
    )
    # 模拟修复前已保存的报告；旧讨论落点继续由历史中心读取。
    document["content"]["topics"][0]["outcome"] = {"content": "采用新清关渠道。"}
    document["schema_version"] = schema_version
    return document


class HistoryCenterMigrationTests(unittest.TestCase):
    def test_v1_database_rebuilds_report_aligned_logical_modules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "history.sqlite3"
            document = history_document(root)
            metadata = document["metadata"]
            content = document["content"]
            stats = document["stats"]
            with closing(sqlite3.connect(path)) as connection, connection:
                for statement in BASE_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.execute(
                    "INSERT INTO chats VALUES(?,?,?,?,?)",
                    ("history@chatroom", "跨境项目讨论群", "2026-08-31", "2026-08-31", "2026-08-31"),
                )
                connection.execute(
                    """INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        metadata["report_id"], "history@chatroom", "2026-08-31",
                        metadata["period"]["start"], metadata["period"]["end"], 1,
                        "2.2", metadata["generated_at"], "deepseek", "deepseek-v4-flash",
                        content["headline"], content["one_line_summary"], 18, 3, 2,
                        "a.json", "a.html", "a.png",
                        json.dumps(stats, ensure_ascii=False), json.dumps(content, ensure_ascii=False),
                    ),
                )
                connection.execute(
                    "INSERT INTO report_modules VALUES(?,?,?,?,?,?)",
                    (metadata["report_id"], "topics", 0, "旧索引", "{}", "旧索引"),
                )

            with HistoryStore(path) as store:
                self.assertEqual(
                    store.connection.execute("PRAGMA user_version").fetchone()[0],
                    DATABASE_SCHEMA_VERSION,
                )
                modules = store._module_keys(metadata["report_id"])
                self.assertIn("themes", modules)
                self.assertIn("topics", modules)
                self.assertIn("outcome", modules)
                self.assertNotIn("action_items", modules)
                self.assertIn("resources", modules)
                self.assertFalse(store.search_reports("旧索引"))

    def test_failed_v2_migration_keeps_v1_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "failed.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                for statement in BASE_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
            with patch.object(HistoryStore, "_migrate_v1_to_v2", side_effect=RuntimeError("boom-v2")):
                with self.assertRaisesRegex(RuntimeError, "boom-v2"):
                    HistoryStore(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_failed_v3_migration_keeps_v2_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "failed-v3.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                for statement in BASE_SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 2")
            with patch.object(HistoryStore, "_migrate_v2_to_v3", side_effect=RuntimeError("boom-v3")):
                with self.assertRaisesRegex(RuntimeError, "boom-v3"):
                    HistoryStore(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)


class HistoryCenterQueryTests(unittest.TestCase):
    def test_schema_22_default_sections_include_report_content_without_activity_totals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                report_id = store.upsert_report(history_document(root))
                detail = store.get_report_detail(report_id)
                module_keys = {item["module_key"] for item in detail["modules"]}
                self.assertTrue(
                    {
                        "topics", "ai_observations", "member_activity", "outcome",
                        "open_questions", "risk_flags", "quotes", "resources", "themes",
                    }.issubset(module_keys)
                )
                topic = next(item for item in detail["modules"] if item["module_key"] == "topics")
                self.assertNotIn("action_items", topic["content"])
                self.assertEqual(topic["content"]["outcome"]["content"], "采用新清关渠道。")
                self.assertEqual(topic["content"]["quotes"][0]["quote"], "先把清单核完再发。")
                self.assertEqual(len(topic["content"]["related_resources"]), 2)
                self.assertEqual(len(detail["resources"]), 2)
                target_ids: dict[str, list[str]] = {}
                for item in detail["modules"]:
                    if item.get("redaction_target_id"):
                        target_ids.setdefault(item["module_key"], []).append(item["redaction_target_id"])
                self.assertEqual(target_ids["topics"], ["topics:0"])
                self.assertEqual(target_ids["ai_observations"], ["ai_observations:0"])
                self.assertEqual(target_ids["outcome"], ["topics:0:outcome"])
                self.assertNotIn("action_items", target_ids)
                self.assertEqual(target_ids["resources"], ["resources:0:0", "resources:0:1"])
                valid_target_ids = {item["id"] for item in list_redaction_targets(history_document(root))}
                self.assertTrue({target_id for values in target_ids.values() for target_id in values}.issubset(valid_target_ids))
                activity_stats = [
                    item for item in detail["modules"]
                    if item["module_key"] == "member_activity" and item["title"] == "活跃统计"
                ][0]
                self.assertEqual(activity_stats["redaction_target_id"], "")
                self.assertNotIn("message_count", activity_stats["content"])
                self.assertNotIn("effective_message_count", activity_stats["content"])
                self.assertNotIn("participant_count", activity_stats["content"])

    def test_history_queries_default_to_latest_and_keep_all_versions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                report_ids = [store.upsert_report(history_document(root, version=version)) for version in (1, 2, 3)]
                latest = store.list_reports(chat_id="history@chatroom")
                self.assertEqual([item["version"] for item in latest["items"]], [3])
                all_versions = store.list_reports(
                    chat_id="history@chatroom", version_strategy="all"
                )
                self.assertEqual([item["version"] for item in all_versions["items"]], [3, 2, 1])
                versions = store.list_report_versions(report_ids[0])
                self.assertEqual([item["version"] for item in versions], [3, 2, 1])
                chats = store.list_history_chats()
                self.assertEqual(chats[0]["report_count"], 3)
                self.assertEqual(chats[0]["latest_report_date"], "2026-08-31")

    def test_module_and_keyword_filters_are_combined(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                store.upsert_report(history_document(root))
                with self.assertRaisesRegex(ValueError, "未知历史模块筛选"):
                    store.list_reports(module_filter="action_items", keyword="准备")
                self.assertEqual(
                    store.list_reports(module_filter="resources", keyword="准备")["total"],
                    0,
                )

    def test_search_covers_full_word_substring_english_mixed_and_all_required_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                store.upsert_report(history_document(root))
                queries = [
                    "今天确认 Tail clearance 清关方案与交付安排",
                    "清关",
                    "clearance",
                    "Tail 清关",
                    "跨境项目讨论群",
                    "张三",
                    "美国尾程清关",
                    "采用新清关渠道",
                    "海关编码",
                    "资料缺失",
                    "先把清单核完",
                    "清关资料清单.xlsx",
                    "https://example.com/customs-guide",
                ]
                for query in queries:
                    with self.subTest(query=query):
                        self.assertGreater(store.search_history(query)["total"], 0)

    def test_stats_only_chat_is_not_summarized(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                store.upsert_chat_daily_stats(
                    chat_id="stats-only@chatroom",
                    chat_name="只有统计",
                    date="2026-08-31",
                    stats={"message_count": 12},
                )
                store.upsert_report(history_document(root))
                self.assertEqual(store.summarized_chat_ids(), ["history@chatroom"])
                self.assertEqual([item["chat_id"] for item in store.list_history_chats()], ["history@chatroom"])

    def test_schema_21_top_level_items_remain_queryable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = history_document(root, schema_version="2.1")
            topic = document["content"]["topics"][0]
            topic["result"] = {"status": "concluded", "summary": "旧版讨论结论"}
            topic.pop("outcome", None)
            topic["action_items"] = []
            document["content"]["action_items"] = [{"task": "旧版行动事项"}]
            with HistoryStore(root / "history.sqlite3") as store:
                report_id = store.upsert_report(document)
                detail = store.get_report_detail(report_id)
                keys = {item["module_key"] for item in detail["modules"]}
                self.assertIn("outcome", keys)
                self.assertNotIn("action_items", keys)
                self.assertGreater(store.search_history("旧版讨论结论")["total"], 0)
                self.assertEqual(store.search_history("旧版行动事项")["total"], 0)
                self.assertEqual(store.list_reports(keyword="旧版行动事项")["total"], 0)
                self.assertEqual(detail["content"]["action_items"], [{"task": "旧版行动事项"}])


if __name__ == "__main__":
    unittest.main()
