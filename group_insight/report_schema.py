"""统一的群聊报告 schema v2 与旧报告读取适配。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import normalize_text

SCHEMA_VERSION = "2.0"


def make_report_id(chat_id: str, start_time: str, end_time: str, version: int) -> str:
    seed = f"{chat_id}|{start_time}|{end_time}|{version}"
    return "report_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _one_line(report: dict[str, Any], chat_name: str) -> str:
    value = normalize_text(
        report.get("one_line_summary", "") or report.get("tagline", "") or report.get("lead_summary", ""),
        max_len=90,
    )
    value = re.sub(r"^(一句话总结|总结|摘要)[:：]\s*", "", value)
    if value:
        return value
    return f"{chat_name} 今日讨论已完成整理。"


def build_report_document(
    *,
    ctx: dict[str, Any],
    start_time: str,
    end_time: str,
    version: int,
    stats: dict[str, Any],
    report: dict[str, Any],
    resources: dict[str, Any],
    exports: dict[str, str],
    provider: str,
    model: str,
    dry_run: bool,
    chunk_count: int,
    chunk_plan: dict[str, Any],
) -> dict[str, Any]:
    """构造 JSON、HTML、PNG 与历史库共同消费的唯一报告文档。"""

    chat_id = str(ctx.get("username") or "")
    chat_name = str(ctx.get("display_name") or chat_id)
    report_date = start_time[:10]
    date_label = report_date if end_time[:10] == report_date else f"{report_date}_至_{end_time[:10]}"
    topics = [dict(item, id=str(item.get("id") or f"topic-{index}")) for index, item in enumerate(report.get("sections", []), 1)]
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "report_id": make_report_id(chat_id, start_time, end_time, version),
            "chat": {"id": chat_id, "name": chat_name},
            "period": {
                "start": start_time,
                "end": end_time,
                "report_date": report_date,
                "date_label": date_label,
            },
            "version": version,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ai": {"provider": provider, "model": model, "dry_run": dry_run},
            "pipeline": {
                "chunk_count": chunk_count,
                "strategy": chunk_plan.get("strategy", ""),
                "mode": chunk_plan.get("mode", ""),
                "estimated_tokens": chunk_plan.get("estimated_tokens", 0),
            },
            "exports": exports,
        },
        "stats": stats,
        "content": {
            "headline": f"{chat_name}：{report_date.replace('-', '')} 总结",
            "one_line_summary": _one_line(report, chat_name),
            "lead_summary": normalize_text(report.get("lead_summary", ""), max_len=1600),
            "themes": report.get("theme_cards", []),
            "topics": topics,
            "members": report.get("participant_insights", []) or stats.get("top_speakers", []),
            "quotes": report.get("quotes", []),
            "decisions": report.get("decisions", []),
            "action_items": report.get("action_items", []),
            "open_questions": report.get("open_questions", []),
            "risk_flags": report.get("risk_flags", []),
            "mood": report.get("mood", {}),
            "resources": resources,
        },
    }


def _legacy_version(path: Path | None) -> int:
    if path is None:
        return 1
    match = re.search(r"_v(\d+)(?:\.[^.]+)?$", path.name)
    return int(match.group(1)) if match else 1


def upgrade_legacy_report(payload: dict[str, Any], source_path: Path | None = None) -> dict[str, Any]:
    """把 v0.1 JSON 适配为内存中的 schema v2，不覆盖原文件。"""

    if str(payload.get("schema_version") or "") == SCHEMA_VERSION:
        return payload
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    stats = payload.get("stats", {}) if isinstance(payload.get("stats"), dict) else {}
    report = payload.get("report", {}) if isinstance(payload.get("report"), dict) else {}
    chat_name = str(metadata.get("chat_name") or "未知群聊")
    chat_id = str(metadata.get("chat_id") or chat_name)
    start_time = str(metadata.get("start_time") or "")
    end_time = str(metadata.get("end_time") or start_time)
    version = int(metadata.get("version") or _legacy_version(source_path))
    exports = {"json": str(source_path) if source_path else "", "html": "", "png": ""}
    if source_path:
        html_path = source_path.with_suffix(".html")
        if html_path.exists():
            exports["html"] = str(html_path)
        data_dir = source_path.parent
        chat_dir = data_dir.parent.parent if data_dir.parent.name == "报告数据" else data_dir.parent
        date_label = start_time[:10] if start_time[:10] == end_time[:10] else f"{start_time[:10]}_至_{end_time[:10]}"
        suffix = "" if version == 1 else f"_v{version}"
        matches = list((chat_dir / "导出图").glob(f"**/{date_label}报告{suffix}.png")) if (chat_dir / "导出图").exists() else []
        if matches:
            exports["png"] = str(matches[0])
    return build_report_document(
        ctx={"username": chat_id, "display_name": chat_name},
        start_time=start_time,
        end_time=end_time,
        version=version,
        stats=stats,
        report=report,
        resources={"count": 0, "groups": []},
        exports=exports,
        provider=str(metadata.get("provider") or ""),
        model=str(metadata.get("model") or ""),
        dry_run=bool(metadata.get("dry_run", False)),
        chunk_count=int(metadata.get("chunk_count") or 0),
        chunk_plan={
            "strategy": metadata.get("chunk_strategy", "legacy"),
            "mode": metadata.get("chunk_mode", "legacy"),
            "estimated_tokens": metadata.get("estimated_tokens", 0),
        },
    )
