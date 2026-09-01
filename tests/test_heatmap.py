from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from group_insight.heatmap import (
    build_heatmap_data,
    ensure_chat_daily_stats,
    find_missing_ranges,
    split_ranges,
)
from group_insight.history_store import HistoryStore
from group_insight.models import StructuredMessage
from group_insight.stats import build_chat_daily_stats
from tests.test_history_center import history_document


def message(day: str, sender: str, text: str = "有效讨论") -> StructuredMessage:
    timestamp = int(datetime.fromisoformat(f"{day} 12:00:00").timestamp())
    return StructuredMessage(
        id=f"{day}-{sender}-{text}",
        local_id=timestamp,
        timestamp=timestamp,
        time=f"{day} 12:00:00",
        sender_username=sender,
        sender=sender,
        text=text,
        msg_type="文本",
        chat_id="room@chatroom",
        chat_name="统计群",
        table_name="test",
        metadata={},
    )


class HeatmapStatsTests(unittest.TestCase):
    def test_build_chat_daily_stats_splits_days_and_emits_explicit_zero(self) -> None:
        rows = build_chat_daily_stats(
            [message("2026-08-01", "甲"), message("2026-08-01", "乙"), message("2026-08-03", "甲")],
            start_date="2026-08-01",
            end_date="2026-08-03",
        )
        self.assertEqual([row["date"] for row in rows], ["2026-08-01", "2026-08-02", "2026-08-03"])
        self.assertEqual(rows[0]["message_count"], 2)
        self.assertEqual(rows[0]["participant_count"], 2)
        self.assertEqual(rows[1]["message_count"], 0)
        self.assertEqual(rows[1]["participant_count"], 0)

    def test_missing_ranges_keep_cached_zero_and_merge_contiguous_days(self) -> None:
        ranges = find_missing_ranges(
            "2026-08-01",
            "2026-08-07",
            {"2026-08-01", "2026-08-04", "2026-08-07"},
        )
        self.assertEqual(
            ranges,
            [
                {"start": "2026-08-02", "end": "2026-08-03"},
                {"start": "2026-08-05", "end": "2026-08-06"},
            ],
        )

    def test_contiguous_ranges_are_chunked_without_per_day_requests(self) -> None:
        chunks = split_ranges(
            [{"start": "2026-01-01", "end": "2026-03-05"}],
            max_days=31,
        )
        self.assertEqual(
            chunks,
            [
                {"start": "2026-01-01", "end": "2026-01-31"},
                {"start": "2026-02-01", "end": "2026-03-03"},
                {"start": "2026-03-04", "end": "2026-03-05"},
            ],
        )

    def test_ensure_upserts_missing_days_and_does_not_rescan_cached_range(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as history:
                history.upsert_chat_daily_stats(
                    chat_id="room@chatroom",
                    chat_name="统计群",
                    date="2026-08-01",
                    stats={"message_count": 0},
                )
                fetch = Mock(return_value=(
                    {"username": "room@chatroom", "display_name": "统计群"},
                    [message("2026-08-02", "甲"), message("2026-08-04", "乙")],
                ))
                result = ensure_chat_daily_stats(
                    history,
                    chat_id="room@chatroom",
                    chat_name="统计群",
                    start_date="2026-08-01",
                    end_date="2026-08-04",
                    fetch_range=fetch,
                )
                fetch.assert_called_once_with("2026-08-02", "2026-08-04")
                self.assertEqual(result["unknown_days"], 0)
                self.assertEqual([item["message_count"] for item in result["days"]], [0, 1, 0, 1])
                self.assertEqual(result["scan"]["scanned_days"], 3)

                second_fetch = Mock(side_effect=AssertionError("cached dates must not be rescanned"))
                cached = ensure_chat_daily_stats(
                    history,
                    chat_id="room@chatroom",
                    chat_name="统计群",
                    start_date="2026-08-01",
                    end_date="2026-08-04",
                    fetch_range=second_fetch,
                )
                second_fetch.assert_not_called()
                self.assertTrue(cached["scan"]["cache_hit"])

    def test_unknown_and_known_zero_are_distinct(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as history:
                history.upsert_chat_daily_stats(
                    chat_id="room@chatroom",
                    chat_name="统计群",
                    date="2026-08-01",
                    stats={"message_count": 0},
                )
                result = build_heatmap_data(
                    history,
                    chat_id="room@chatroom",
                    start_date="2026-08-01",
                    end_date="2026-08-02",
                )
                self.assertEqual(result["days"][0]["status"], "known")
                self.assertEqual(result["days"][0]["message_count"], 0)
                self.assertEqual(result["days"][1]["status"], "unknown")
                self.assertIsNone(result["days"][1]["message_count"])

    def test_failed_read_never_turns_unknown_days_into_zero(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as history:
                with self.assertRaisesRegex(RuntimeError, "source unavailable"):
                    ensure_chat_daily_stats(
                        history,
                        chat_id="room@chatroom",
                        chat_name="统计群",
                        start_date="2026-08-01",
                        end_date="2026-08-02",
                        fetch_range=Mock(side_effect=RuntimeError("source unavailable")),
                    )
                result = build_heatmap_data(
                    history,
                    chat_id="room@chatroom",
                    start_date="2026-08-01",
                    end_date="2026-08-02",
                )
                self.assertEqual([day["status"] for day in result["days"]], ["unknown", "unknown"])

    def test_report_date_is_linked_to_latest_history_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with HistoryStore(root / "history.sqlite3") as history:
                first = history_document(root)
                history.upsert_report(first)
                second = history_document(root, version=2)
                second["metadata"]["report_id"] = "history-report-v2"
                history.upsert_report(second)
                result = build_heatmap_data(
                    history,
                    chat_id="history@chatroom",
                    start_date="2026-08-31",
                    end_date="2026-08-31",
                )
                self.assertEqual(result["days"][0]["report"]["report_id"], "history-report-v2")


if __name__ == "__main__":
    unittest.main()
