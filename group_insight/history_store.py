"""SQLite 历史数据底座：报告、模块、资源、日统计与 FTS。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .desktop_config import ensure_desktop_data_dir
from .report_schema import SCHEMA_VERSION, upgrade_legacy_report


DATABASE_SCHEMA_VERSION = 1


BASE_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        last_report_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS reports (
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
    )""",
    """CREATE TABLE IF NOT EXISTS report_modules (
        report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
        module_key TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        title TEXT NOT NULL,
        content_json TEXT NOT NULL,
        search_text TEXT NOT NULL,
        PRIMARY KEY(report_id, module_key, ordinal)
    )""",
    """CREATE TABLE IF NOT EXISTS resources (
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
    )""",
    """CREATE TABLE IF NOT EXISTS report_redactions (
        report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
        target_id TEXT NOT NULL,
        module_key TEXT NOT NULL,
        time_label TEXT NOT NULL,
        notice TEXT NOT NULL,
        PRIMARY KEY(report_id, target_id)
    )""",
    """CREATE TABLE IF NOT EXISTS daily_stats (
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
    )""",
    """CREATE TABLE IF NOT EXISTS chat_daily_stats (
        chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        message_count INTEGER NOT NULL DEFAULT 0,
        effective_message_count INTEGER NOT NULL DEFAULT 0,
        participant_count INTEGER NOT NULL DEFAULT 0,
        effective_char_count INTEGER NOT NULL DEFAULT 0,
        link_count INTEGER NOT NULL DEFAULT 0,
        file_count INTEGER NOT NULL DEFAULT 0,
        calculated_at TEXT NOT NULL,
        PRIMARY KEY(chat_id, date)
    )""",
    """CREATE TABLE IF NOT EXISTS imported_files (
        path TEXT PRIMARY KEY,
        size INTEGER NOT NULL,
        modified_ns INTEGER NOT NULL,
        report_id TEXT NOT NULL
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS report_search_fts USING fts5(
        report_id UNINDEXED,
        module_key UNINDEXED,
        chat_name,
        title,
        body,
        tokenize='unicode61'
    )""",
)


