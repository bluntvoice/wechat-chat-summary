from __future__ import annotations

import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_bridge import _generate
from group_insight.desktop_config import (
    desktop_data_dir,
    migrate_legacy_desktop_data,
)
from group_insight.history_store import (
    BASE_SCHEMA_STATEMENTS,
    DATABASE_SCHEMA_VERSION,
    HistoryStore,
)
from group_insight.report_schema import build_report_document


def searchable_document(root: Path) -> dict[str, object]:
    return build_report_document(
        ctx={"username": "clearance@chatroom", "display_name": "跨境清关讨论群"},
        start_time="2026-08-31 00:00:00",
        end_time="2026-08-31 23:59:59",
        version=1,
        stats={
            "message_count": 12,
            "effective_message_count": 10,
            "participant_count": 3,
            "effective_char_count": 260,
            "resource_breakdown": {"link": 1, "file": 1},
        },
        report={
            "one_line_summary": "今天主要讨论美国尾程清关风险及资料准备",
            "theme_cards": [{"title": "尾程清关", "summary": "核对风险与资料"}],
            "sections": [
                {
                    "id": "topic-clearance",
                    "title": "美国尾程清关风险",
                    "discussion_flow": "今天主要讨论美国尾程清关风险及资料准备，Tail clearance 需要复核。",
                    "action_items": [{"task": "准备尾程清关资料", "owner": "张三"}],
                    "open_questions": [{"question": "海关编码是否需要调整"}],
                    "resource_ids": ["res-link", "res-file"],
                }
            ],
            "participant_insights": [{"name": "张三", "insight": "负责清关资料复核"}],
        },
        resources={
            "count": 2,
            "groups": [
                {
                    "topic_id": "topic-clearance",
                    "topic": "清关资料",
                    "summary": "报关参考资料",
                    "items": [
                        {
                            "id": "res-link",
                            "type": "link",
                            "title": "美国海关政策说明",
                            "url": "https://example.com/customs-guide",
                            "sender": "李四",
                            "context_summary": "尾程政策资源",
                        },
                        {
                            "id": "res-file",
                            "type": "file",
                            "title": "清关资料清单.xlsx",
                            "url": "",
                            "sender": "王五",
                            "context_summary": "待填写文件",
                        },
                    ],
                }
            ],
        },
        exports={
            "json": str(root / "report.json"),
            "html": str(root / "report.html"),
            "png": str(root / "report.png"),
        },
        provider="deepseek",
        model="deepseek-v4-flash",
        dry_run=False,
        chunk_count=1,
        chunk_plan={},
    )


class DesktopDataMigrationTests(unittest.TestCase):
    def test_tauri_resolved_app_local_data_dir_is_preferred(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "WECHAT_CHAT_SUMMARY_APP_LOCAL_DATA_DIR": temp_dir,
                "LOCALAPPDATA": str(Path(temp_dir).parent),
            },
            clear=True,
        ):
            self.assertEqual(desktop_data_dir(), Path(temp_dir))

    def test_legacy_data_is_verified_and_copied_without_deleting_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "legacy"
            target = root / "appdata"
            legacy.mkdir()
            (legacy / "config.json").write_text(
                json.dumps({"export_root": r"F:\自定义报告"}, ensure_ascii=False), encoding="utf-8"
            )
            (legacy / "secrets.env").write_text("DEEPSEEK_API_KEY=test-only\n", encoding="utf-8")
            with closing(sqlite3.connect(legacy / "history.sqlite3")) as connection, connection:
                connection.execute("CREATE TABLE proof(value TEXT)")
                connection.execute("INSERT INTO proof VALUES('retained')")

            result = migrate_legacy_desktop_data(target, legacy)
            self.assertEqual(result["status"], "migrated")
            self.assertTrue((legacy / "config.json").is_file())
            self.assertEqual(
                json.loads((target / "config.json").read_text(encoding="utf-8"))["export_root"],
                r"F:\自定义报告",
            )
            with closing(sqlite3.connect(target / "history.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT value FROM proof").fetchone()[0], "retained")
            self.assertEqual(
                migrate_legacy_desktop_data(target, legacy)["status"], "already-migrated"
            )

    def test_existing_target_config_is_never_overwritten(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "legacy"
            target = root / "appdata"
            legacy.mkdir()
            target.mkdir()
            (legacy / "config.json").write_text('{"export_root":"legacy"}', encoding="utf-8")
            (target / "config.json").write_text('{"export_root":"current"}', encoding="utf-8")
            result = migrate_legacy_desktop_data(target, legacy)
            self.assertEqual(result["status"], "target-in-use")
            self.assertIn("current", (target / "config.json").read_text(encoding="utf-8"))


class DatabaseMigrationTests(unittest.TestCase):
    def test_v0_database_migrates_latest_daily_stats_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                for statement in BASE_SCHEMA_STATEMENTS:
                    if "CREATE TABLE IF NOT EXISTS chat_daily_stats" not in statement:
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO chats VALUES(?,?,?,?,?)",
                    ("room", "旧群", "2026-08-01", "2026-08-31", "2026-08-31"),
                )
                report_values = (
                    "room", "2026-08-31", "2026-08-31 00:00:00", "2026-08-31 23:59:59",
                    "2.1", "deepseek", "model", "标题", "摘要", 1, 1, 0,
                    "a.json", "a.html", "a.png", "{}", "{}",
                )
                connection.execute(
                    """INSERT INTO reports(
                       report_id, chat_id, report_date, period_start, period_end, version,
                       schema_version, generated_at, provider, model, headline, one_line_summary,
                       message_count, participant_count, resource_count, json_path, html_path,
                       png_path, stats_json, content_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("report-old", *report_values[:4], 1, report_values[4], "2026-08-31 10:00:00", *report_values[5:]),
                )
                connection.execute(
                    """INSERT INTO reports(
                       report_id, chat_id, report_date, period_start, period_end, version,
                       schema_version, generated_at, provider, model, headline, one_line_summary,
                       message_count, participant_count, resource_count, json_path, html_path,
                       png_path, stats_json, content_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("report-new", *report_values[:4], 2, report_values[4], "2026-08-31 12:00:00", *report_values[5:]),
                )
                connection.execute(
                    "INSERT INTO daily_stats VALUES(?,?,?,?,?,?,?,?,?)",
                    ("room", "2026-08-31", "report-old", 10, 8, 2, 100, 1, 0),
                )
                connection.execute(
                    "INSERT INTO daily_stats VALUES(?,?,?,?,?,?,?,?,?)",
                    ("room", "2026-08-31", "report-new", 20, 18, 3, 260, 2, 1),
                )

            with HistoryStore(path) as store:
                self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], DATABASE_SCHEMA_VERSION)
                row = store.get_chat_daily_stats("room")[0]
                self.assertEqual(row["message_count"], 20)
                self.assertEqual(row["file_count"], 1)
            with HistoryStore(path) as store:
                self.assertEqual(len(store.get_chat_daily_stats("room")), 1)

    def test_failed_migration_does_not_advance_user_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "failed.sqlite3"
            sqlite3.connect(path).close()
            with patch.object(HistoryStore, "_migrate_v0_to_v1", side_effect=RuntimeError("boom")):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    HistoryStore(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_daily_stats_can_exist_without_a_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(path) as store:
                store.upsert_chat_daily_stats(
                    chat_id="room",
                    chat_name="统计群",
                    date="2026-08-30",
                    stats={
                        "message_count": 88,
                        "effective_message_count": 70,
                        "participant_count": 9,
                        "effective_char_count": 1500,
                        "resource_breakdown": {"link": 3, "file": 2},
                    },
                )
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 0)
                self.assertEqual(store.get_chat_daily_stats("room")[0]["message_count"], 88)


