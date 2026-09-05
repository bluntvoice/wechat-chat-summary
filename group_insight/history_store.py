"""SQLite 历史数据底座：报告、模块、资源、日统计与 FTS。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .desktop_config import ensure_desktop_data_dir
from .member_references import (
    member_names_from_stats,
    normalize_member_reference_text,
    normalize_member_references,
)
from .report_model import BLOCKED_OBSERVATION_PHRASES
from .report_schema import SCHEMA_VERSION, upgrade_legacy_report


DATABASE_SCHEMA_VERSION = 3

HISTORY_MODULE_ORDER = (
    "summary",
    "themes",
    "topics",
    "ai_observations",
    "member_activity",
    "outcome",
    "open_questions",
    "risk_flags",
    "quotes",
    "resources",
)

HISTORY_MODULE_LABELS = {
    "summary": "今日总览",
    "themes": "今日速览",
    "topics": "今日主要话题",
    "ai_observations": "AI 今日观察",
    "member_activity": "今日活跃情况",
    "outcome": "讨论结论",
    "open_questions": "开放问题",
    "risk_flags": "风险提示",
    "quotes": "代表性原话",
    "resources": "资源",
}

HISTORY_FILTER_KEYS = set(HISTORY_MODULE_ORDER) - {"summary"}


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

    @classmethod
    def _migrate_v1_to_v2(cls, connection: sqlite3.Connection) -> None:
        """为桌面历史查询补索引，并把旧模块行重建为 Schema 2.2 逻辑模块。"""

        connection.execute(
            "CREATE INDEX IF NOT EXISTS reports_history_lookup_idx "
            "ON reports(chat_id, period_start, period_end, version DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS reports_date_idx "
            "ON reports(report_date DESC, generated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS report_modules_filter_idx "
            "ON report_modules(module_key, report_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS resources_report_idx ON resources(report_id, topic_id)"
        )
        rows = connection.execute(
            """SELECT r.report_id, c.display_name, r.content_json, r.stats_json
               FROM reports AS r
               JOIN chats AS c ON c.chat_id = r.chat_id"""
        ).fetchall()
        for row in rows:
            try:
                content = json.loads(str(row["content_json"] or "{}"))
                stats = json.loads(str(row["stats_json"] or "{}"))
            except json.JSONDecodeError:
                content, stats = {}, {}
            cls._replace_report_index(
                connection,
                str(row["report_id"]),
                str(row["display_name"]),
                content if isinstance(content, dict) else {},
                stats if isinstance(stats, dict) else {},
            )

    @classmethod
    def _migrate_v2_to_v3(cls, connection: sqlite3.Connection) -> None:
        """按报告一级板块重建历史索引，并加入今日速览模块。"""

        rows = connection.execute(
            """SELECT r.report_id, c.display_name, r.content_json, r.stats_json
               FROM reports AS r
               JOIN chats AS c ON c.chat_id = r.chat_id"""
        ).fetchall()
        for row in rows:
            try:
                content = json.loads(str(row["content_json"] or "{}"))
                stats = json.loads(str(row["stats_json"] or "{}"))
            except json.JSONDecodeError:
                content, stats = {}, {}
            cls._replace_report_index(
                connection,
                str(row["report_id"]),
                str(row["display_name"]),
                content if isinstance(content, dict) else {},
                stats if isinstance(stats, dict) else {},
            )

    def _ensure_schema(self) -> None:
        current_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > DATABASE_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {current_version} 高于当前程序支持的 {DATABASE_SCHEMA_VERSION}。"
            )
        migrations = {
            1: self._migrate_v0_to_v1,
            2: self._migrate_v1_to_v2,
            3: self._migrate_v2_to_v3,
        }
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
    def _item_title(value: Any, fallback: str) -> str:
        if not isinstance(value, dict):
            return fallback
        for key in ("title", "name", "task", "question", "content", "quote", "summary"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                return candidate[:140]
        return fallback

    @classmethod
    def _module_rows(
        cls,
        content: dict[str, Any],
        stats: dict[str, Any] | None = None,
    ) -> list[tuple[str, int, str, Any, str]]:
        """把不同 Report Schema 派生为历史 UI 的稳定逻辑模块。"""

        stats = stats or {}
        rows: list[tuple[str, int, str, Any, str]] = []
        seen: dict[str, set[str]] = {}

        def target_id(value: Any, fallback: str) -> str:
            if isinstance(value, dict) and str(value.get("redaction_id") or "").strip():
                return str(value["redaction_id"]).strip()
            return fallback

        def add(module_key: str, title: str, value: Any, redaction_target_id: str = "") -> None:
            if value in (None, "", [], {}):
                return
            signature = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            bucket = seen.setdefault(module_key, set())
            if signature in bucket:
                return
            bucket.add(signature)
            ordinal = sum(1 for row in rows if row[0] == module_key)
            rows.append((
                module_key,
                ordinal,
                str(title or HISTORY_MODULE_LABELS[module_key]),
                value,
                redaction_target_id,
            ))

        summary = {
            key: content.get(key)
            for key in ("headline", "one_line_summary", "lead_summary")
            if content.get(key)
        }
        add("summary", "报告摘要", summary)

        themes = [
            (source_index, item)
            for source_index, item in enumerate(content.get("themes", []) or [])
            if isinstance(item, dict)
        ]
        for display_index, (source_index, item) in enumerate(themes, 1):
            add(
                "themes",
                cls._item_title(item, f"今日速览 {display_index}"),
                item,
                target_id(item, f"themes:{source_index}"),
            )

        resources = content.get("resources", {}) if isinstance(content.get("resources"), dict) else {}
        resource_groups = [
            (group_index, group)
            for group_index, group in enumerate(resources.get("groups", []) or [])
            if isinstance(group, dict) and not group.get("redacted")
        ]
        assigned_resource_groups: set[int] = set()

        topics = [
            (source_index, item)
            for source_index, item in enumerate(content.get("topics", []) or [])
            if isinstance(item, dict)
        ]
        for display_index, (source_index, topic) in enumerate(topics, 1):
            topic_id = str(topic.get("id") or "")
            linked_resource_ids = {str(value) for value in topic.get("resource_ids", []) or []}
            related_resources: list[dict[str, Any]] = []
            for group_index, group in resource_groups:
                items = [
                    item for item in group.get("items", []) or []
                    if isinstance(item, dict) and not item.get("redacted")
                ]
                if (topic_id and str(group.get("topic_id") or "") == topic_id) or any(
                    str(item.get("id") or "") in linked_resource_ids for item in items
                ):
                    assigned_resource_groups.add(group_index)
                    related_resources.extend(
                        {"topic": str(group.get("topic") or "相关资源"), **item}
                        for item in items
                    )
            core = {
                key: topic.get(key)
                for key in (
                    "id", "title", "start_time", "end_time", "time_ranges",
                    "discussion_flow", "summary", "outcome", "result", "takeaway",
                    "open_questions", "risk_flags", "quotes", "redacted", "time_label", "notice",
                )
                if topic.get(key) not in (None, "", [], {})
            }
            if related_resources:
                core["related_resources"] = related_resources
            add(
                "topics",
                cls._item_title(topic, f"主要话题 {display_index}"),
                core,
                target_id(topic, f"topics:{source_index}"),
            )

        for group_index, group in resource_groups:
            if group_index in assigned_resource_groups:
                continue
            items = [
                {"topic": str(group.get("topic") or "其他 / 未归类"), **item}
                for item in group.get("items", []) or []
                if isinstance(item, dict) and not item.get("redacted")
            ]
            if items:
                add(
                    "topics",
                    "其他 / 未归类资源",
                    {
                        "title": "其他 / 未归类资源",
                        "discussion_flow": "以下链接或文件暂时无法可靠关联到某个主要话题。",
                        "related_resources": items,
                    },
                )

        for source_index, item in enumerate(content.get("ai_observations", []) or []):
            observation_text = json.dumps(item, ensure_ascii=False, default=str)
            if any(phrase in observation_text for phrase in BLOCKED_OBSERVATION_PHRASES):
                continue
            add(
                "ai_observations",
                cls._item_title(item, "AI 今日观察"),
                item,
                target_id(item, f"ai_observations:{source_index}"),
            )

        for source_index, item in enumerate(content.get("members", []) or []):
            add(
                "member_activity",
                cls._item_title(item, "成员观察"),
                item,
                target_id(item, f"members:{source_index}"),
            )
        activity = {
            key: stats.get(key)
            for key in (
                "top_speakers", "word_cloud", "time_segment_breakdown",
            )
            if stats.get(key) not in (None, "", [], {})
        }
        add("member_activity", "活跃统计", activity)

        for topic_index, topic in topics:
            topic_context = {
                "topic_id": str(topic.get("id") or ""),
                "topic_title": str(topic.get("title") or "主要话题"),
            }
            outcome = topic.get("outcome")
            if not outcome and isinstance(topic.get("result"), dict):
                result = topic["result"]
                if str(result.get("status") or "") == "concluded":
                    outcome = {"content": result.get("summary", "")}
            if outcome:
                value = {**topic_context, **outcome} if isinstance(outcome, dict) else {
                    **topic_context, "content": outcome,
                }
                outcome_target = target_id(outcome, f"topics:{topic_index}:outcome") if isinstance(topic.get("outcome"), dict) else ""
                add("outcome", cls._item_title(value, topic_context["topic_title"]), value, outcome_target)
            for module_key in ("open_questions", "risk_flags", "quotes"):
                for item_index, item in enumerate(topic.get(module_key, []) or []):
                    value = {**topic_context, **item} if isinstance(item, dict) else {
                        **topic_context, "content": item,
                    }
                    item_target = target_id(item, f"topics:{topic_index}:{module_key}:{item_index}") if isinstance(item, dict) else ""
                    add(module_key, cls._item_title(value, HISTORY_MODULE_LABELS[module_key]), value, item_target)

        legacy_outcomes = content.get("decisions", []) or []
        decision_count = len(content.get("decisions", []) or [])
        for source_index, item in enumerate(legacy_outcomes):
            item_target = target_id(item, f"decisions:{source_index}") if source_index < decision_count else ""
            add("outcome", cls._item_title(item, "讨论结论"), item, item_target)
        for module_key in ("open_questions", "risk_flags", "quotes"):
            for source_index, item in enumerate(content.get(module_key, []) or []):
                add(
                    module_key,
                    cls._item_title(item, HISTORY_MODULE_LABELS[module_key]),
                    item,
                    target_id(item, f"{module_key}:{source_index}"),
                )

        for group_index, group in enumerate(resources.get("groups", []) or []):
            if not isinstance(group, dict) or group.get("redacted"):
                continue
            for item_index, item in enumerate(group.get("items", []) or []):
                if not isinstance(item, dict) or item.get("redacted"):
                    continue
                value = {
                    "topic_id": str(group.get("topic_id") or "other"),
                    "topic": str(group.get("topic") or "其他 / 未归类"),
                    **item,
                }
                add(
                    "resources",
                    cls._item_title(item, "资源"),
                    value,
                    target_id(item, f"resources:{group_index}:{item_index}"),
                )
        return rows

    @classmethod
    def _replace_report_index(
        cls,
        connection: sqlite3.Connection,
        report_id: str,
        chat_name: str,
        content: dict[str, Any],
        stats: dict[str, Any],
    ) -> None:
        connection.execute("DELETE FROM report_modules WHERE report_id=?", (report_id,))
        connection.execute("DELETE FROM report_search_fts WHERE report_id=?", (report_id,))
        for module_key, ordinal, title, value, _target_id in cls._module_rows(content, stats):
            body = json.dumps(value, ensure_ascii=False)
            connection.execute(
                "INSERT INTO report_modules VALUES(?,?,?,?,?,?)",
                (report_id, module_key, ordinal, title, body, body),
            )
            if module_key in {"summary", "themes", "topics", "ai_observations", "member_activity"}:
                connection.execute(
                    "INSERT INTO report_search_fts(report_id,module_key,chat_name,title,body) VALUES(?,?,?,?,?)",
                    (report_id, module_key, chat_name, title, body),
                )

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

    def upsert_chat_daily_stats_many(
        self,
        *,
        chat_id: str,
        chat_name: str,
        rows: list[dict[str, Any]],
        calculated_at: str | None = None,
    ) -> None:
        """在一个事务中保存多天聚合结果，不持久化原始消息。"""

        if not rows:
            return
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
            for row in rows:
                row_date = str(row.get("date") or "").strip()
                if not row_date:
                    raise ValueError("日统计记录缺少 date。")
                self._write_chat_daily_stats(
                    self.connection,
                    chat_id,
                    row_date,
                    row,
                    str(row.get("calculated_at") or timestamp),
                )

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

    def get_report_links_by_date(
        self,
        chat_id: str,
        *,
        start_date: str,
        end_date: str,
    ) -> dict[str, dict[str, Any]]:
        """把与日期相交的最新版报告映射到热力图日期。"""

        rows = self.connection.execute(
            """WITH ranked AS (
                   SELECT r.*,
                          ROW_NUMBER() OVER (
                            PARTITION BY r.chat_id, r.period_start, r.period_end
                            ORDER BY r.version DESC, r.generated_at DESC, r.report_id DESC
                          ) AS version_rank
                   FROM reports AS r
                   WHERE r.chat_id=?
                     AND substr(r.period_end, 1, 10) >= ?
                     AND substr(r.period_start, 1, 10) <= ?
               )
               SELECT report_id, report_date, period_start, period_end, version,
                      generated_at, headline, one_line_summary
               FROM ranked
               WHERE version_rank=1
               ORDER BY generated_at DESC, version DESC, report_id DESC""",
            (chat_id, start_date, end_date),
        ).fetchall()
        links: dict[str, dict[str, Any]] = {}
        requested_start = date.fromisoformat(start_date)
        requested_end = date.fromisoformat(end_date)
        for row in rows:
            report_start = max(requested_start, date.fromisoformat(str(row["period_start"])[:10]))
            report_end = min(requested_end, date.fromisoformat(str(row["period_end"])[:10]))
            cursor = report_start
            while cursor <= report_end:
                key = cursor.isoformat()
                links.setdefault(
                    key,
                    {
                        "report_id": str(row["report_id"]),
                        "report_date": str(row["report_date"]),
                        "version": int(row["version"]),
                        "headline": str(row["headline"]),
                        "one_line_summary": str(row["one_line_summary"]),
                    },
                )
                cursor += timedelta(days=1)
        return links

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
            self.connection.execute("DELETE FROM resources WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM report_redactions WHERE report_id=?", (report_id,))
            self.connection.execute("DELETE FROM daily_stats WHERE report_id=?", (report_id,))
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
            self._replace_report_index(
                self.connection,
                report_id,
                str(chat["name"]),
                content,
                stats,
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

    @staticmethod
    def _normalize_module_filter(module_filter: str) -> str:
        normalized = str(module_filter or "all").strip()
        if normalized == "all":
            return normalized
        if normalized not in HISTORY_FILTER_KEYS:
            raise ValueError(f"未知历史模块筛选: {normalized}")
        return normalized

    def _module_keys(self, report_id: str) -> list[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT module_key FROM report_modules WHERE report_id=?",
            (report_id,),
        ).fetchall()
        present = {str(row["module_key"]) for row in rows}
        return [key for key in HISTORY_MODULE_ORDER if key in present]

    def _report_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id": str(row["report_id"]),
            "chat_id": str(row["chat_id"]),
            "display_name": str(row["display_name"]),
            "report_date": str(row["report_date"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "version": int(row["version"]),
            "schema_version": str(row["schema_version"]),
            "generated_at": str(row["generated_at"]),
            "provider": str(row["provider"]),
            "model": str(row["model"]),
            "headline": str(row["headline"]),
            "one_line_summary": str(row["one_line_summary"]),
            "message_count": int(row["message_count"]),
            "participant_count": int(row["participant_count"]),
            "resource_count": int(row["resource_count"]),
            "modules": self._module_keys(str(row["report_id"])),
        }

    def list_history_chats(self, *, keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
        """列出至少拥有一份历史报告的群聊。"""

        clauses: list[str] = []
        parameters: list[Any] = []
        normalized = " ".join(str(keyword or "").split()).casefold()
        if normalized:
            clauses.append("instr(lower(c.display_name), ?) > 0")
            parameters.append(normalized)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(max(1, min(int(limit), 2000)))
        rows = self.connection.execute(
            f"""SELECT c.chat_id, c.display_name, COUNT(r.report_id) AS report_count,
                       MAX(r.report_date) AS latest_report_date,
                       MAX(r.generated_at) AS latest_generated_at
                FROM chats AS c
                JOIN reports AS r ON r.chat_id = c.chat_id
                {where_sql}
                GROUP BY c.chat_id, c.display_name
                ORDER BY latest_generated_at DESC, c.display_name COLLATE NOCASE, c.chat_id
                LIMIT ?""",
            parameters,
        ).fetchall()
        return [
            {
                "chat_id": str(row["chat_id"]),
                "display_name": str(row["display_name"]),
                "report_count": int(row["report_count"]),
                "latest_report_date": str(row["latest_report_date"] or ""),
                "latest_generated_at": str(row["latest_generated_at"] or ""),
            }
            for row in rows
        ]

    def list_reports(
        self,
        *,
        chat_id: str = "",
        start_date: str = "",
        end_date: str = "",
        module_filter: str = "all",
        keyword: str = "",
        version_strategy: str = "latest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """为桌面端返回可分页的历史报告列表；默认每个时间范围只取最新版本。"""

        module_key = self._normalize_module_filter(module_filter)
        if version_strategy not in {"latest", "all"}:
            raise ValueError("version_strategy 仅支持 latest 或 all。")
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        clauses: list[str] = []
        parameters: list[Any] = []
        if version_strategy == "latest":
            clauses.append("version_rank = 1")
        if chat_id:
            clauses.append("ranked.chat_id = ?")
            parameters.append(chat_id)
        if start_date:
            clauses.append("substr(ranked.period_end, 1, 10) >= ?")
            parameters.append(start_date)
        if end_date:
            clauses.append("substr(ranked.period_start, 1, 10) <= ?")
            parameters.append(end_date)
        if module_key != "all":
            clauses.append(
                "EXISTS (SELECT 1 FROM report_modules AS rm "
                "WHERE rm.report_id = ranked.report_id AND rm.module_key = ?)"
            )
            parameters.append(module_key)
        terms = [term.casefold() for term in " ".join(str(keyword or "").split()).split() if term]
        if terms:
            haystack = (
                "lower(coalesce(f.chat_name,'') || ' ' || coalesce(f.title,'') || ' ' || coalesce(f.body,''))"
            )
            term_conditions = [f"instr({haystack}, ?) > 0" for _term in terms]
            module_search = ""
            if module_key != "all":
                module_search = " AND f.module_key = ?"
            else:
                module_search = " AND f.module_key <> 'action_items'"
            clauses.append(
                "EXISTS (SELECT 1 FROM report_search_fts AS f "
                f"WHERE f.report_id = ranked.report_id{module_search} "
                f"AND {' AND '.join(term_conditions)})"
            )
            if module_key != "all":
                parameters.append(module_key)
            parameters.extend(terms)
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        parameters.extend([safe_limit, safe_offset])
        rows = self.connection.execute(
            f"""WITH ranked AS (
                    SELECT r.*, c.display_name,
                           ROW_NUMBER() OVER (
                             PARTITION BY r.chat_id, r.period_start, r.period_end
                             ORDER BY r.version DESC, r.generated_at DESC, r.report_id DESC
                           ) AS version_rank
                    FROM reports AS r
                    JOIN chats AS c ON c.chat_id = r.chat_id
                )
                SELECT ranked.*, COUNT(*) OVER() AS total_count
                FROM ranked
                WHERE {where_sql}
                ORDER BY ranked.report_date DESC, ranked.generated_at DESC,
                         ranked.version DESC, ranked.report_id DESC
                LIMIT ? OFFSET ?""",
            parameters,
        ).fetchall()
        items = [self._report_summary(row) for row in rows]
        total = int(rows[0]["total_count"]) if rows else 0
        return {
            "items": items,
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(items) < total,
        }

    def get_report_detail(self, report_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT r.*, c.display_name
               FROM reports AS r JOIN chats AS c ON c.chat_id = r.chat_id
               WHERE r.report_id=?""",
            (report_id,),
        ).fetchone()
        if row is None:
            raise ValueError("历史报告不存在。")
        try:
            content = json.loads(str(row["content_json"] or "{}"))
            stats = json.loads(str(row["stats_json"] or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"历史报告结构化数据损坏: {exc}") from exc
        names = member_names_from_stats(stats if isinstance(stats, dict) else {})
        if isinstance(content, dict):
            content = normalize_member_references(content, names)
        module_rows = self.connection.execute(
            """SELECT module_key, ordinal, title, content_json
               FROM report_modules WHERE report_id=? AND module_key <> 'action_items'""",
            (report_id,),
        ).fetchall()
        order = {key: index for index, key in enumerate(HISTORY_MODULE_ORDER)}
        live_target_ids = {
            (module_key, ordinal): redaction_target_id
            for module_key, ordinal, _title, _value, redaction_target_id in self._module_rows(content, stats)
            if redaction_target_id
        }
        modules = []
        for module_row in sorted(
            module_rows,
            key=lambda item: (order.get(str(item["module_key"]), 999), int(item["ordinal"])),
        ):
            try:
                value = json.loads(str(module_row["content_json"] or "null"))
            except json.JSONDecodeError:
                value = str(module_row["content_json"] or "")
            value = normalize_member_references(value, names)
            key = str(module_row["module_key"])
            modules.append(
                {
                    "module_key": key,
                    "module_label": HISTORY_MODULE_LABELS.get(key, key),
                    "ordinal": int(module_row["ordinal"]),
                    "title": normalize_member_reference_text(str(module_row["title"]), names),
                    "content": value,
                    "redaction_target_id": live_target_ids.get((key, int(module_row["ordinal"])), ""),
                }
            )
        exports = {}
        for key, column in (("json", "json_path"), ("html", "html_path"), ("png", "png_path")):
            path = str(row[column] or "")
            exports[key] = {"path": path, "exists": bool(path and Path(path).is_file())}
        return {
            **self._report_summary(row),
            "content": content if isinstance(content, dict) else {},
            "stats": stats if isinstance(stats, dict) else {},
            "modules": modules,
            "resources": self.list_resources(report_id=report_id, limit=500)["items"],
            "redactions": [
                dict(item)
                for item in self.connection.execute(
                    "SELECT * FROM report_redactions WHERE report_id=? ORDER BY module_key, target_id",
                    (report_id,),
                ).fetchall()
            ],
            "exports": exports,
        }

    def list_report_versions(self, report_id: str) -> list[dict[str, Any]]:
        anchor = self.connection.execute(
            "SELECT chat_id, period_start, period_end FROM reports WHERE report_id=?",
            (report_id,),
        ).fetchone()
        if anchor is None:
            raise ValueError("历史报告不存在。")
        rows = self.connection.execute(
            """SELECT r.*, c.display_name
               FROM reports AS r JOIN chats AS c ON c.chat_id = r.chat_id
               WHERE r.chat_id=? AND r.period_start=? AND r.period_end=?
               ORDER BY r.version DESC, r.generated_at DESC, r.report_id DESC""",
            (anchor["chat_id"], anchor["period_start"], anchor["period_end"]),
        ).fetchall()
        return [self._report_summary(row) for row in rows]

    def list_resources(
        self,
        *,
        report_id: str = "",
        chat_id: str = "",
        keyword: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if report_id:
            clauses.append("res.report_id = ?")
            parameters.append(report_id)
        if chat_id:
            clauses.append("r.chat_id = ?")
            parameters.append(chat_id)
        terms = [term.casefold() for term in " ".join(str(keyword or "").split()).split() if term]
        if terms:
            haystack = (
                "lower(coalesce(res.topic,'') || ' ' || coalesce(res.title,'') || ' ' || "
                "coalesce(res.url,'') || ' ' || coalesce(res.sender,'') || ' ' || "
                "coalesce(res.context_summary,'') || ' ' || coalesce(res.metadata_json,''))"
            )
            for term in terms:
                clauses.append(f"instr({haystack}, ?) > 0")
                parameters.append(term)
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        parameters.extend([safe_limit, safe_offset])
        rows = self.connection.execute(
            f"""SELECT res.*, r.chat_id, r.report_date, r.version,
                       COUNT(*) OVER() AS total_count
                FROM resources AS res
                JOIN reports AS r ON r.report_id = res.report_id
                WHERE {where_sql}
                ORDER BY r.report_date DESC, res.topic, res.sent_at, res.title
                LIMIT ? OFFSET ?""",
            parameters,
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = {key: row[key] for key in row.keys() if key != "total_count"}
            try:
                item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
            except json.JSONDecodeError:
                item["metadata"] = {}
            items.append(item)
        total = int(rows[0]["total_count"]) if rows else 0
        return {
            "items": items,
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(items) < total,
        }

    def search_history(
        self,
        query: str,
        *,
        chat_id: str = "",
        start_date: str = "",
        end_date: str = "",
        module_filter: str = "all",
        version_strategy: str = "latest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """使用 FTS5，并始终补充中文/混合文本子串检索。"""

        normalized = " ".join(str(query or "").split())
        if not normalized:
            return {"items": [], "total": 0, "limit": max(1, int(limit)), "offset": max(0, int(offset)), "has_more": False}
        module_key = self._normalize_module_filter(module_filter)
        if version_strategy not in {"latest", "all"}:
            raise ValueError("version_strategy 仅支持 latest 或 all。")
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        clauses: list[str] = []
        parameters: list[Any] = []
        if chat_id:
            clauses.append("r.chat_id = ?")
            parameters.append(chat_id)
        if start_date:
            clauses.append("substr(r.period_end, 1, 10) >= ?")
            parameters.append(start_date)
        if end_date:
            clauses.append("substr(r.period_start, 1, 10) <= ?")
            parameters.append(end_date)
        if module_key != "all":
            clauses.append("f.module_key = ?")
            parameters.append(module_key)
        else:
            clauses.append("f.module_key <> 'action_items'")
        if version_strategy == "latest":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM reports AS newer "
                "WHERE newer.chat_id = r.chat_id AND newer.period_start = r.period_start "
                "AND newer.period_end = r.period_end AND newer.version > r.version)"
            )
        base_where = " AND ".join(clauses) if clauses else "1=1"
        select_sql = """SELECT f.report_id, f.module_key, f.chat_name, f.title, f.body,
                               r.chat_id, r.report_date, r.period_start, r.period_end,
                               r.version, r.generated_at, r.one_line_summary
                        FROM report_search_fts AS f
                        JOIN reports AS r ON r.report_id = f.report_id"""
        candidates: list[sqlite3.Row] = []
        phrase = '"' + normalized.replace('"', '""') + '"'
        try:
            candidates.extend(
                self.connection.execute(
                    f"""{select_sql}
                         WHERE report_search_fts MATCH ? AND {base_where}
                         ORDER BY r.report_date DESC, r.generated_at DESC""",
                    [phrase, *parameters],
                ).fetchall()
            )
        except sqlite3.OperationalError:
            pass

        terms = [term.casefold() for term in normalized.split() if term]
        haystack = "lower(coalesce(f.chat_name,'') || ' ' || coalesce(f.title,'') || ' ' || coalesce(f.body,''))"
        substring_conditions = [f"instr({haystack}, ?) > 0" for _term in terms]
        candidates.extend(
            self.connection.execute(
                f"""{select_sql}
                     WHERE {base_where} AND {' AND '.join(substring_conditions)}
                     ORDER BY r.report_date DESC, r.generated_at DESC""",
                [*parameters, *terms],
            ).fetchall()
        )
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in candidates:
            key = (str(row["report_id"]), str(row["module_key"]), str(row["title"]))
            if key in seen:
                continue
            seen.add(key)
            module = key[1]
            results.append(
                {
                    "report_id": key[0],
                    "chat_id": str(row["chat_id"]),
                    "chat_name": str(row["chat_name"]),
                    "report_date": str(row["report_date"]),
                    "period_start": str(row["period_start"]),
                    "period_end": str(row["period_end"]),
                    "version": int(row["version"]),
                    "generated_at": str(row["generated_at"]),
                    "module_key": module,
                    "module_label": HISTORY_MODULE_LABELS.get(module, module),
                    "title": key[2],
                    "snippet": str(row["body"])[:320],
                }
            )
        results.sort(
            key=lambda item: (
                str(item["report_date"]),
                str(item["generated_at"]),
                int(item["version"]),
            ),
            reverse=True,
        )
        page = results[safe_offset : safe_offset + safe_limit]
        return {
            "items": page,
            "total": len(results),
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(page) < len(results),
        }

    def search_reports(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """保留现有 Python 调用方的兼容入口。"""

        return self.search_history(query, version_strategy="all", limit=limit)["items"]

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
            """SELECT r.chat_id, MAX(r.generated_at) AS latest_generated_at
               FROM reports AS r
               GROUP BY r.chat_id
               ORDER BY latest_generated_at DESC, r.chat_id"""
        ).fetchall()
        return [str(row["chat_id"]) for row in rows]
