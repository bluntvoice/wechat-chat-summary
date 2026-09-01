"""统一的群聊报告 schema 2.x 与旧报告读取适配。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import normalize_text

SCHEMA_VERSION = "2.2"
COMPATIBLE_SCHEMA_VERSIONS = {"2.0", "2.1", SCHEMA_VERSION}


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


def _canonical_topic(item: dict[str, Any], index: int) -> dict[str, Any]:
    """把新文档的话题固定为 Schema 2.2，避免旧冗余字段继续写入。"""

    outcome = item.get("outcome")
    if not isinstance(outcome, dict):
        legacy_result = item.get("result") if isinstance(item.get("result"), dict) else {}
        outcome = (
            {"content": legacy_result.get("summary", "")}
            if str(legacy_result.get("status") or "") == "concluded" and legacy_result.get("summary")
            else None
        )
    if isinstance(outcome, dict):
        outcome = dict(outcome)
        outcome["content"] = normalize_text(outcome.get("content", "") or outcome.get("summary", ""), max_len=240)
        if outcome["content"] in {
            "", "暂无结论", "暂无结论。", "未形成明确结论", "未形成明确结论。",
            "仍在讨论", "仍在讨论。", "讨论停留在观点交流", "讨论停留在观点交流。",
        }:
            outcome = None
    return {
        "id": str(item.get("id") or item.get("topic_key") or f"topic-{index}"),
        "title": normalize_text(item.get("title", ""), max_len=140) or "主要话题",
        "start_time": str(item.get("start_time") or ""),
        "end_time": str(item.get("end_time") or ""),
        "time_ranges": item.get("time_ranges", []) if isinstance(item.get("time_ranges"), list) else [],
        "discussion_flow": normalize_text(item.get("discussion_flow", "") or item.get("summary", ""), max_len=360),
        "outcome": outcome,
        "action_items": item.get("action_items", []) if isinstance(item.get("action_items"), list) else [],
        "open_questions": item.get("open_questions", []) if isinstance(item.get("open_questions"), list) else [],
        "risk_flags": item.get("risk_flags", []) if isinstance(item.get("risk_flags"), list) else [],
        "quotes": item.get("quotes", []) if isinstance(item.get("quotes"), list) else [],
        "resource_ids": item.get("resource_ids", []) if isinstance(item.get("resource_ids"), list) else [],
    }


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
    topics = [
        _canonical_topic(item, index)
        for index, item in enumerate(report.get("sections", []), 1)
        if isinstance(item, dict)
    ]
    topics_by_id = {str(item["id"]): item for item in topics}

    def target_topic(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        linked = str(item.get("topic_id") or "")
        if linked and linked in topics_by_id:
            return topics_by_id[linked]
        return topics[0] if len(topics) == 1 else None

    # 兼容尚未经过 repair_final_report 的 2.1 形态调用方；新文档只写嵌套结构。
    for key in ("action_items", "open_questions", "risk_flags", "quotes"):
        for item in report.get(key, []) if isinstance(report.get(key), list) else []:
            target = target_topic(item)
            if target is not None:
                target.setdefault(key, []).append(item)
    for item in report.get("decisions", []) if isinstance(report.get("decisions"), list) else []:
        target = target_topic(item)
        if target is not None and not target.get("outcome"):
            target["outcome"] = item
    catalog_ids = {
        str(item.get("id") or "")
        for group in resources.get("groups", [])
        if isinstance(group, dict)
        for item in group.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    assigned_ids: dict[str, list[str]] = {}
    for group in resources.get("groups", []):
        if not isinstance(group, dict):
            continue
        topic_id = str(group.get("topic_id") or "")
        if not topic_id or topic_id == "other":
            continue
        assigned_ids[topic_id] = [
            str(item.get("id"))
            for item in group.get("items", [])
            if isinstance(item, dict) and str(item.get("id") or "") in catalog_ids
        ]
    for topic in topics:
        topic_id = str(topic.get("id") or "")
        # 目录分组已经完成语义复核；以目录结果为准，避免模型原始关联绕过“未归类”保护。
        topic["resource_ids"] = list(dict.fromkeys(assigned_ids.get(topic_id, [])))
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
            "ai_observations": report.get("ai_observations", []),
            "members": report.get("participant_insights", []) or stats.get("top_speakers", []),
            "mood": report.get("mood", {}),
            "conclusion": normalize_text(report.get("conclusion", ""), max_len=240),
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

    if str(payload.get("schema_version") or "") in COMPATIBLE_SCHEMA_VERSIONS:
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