class ChineseSearchTests(unittest.TestCase):
    def test_chinese_substrings_and_history_fields_are_searchable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as store:
                store.upsert_report(searchable_document(root))
                queries = [
                    "今天主要讨论美国尾程清关风险及资料准备",
                    "清关",
                    "跨境清关讨论群",
                    "张三",
                    "美国尾程清关风险",
                    "准备尾程清关资料",
                    "清关资料清单.xlsx",
                    "美国海关政策说明",
                    "https://example.com/customs-guide",
                    "Tail 清关",
                ]
                for query in queries:
                    with self.subTest(query=query):
                        self.assertTrue(store.search_reports(query), query)


class StructuredResultProtocolTests(unittest.TestCase):
    def test_desktop_generation_uses_result_file_not_human_log_labels(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(Path(temp_dir) / "data")}
        ):
            export_root = Path(temp_dir) / "reports"

            def fake_run(command: list[str], **_kwargs: object):
                result_path = Path(command[command.index("--result-file") + 1])
                output_dir = export_root / "测试群" / "报告数据" / "2026-08-31报告数据"
                image_dir = export_root / "测试群" / "导出图" / "2026" / "08"
                output_dir.mkdir(parents=True)
                image_dir.mkdir(parents=True)
                json_path = output_dir / "report.json"
                html_path = output_dir / "report.html"
                png_path = image_dir / "report.png"
                json_path.write_text("{}", encoding="utf-8")
                html_path.write_text("<html></html>", encoding="utf-8")
                png_path.write_bytes(b"png")
                result_path.write_text(
                    json.dumps(
                        {
                            "completed": True,
                            "protocol_version": 1,
                            "version": 1,
                            "chat_dir": str(export_root / "测试群"),
                            "data_dir": str(output_dir),
                            "image_dir": str(image_dir),
                            "json_path": str(json_path),
                            "html_path": str(html_path),
                            "png_path": str(png_path),
                            "png_error": "",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "日志文案已经完全变化\n", "stderr": ""},
                )()

            settings = {
                "provider": "deepseek",
                "api_key": "test-key",
                "api_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-v4-flash",
                "wechat_api_url": "http://127.0.0.1:10392",
                "image_dpi": 300,
                "export_root": str(export_root),
            }
            with patch("group_insight.desktop_bridge.subprocess.run", side_effect=fake_run):
                result = _generate(
                    settings,
                    {
                        "job_id": "test-job",
                        "chat": "room@chatroom",
                        "chat_name": "测试群",
                        "start": "2026-08-31 00:00:00",
                        "end": "2026-08-31 23:59:59",
                        "range_mode": "single",
                        "export_root": str(export_root),
                    },
                )
            self.assertEqual(result["protocol_version"], 1)
            self.assertTrue(Path(result["png_path"]).is_file())
            self.assertIn("日志文案已经完全变化", result["log"])


if __name__ == "__main__":
    unittest.main()
