"""群聊日历热力图的数据查询、缺口判断与按需本地统计。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from .history_store import HistoryStore
from .models import StructuredMessage
from .stats import build_chat_daily_stats


MAX_HEATMAP_DAYS = 366
HEATMAP_SCAN_CHUNK_DAYS = 31

FetchRange = Callable[[str, str], tuple[dict[str, Any], list[StructuredMessage]]]


def validate_heatmap_range(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        start = date.fromisoformat(str(start_date or ""))
        end = date.fromisoformat(str(end_date or ""))
    except ValueError as exc:
        raise ValueError("热力图日期必须使用 YYYY-MM-DD 格式。") from exc
    if end < start:
        raise ValueError("热力图结束日期不能早于开始日期。")
    if (end - start).days + 1 > MAX_HEATMAP_DAYS:
        raise ValueError(f"单次热力图最多统计 {MAX_HEATMAP_DAYS} 天，请缩小日期范围。")
    return start, end


def iter_date_strings(start: date, end: date) -> list[str]:
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def find_missing_ranges(
    start_date: str,
    end_date: str,
    known_dates: set[str] | list[str] | tuple[str, ...],
) -> list[dict[str, str]]:
    """把缺失日期合并为连续区间；已有零值行仍视为已统计。"""

    start, end = validate_heatmap_range(start_date, end_date)
    known = {str(value) for value in known_dates}
    missing = [value for value in iter_date_strings(start, end) if value not in known]
    if not missing:
        return []
    ranges: list[dict[str, str]] = []
    range_start = previous = date.fromisoformat(missing[0])
    for value in missing[1:]:
        current = date.fromisoformat(value)
        if current != previous + timedelta(days=1):
            ranges.append({"start": range_start.isoformat(), "end": previous.isoformat()})
            range_start = current
        previous = current
    ranges.append({"start": range_start.isoformat(), "end": previous.isoformat()})
    return ranges


def split_ranges(
    ranges: list[dict[str, str]],
    *,
    max_days: int = HEATMAP_SCAN_CHUNK_DAYS,
) -> list[dict[str, str]]:
    """把连续缺口限制在可控区间，避免一次加载超大群的全年消息。"""

    if max_days < 1:
        raise ValueError("热力图扫描分段天数必须大于 0。")
    chunks: list[dict[str, str]] = []
    for item in ranges:
        start = date.fromisoformat(item["start"])
        end = date.fromisoformat(item["end"])
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=max_days - 1))
            chunks.append({"start": cursor.isoformat(), "end": chunk_end.isoformat()})
            cursor = chunk_end + timedelta(days=1)
    return chunks


def build_heatmap_data(
    history: HistoryStore,
    *,
    chat_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """返回完整日期轴，并用 status 明确区分 unknown 与真实 zero。"""

    start, end = validate_heatmap_range(start_date, end_date)
    rows = history.get_chat_daily_stats(chat_id, start_date=start_date, end_date=end_date)
    rows_by_date = {str(row["date"]): row for row in rows}
    report_links = history.get_report_links_by_date(
        chat_id,
        start_date=start_date,
        end_date=end_date,
    )
    days: list[dict[str, Any]] = []
    for day in iter_date_strings(start, end):
        row = rows_by_date.get(day)
        report = report_links.get(day)
        if row is None:
            days.append(
                {
                    "date": day,
                    "status": "unknown",
                    "message_count": None,
                    "effective_message_count": None,
                    "participant_count": None,
                    "effective_char_count": None,
                    "link_count": None,
                    "file_count": None,
                    "calculated_at": "",
                    "report": report,
                }
            )
            continue
        days.append(
            {
                "date": day,
                "status": "known",
                "message_count": int(row["message_count"]),
                "effective_message_count": int(row["effective_message_count"]),
                "participant_count": int(row["participant_count"]),
                "effective_char_count": int(row["effective_char_count"]),
                "link_count": int(row["link_count"]),
                "file_count": int(row["file_count"]),
                "calculated_at": str(row["calculated_at"]),
                "report": report,
            }
        )
    missing_ranges = find_missing_ranges(start_date, end_date, set(rows_by_date))
    return {
        "version": 1,
        "chat_id": chat_id,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "missing_ranges": missing_ranges,
        "known_days": len(rows_by_date),
        "unknown_days": len(days) - len(rows_by_date),
    }


def ensure_chat_daily_stats(
    history: HistoryStore,
    *,
    chat_id: str,
    chat_name: str,
    start_date: str,
    end_date: str,
    fetch_range: FetchRange,
    chunk_days: int = HEATMAP_SCAN_CHUNK_DAYS,
) -> dict[str, Any]:
    """只扫描 SQLite 中缺失的日期，并把连续缺口按区间读取、按日落库。"""

    validate_heatmap_range(start_date, end_date)
    cached_rows = history.get_chat_daily_stats(
        chat_id,
        start_date=start_date,
        end_date=end_date,
    )
    known_dates = {str(row["date"]) for row in cached_rows}
    missing_ranges = find_missing_ranges(start_date, end_date, known_dates)
    chunks = split_ranges(missing_ranges, max_days=chunk_days)
    calculated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scanned_days = 0
    for chunk in chunks:
        _context, messages = fetch_range(chunk["start"], chunk["end"])
        rows = build_chat_daily_stats(
            messages,
            start_date=chunk["start"],
            end_date=chunk["end"],
        )
        try:
            history.upsert_chat_daily_stats_many(
                chat_id=chat_id,
                chat_name=chat_name,
                rows=rows,
                calculated_at=calculated_at,
            )
        except Exception as exc:
            raise RuntimeError(f"SQLite 日统计写入失败: {exc}") from exc
        scanned_days += len(rows)
    result = build_heatmap_data(
        history,
        chat_id=chat_id,
        start_date=start_date,
        end_date=end_date,
    )
    result["scan"] = {
        "cache_hit": not chunks,
        "scanned_days": scanned_days,
        "scanned_ranges": chunks,
    }
    return result