def default_history_path() -> Path:
    return ensure_desktop_data_dir() / "history.sqlite3"


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_history_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        try:
            self._ensure_schema()
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    @classmethod
    def _migrate_v0_to_v1(cls, connection: sqlite3.Connection) -> None:
        for statement in BASE_SCHEMA_STATEMENTS:
            connection.execute(statement)
        if cls._table_exists(connection, "daily_stats"):
            connection.execute(
                """INSERT INTO chat_daily_stats(
                       chat_id, date, message_count, effective_message_count,
                       participant_count, effective_char_count, link_count,
                       file_count, calculated_at)
                   SELECT chat_id, report_date, message_count,
                          effective_message_count, participant_count,
                          effective_char_count, link_count, file_count,
                          generated_at
                   FROM (
                       SELECT ds.*, r.generated_at,
                              ROW_NUMBER() OVER (
                                PARTITION BY ds.chat_id, ds.report_date
                                ORDER BY r.version DESC, r.generated_at DESC, r.report_id DESC
                              ) AS row_rank
                       FROM daily_stats AS ds
                       JOIN reports AS r ON r.report_id = ds.report_id
                   )
                   WHERE row_rank = 1
                   ON CONFLICT(chat_id, date) DO UPDATE SET
                     message_count=excluded.message_count,
                     effective_message_count=excluded.effective_message_count,
                     participant_count=excluded.participant_count,
                     effective_char_count=excluded.effective_char_count,
                     link_count=excluded.link_count,
                     file_count=excluded.file_count,
                     calculated_at=excluded.calculated_at"""
            )

    def _ensure_schema(self) -> None:
        current_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > DATABASE_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {current_version} 高于当前程序支持的 {DATABASE_SCHEMA_VERSION}。"
            )
        migrations = {1: self._migrate_v0_to_v1}
        for target_version in range(current_version + 1, DATABASE_SCHEMA_VERSION + 1):
            migration = migrations.get(target_version)
            if migration is None:
                raise RuntimeError(f"缺少 SQLite migration: v{target_version - 1} -> v{target_version}")
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                migration(self.connection)
                self.connection.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('report_schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
                self.connection.execute(f"PRAGMA user_version = {target_version}")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('report_schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def _module_rows(content: dict[str, Any]) -> list[tuple[str, int, str, Any]]:
        rows: list[tuple[str, int, str, Any]] = []
        singular = [
            ("one_line_summary", content.get("one_line_summary", "")),
            ("lead_summary", content.get("lead_summary", "")),
            ("mood", content.get("mood", {})),
            ("conclusion", content.get("conclusion", "")),
        ]
        for key, value in singular:
            if value:
                rows.append((key, 0, key, value))
        for key in (
            "themes", "topics", "ai_observations", "members", "quotes", "decisions",
            "action_items", "open_questions", "risk_flags",
        ):
            for index, item in enumerate(content.get(key, []) or []):
                title = str(item.get("title") or item.get("name") or key) if isinstance(item, dict) else key
                rows.append((key, index, title, item))
        return rows

    @staticmethod
    def _write_chat_daily_stats(
        connection: sqlite3.Connection,
        chat_id: str,
        date: str,
        stats: dict[str, Any],
        calculated_at: str,
    ) -> None:
        resources = stats.get("resource_breakdown", {})
        connection.execute(
            """INSERT INTO chat_daily_stats(
                   chat_id, date, message_count, effective_message_count,
                   participant_count, effective_char_count, link_count,
                   file_count, calculated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(chat_id, date) DO UPDATE SET
                 message_count=excluded.message_count,
                 effective_message_count=excluded.effective_message_count,
                 participant_count=excluded.participant_count,
                 effective_char_count=excluded.effective_char_count,
                 link_count=excluded.link_count,
                 file_count=excluded.file_count,
                 calculated_at=excluded.calculated_at""",
            (
                chat_id, date, int(stats.get("message_count") or 0),
                int(stats.get("effective_message_count") or 0),
                int(stats.get("participant_count") or 0),
                int(stats.get("effective_char_count") or 0),
                int(resources.get("link") or stats.get("link_count") or 0),
                int(resources.get("file") or stats.get("file_count") or 0),
                calculated_at,
            ),
        )

    def upsert_chat_daily_stats(
        self,
        *,
        chat_id: str,
        chat_name: str,
        date: str,
        stats: dict[str, Any],
        calculated_at: str | None = None,
    ) -> None:
        """保存不依赖报告存在的群聊日统计。"""

        timestamp = calculated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.connection:
            self.connection.execute(
                """INSERT INTO chats(chat_id, display_name, first_seen_at, last_seen_at, last_report_at)
                   VALUES(?, ?, ?, ?, '')
                   ON CONFLICT(chat_id) DO UPDATE SET
                     display_name=excluded.display_name,
                     last_seen_at=excluded.last_seen_at""",
                (chat_id, chat_name, timestamp, timestamp),
            )
            self._write_chat_daily_stats(self.connection, chat_id, date, stats, timestamp)

    def get_chat_daily_stats(
        self,
        chat_id: str,
        *,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["chat_id = ?"]
        parameters: list[Any] = [chat_id]
        if start_date:
            clauses.append("date >= ?")
            parameters.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            parameters.append(end_date)
        rows = self.connection.execute(
            f"SELECT * FROM chat_daily_stats WHERE {' AND '.join(clauses)} ORDER BY date",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_report(
        self,
        document: dict[str, Any],
        *,
        daily_stats: list[dict[str, Any]] | None = None,
    ) -> str:
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
                    body = " ".join(
                        str(value or "")
                        for value in (
                            group.get("topic"), item.get("title"), item.get("url"),
                            item.get("sender"), item.get("context_summary"),
                        )
                    )
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
            stat_rows = daily_stats
            if stat_rows is None and str(period.get("start") or "")[:10] == str(period.get("end") or "")[:10]:
                stat_rows = [{"date": period["report_date"], **stats}]
            for stat_row in stat_rows or []:
                stat_date = str(stat_row.get("date") or "").strip()
                if not stat_date:
                    continue
                self._write_chat_daily_stats(
                    self.connection,
                    str(chat["id"]),
                    stat_date,
                    stat_row,
                    str(stat_row.get("calculated_at") or generated_at),
                )
        return report_id

    def search_reports(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """搜索历史报告索引；FTS 无命中或不适合时补充安全子串匹配。"""

        normalized = " ".join(str(query or "").split())
        if not normalized:
            return []
        safe_limit = max(1, int(limit))
        result_rows: list[sqlite3.Row] = []
        seen: set[tuple[str, str, str]] = set()

        phrase = '"' + normalized.replace('"', '""') + '"'
        try:
            result_rows.extend(
                self.connection.execute(
                    """SELECT report_id, module_key, chat_name, title, body
                       FROM report_search_fts
                       WHERE report_search_fts MATCH ?
                       LIMIT ?""",
                    (phrase, safe_limit),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            pass

        terms = [term.casefold() for term in normalized.split() if term]
        haystack = "lower(coalesce(chat_name,'') || ' ' || coalesce(title,'') || ' ' || coalesce(body,''))"
        conditions = [f"instr({haystack}, ?) > 0" for _term in terms]
        parameters: list[Any] = [*terms, safe_limit]
        result_rows.extend(
            self.connection.execute(
                f"""SELECT report_id, module_key, chat_name, title, body
                    FROM report_search_fts
                    WHERE {' AND '.join(conditions)}
                    LIMIT ?""",
                parameters,
            ).fetchall()
        )

        results: list[dict[str, Any]] = []
        for row in result_rows:
            key = (str(row["report_id"]), str(row["module_key"]), str(row["title"]))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "report_id": key[0],
                    "module_key": key[1],
                    "chat_name": str(row["chat_name"]),
                    "title": key[2],
                    "snippet": str(row["body"])[:320],
                }
            )
            if len(results) >= safe_limit:
                break
        return results

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
