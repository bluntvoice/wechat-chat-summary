"""SQLite 历史数据底座：报告、模块、资源、日统计与 FTS。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .desktop_config import desktop_data_dir
from .report_schema import SCHEMA_VERSION, upgrade_legacy_report


def default_history_path() -> Path:
    return desktop_data_dir() / "history.sqlite3"


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_history_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_report_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                report_date TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                version INTEGER NOT NULL,
                schema_version TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                headline TEXT NOT NULL,
                one_line_summary TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                participant_count INTEGER NOT NULL DEFAULT 0,
                resource_count INTEGER NOT NULL DEFAULT 0,
                json_path TEXT NOT NULL,
                html_path TEXT NOT NULL,
                png_path TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                content_json TEXT NOT NULL,
                UNIQUE(chat_id, period_start, period_end, version)
            );
            CREATE TABLE IF NOT EXISTS report_modules (
                report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
                module_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                content_json TEXT NOT NULL,
                search_text TEXT NOT NULL,
                PRIMARY KEY(report_id, module_key, ordinal)
            );
            CREATE TABLE IF NOT EXISTS resources (
                resource_id TEXT NOT NULL,
                report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
                topic_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                sender TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                context_summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY(resource_id, report_id)
            );
            CREATE TABLE IF NOT EXISTS report_redactions (
                report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
                target_id TEXT NOT NULL,
                module_key TEXT NOT NULL,
                time_label TEXT NOT NULL,
                notice TEXT NOT NULL,
                PRIMARY KEY(report_id, target_id)
            );
            CREATE TABLE IF NOT EXISTS daily_stats (
                chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                report_date TEXT NOT NULL,
                report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
                message_count INTEGER NOT NULL DEFAULT 0,
                effective_message_count INTEGER NOT NULL DEFAULT 0,
                participant_count INTEGER NOT NULL DEFAULT 0,
                effective_char_count INTEGER NOT NULL DEFAULT 0,
                link_count INTEGER NOT NULL DEFAULT 0,
                file_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id, report_date, report_id)
            );
            CREATE TABLE IF NOT EXISTS imported_files (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                report_id TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS report_search_fts USING fts5(
                report_id UNINDEXED,
                module_key UNINDEXED,
                chat_name,
                title,
                body,
                tokenize='unicode61'
            );
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('report_schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        self.connection.commit()

    @staticmethod
    def _module_rows(content: dict[str, Any]) -> list[tuple[str, int, str, Any]]:
        rows: list[tuple[str, int, str, Any]] = []
        singular = [
            ("one_line_summary", content.get("one_line_summary", "")),
            ("lead_summary", content.get("lead_summary", "")),
            ("mood", content.get("mood", {})),
        ]
        for key, value in singular:
            if value:
                rows.append((key, 0, key, value))
        for key in ("themes", "topics", "members", "quotes", "decisions", "action_items", "open_questions", "risk_flags"):
            for index, item in enumerate(content.get(key, []) or []):
                title = str(item.get("title") or item.get("name") or key) if isinstance(item, dict) else key
                rows.append((key, index, title, item))
        return rows

    def upsert_report(self, document: dict[str, Any]) -> str:
        metadata = document["metadata"]
        chat = metadata["chat"]
        period = metadata["period"]
        ai = metadata.get("ai", {})
        exports = metadata.get("exports", {})
        stats = document.get("stats", {})
        content = document.get("content", {})
        resources = content.get("resources", {})
        report_id = str(metadata["report_id"])
        generated_at = str(metadata.get("generated_at") or "")
        with self.connection:
            self.connection.execute(
                """INSERT INTO chats(chat_id, display_name, first_seen_at, last_seen_at, last_report_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                     display_name=excluded.display_name,
                     last_seen_at=excluded.last_seen_at,
                     last_report_at=excluded.last_report_at""",
                (chat["id"], chat["name"], generated_at, generated_at, generated_at),
            )
            self.connection.execute(
                """INSERT INTO reports(
                       report_id, chat_id, report_date, period_start, period_end, version,
                       schema_version, generated_at, provider, model, headline, one_line_summary,
                       message_count, participant_count, resource_count, json_path, html_path,
                       png_path, stats_json, content_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(report_id) DO UPDATE SET
                     generated_at=excluded.generated_at, provider=excluded.provider,
                     model=excluded.model, headline=excluded.headline,
                     one_line_summary=excluded.one_line_summary,
                     message_count=excluded.message_count,
                     participant_count=excluded.participant_count,
                     resource_count=excluded.resource_count,
                     json_path=excluded.json_path, html_path=excluded.html_path,
                     png_path=excluded.png_path, stats_json=excluded.stats_json,
                     content_json=excluded.content_json""",
                (
                    report_id, chat["id"], period["report_date"], period["start"], period["end"],
                    int(metadata.get("version") or 1), document.get("schema_version", ""), generated_at,
                    str(ai.get("provider") or ""), str(ai.get("model") or ""),
                    str(content.get("headline") or ""), str(content.get("one_line_summary") or ""),
                    int(stats.get("message_count") or 0), int(stats.get("participant_count") or 0),
                    int(resources.get("count") or 0), str(exports.get("json") or ""),
                    str(exports.get("html") or ""), str(exports.get("png") or ""),
                    json.dumps(stats, ensure_ascii=False), json.dumps(content, ensure_ascii=False),
                ),
            )
            self.connection.execute("DELETE FROM report_modules WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM resources WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM report_redactions WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM daily_stats WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM report_search_fts WHERE report_id=?", (report_id,))
            for module_key, ordinal, title, value in self._module_rows(content):
                body = json.dumps(value, ensure_ascii=False)
                self.connection.execute(
                    "INSERT INTO report_modules VALUES(?,?,?,?,?,?)",
                    (report_id, module_key, ordinal, title, body, body),
                )
                self.connection.execute(
                    "INSERT INTO report_search_fts(report_id,module_key,chat_name,title,body) VALUES(?,?,?,?,?)",
                    (report_id, module_key, chat["name"], title, body),
                )
            link_count = 0
            file_count = 0
            for group in resources.get("groups", []) or []:
                if not isinstance(group, dict) or group.get("redacted"):
                    continue
                for item in group.get("items", []) or []:
                    if not isinstance(item, dict) or item.get("redacted"):
                        continue
                    resource_type = str(item.get("type") or "")
                    link_count += int(resource_type == "link")
                    file_count += int(resource_type == "file")
                    self.connection.execute(
                        "INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(item.get("id") or ""), report_id, str(group.get("topic_id") or "other"),
                            str(group.get("topic") or "其他 / 未归类"), resource_type,
                            str(item.get("title") or ""), str(item.get("url") or ""),
                            str(item.get("sender") or ""), str(item.get("sent_at") or ""),
                            str(item.get("context_summary") or ""), json.dumps(item, ensure_ascii=False),
                        ),
                    )
                    body = " ".join(str(item.get(key) or "") for key in ("title", "url", "sender", "context_summary"))
                    self.connection.execute(
                        "INSERT INTO report_search_fts(report_id,module_key,chat_name,title,body) VALUES(?,?,?,?,?)",
                        (report_id, "resources", chat["name"], str(item.get("title") or ""), body),
                    )
            for item in document.get("redactions", []) or []:
                if not isinstance(item, dict):
                    continue
                self.connection.execute(
                    "INSERT OR REPLACE INTO report_redactions VALUES(?,?,?,?,?)",
                    (
                        report_id, str(item.get("target_id") or ""), str(item.get("module_key") or ""),
                        str(item.get("time_label") or ""), str(item.get("notice") or ""),
                    ),
                )
            self.connection.execute(
                "INSERT INTO daily_stats VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    chat["id"], period["report_date"], report_id,
                    int(stats.get("message_count") or 0), int(stats.get("effective_message_count") or 0),
                    int(stats.get("participant_count") or 0), int(stats.get("effective_char_count") or 0),
                    int(stats.get("resource_breakdown", {}).get("link", link_count)),
                    int(stats.get("resource_breakdown", {}).get("file", file_count)),
                ),
            )
        return report_id

    def import_export_root(self, export_root: Path) -> dict[str, int]:
        result = {"scanned": 0, "imported": 0, "skipped": 0, "failed": 0}
        if not export_root.is_dir():
            return result
        for path in export_root.glob("*/报告数据/*报告数据*/*_群聊总结*.json"):
            result["scanned"] += 1
            stat = path.stat()
            cached = self.connection.execute(
                "SELECT size, modified_ns FROM imported_files WHERE path=?", (str(path),)
            ).fetchone()
            if cached and int(cached["size"]) == stat.st_size and int(cached["modified_ns"]) == stat.st_mtime_ns:
                result["skipped"] += 1
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                document = upgrade_legacy_report(payload, path)
                report_id = self.upsert_report(document)
                with self.connection:
                    self.connection.execute(
                        "INSERT OR REPLACE INTO imported_files VALUES(?,?,?,?)",
                        (str(path), stat.st_size, stat.st_mtime_ns, report_id),
                    )
                result["imported"] += 1
            except Exception:
                result["failed"] += 1
        return result

    def summarized_chat_ids(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT chat_id FROM chats ORDER BY last_report_at DESC"
        ).fetchall()
        return [str(row["chat_id"]) for row in rows]
