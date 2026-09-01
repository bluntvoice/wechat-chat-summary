"""报告条目屏蔽：生成可审计的新版本，不在新版本中保留被屏蔽正文。"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from .report_schema import make_report_id


REDACTION_NOTICE = "已屏蔽，建议在群内查看"
REDACTABLE_MODULES = {
    "themes": "今日速览",
    "topics": "今日主要话题",
    "ai_observations": "AI 今日观察",
    "members": "活跃成员",
    "quotes": "引用原话",
    "decisions": "明确结论",
    "action_items": "行动事项",
    "open_questions": "开放问题",
    "risk_flags": "风险提示",
}
TOPIC_DETAIL_MODULES = {
    "outcome": "讨论落点",
    "action_items": "行动事项",
    "open_questions": "开放问题",
    "risk_flags": "风险提示",
    "quotes": "相关原话",
}


def _preview(item: Any) -> str:
    if isinstance(item, str):
        return item[:100]
    if not isinstance(item, dict):
        return ""
    if item.get("redacted"):
        return REDACTION_NOTICE
    for key in (
        "title", "name", "content", "task", "question", "discussion_flow",
        "summary", "quote", "text", "insight", "topic",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:100]
    return "未命名条目"


def _period_label(document: dict[str, Any]) -> str:
    period = document.get("metadata", {}).get("period", {})
    report_date = str(period.get("report_date") or "")
    start = str(period.get("start") or "")[:16]
    end = str(period.get("end") or "")[:16]
    if start and end and start[:10] != end[:10]:
        return f"{start} — {end}"
    return report_date or start or end or "当日"


def _time_label(item: Any, document: dict[str, Any]) -> str:
    if isinstance(item, dict):
        explicit = str(item.get("time_label") or "").strip()
        if explicit:
            return explicit
        start = str(item.get("start_time") or item.get("sent_at") or item.get("time") or "").strip()
        end = str(item.get("end_time") or "").strip()
        if start and end and end != start:
            return f"{start} — {end}"
        if start:
            return start
    return _period_label(document)


def _resource_group_time(group: dict[str, Any], document: dict[str, Any]) -> str:
    times = sorted(
        str(item.get("sent_at") or "").strip()
        for item in group.get("items", []) or []
        if isinstance(item, dict) and str(item.get("sent_at") or "").strip()
    )
    if len(times) > 1:
        return f"{times[0]} — {times[-1]}"
    return times[0] if times else _period_label(document)


def list_redaction_targets(document: dict[str, Any]) -> list[dict[str, Any]]:
    """列出桌面端可逐项屏蔽的所有报告条目。"""

    content = document.get("content", {})
    targets: list[dict[str, Any]] = []
    for module_key, module_label in REDACTABLE_MODULES.items():
        for index, item in enumerate(content.get(module_key, []) or []):
            target_id = str(item.get("redaction_id") or f"{module_key}:{index}") if isinstance(item, dict) else f"{module_key}:{index}"
            targets.append(
                {
                    "id": target_id,
                    "module_key": module_key,
                    "module_label": module_label,
                    "preview": _preview(item),
                    "time_label": _time_label(item, document),
                    "redacted": bool(isinstance(item, dict) and item.get("redacted")),
                }
            )
            if module_key != "topics" or not isinstance(item, dict) or item.get("redacted"):
                continue
            for detail_key, detail_label in TOPIC_DETAIL_MODULES.items():
                detail = item.get(detail_key)
                detail_items = detail if isinstance(detail, list) else ([detail] if isinstance(detail, dict) else [])
                for detail_index, detail_item in enumerate(detail_items):
                    if not isinstance(detail_item, dict):
                        continue
                    suffix = f":{detail_key}" if not isinstance(detail, list) else f":{detail_key}:{detail_index}"
                    detail_id = str(detail_item.get("redaction_id") or f"topics:{index}{suffix}")
                    targets.append(
                        {
                            "id": detail_id,
                            "module_key": f"topics.{detail_key}",
                            "module_label": detail_label,
                            "preview": _preview(detail_item),
                            "time_label": _time_label(detail_item, document) if detail_item.get("time") else _time_label(item, document),
                            "redacted": bool(detail_item.get("redacted")),
                        }
                    )

    resources = content.get("resources", {}) if isinstance(content.get("resources"), dict) else {}
    for group_index, group in enumerate(resources.get("groups", []) or []):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("redaction_id") or f"resources:{group_index}")
        targets.append(
            {
                "id": group_id,
                "module_key": "resource_groups",
                "module_label": "资源主题",
                "preview": _preview(group),
                "time_label": _resource_group_time(group, document),
                "redacted": bool(group.get("redacted")),
            }
        )
        if group.get("redacted"):
            continue
        for item_index, item in enumerate(group.get("items", []) or []):
            if not isinstance(item, dict):
                continue
            target_id = str(item.get("redaction_id") or f"resources:{group_index}:{item_index}")
            targets.append(
                {
                    "id": target_id,
                    "module_key": "resources",
                    "module_label": "资源条目",
                    "preview": _preview(item),
                    "time_label": _time_label(item, document),
                    "redacted": bool(item.get("redacted")),
                }
            )
    return targets


def _stub(target_id: str, time_label: str, *, original_id: str = "") -> dict[str, Any]:
    return {
        "id": original_id or target_id,
        "redaction_id": target_id,
        "redacted": True,
        "time_label": time_label,
        "notice": REDACTION_NOTICE,
    }


def _sanitize_member_stats(document: dict[str, Any], original: Any) -> None:
    """屏蔽成员条目时，避免同一成员从统计目录回退显示或留在新 JSON。"""

    if not isinstance(original, dict):
        return
    names = {
        str(original.get(key) or "").strip()
        for key in ("name", "sender", "sender_name")
        if str(original.get(key) or "").strip()
    }
    ids = {
        str(original.get(key) or "").strip()
        for key in ("sender_id", "sender_username", "username")
        if str(original.get(key) or "").strip()
    }
    for value in list(names):
        ids.update(re.findall(r"\[\[user:([^\]]+)\]\]", value))
    stats = document.get("stats", {})
    aliases = stats.get("member_aliases", []) or []
    for item in aliases:
        if not isinstance(item, dict):
            continue
        if str(item.get("sender_id") or "") in ids:
            names.add(str(item.get("sender_name") or ""))
    names.discard("")

    def matches(item: Any) -> bool:
        if isinstance(item, str):
            return item in names or item in ids
        if not isinstance(item, dict):
            return False
        values = {str(value or "") for value in item.values() if not isinstance(value, (dict, list))}
        return bool(values & (names | ids))

    for key in ("member_aliases", "speaker_directory", "top_speakers"):
        if isinstance(stats.get(key), list):
            stats[key] = [item for item in stats[key] if not matches(item)]
    if isinstance(stats.get("known_speakers"), list):
        stats["known_speakers"] = [item for item in stats["known_speakers"] if not matches(item)]
    rankings = stats.get("interaction_rankings")
    if isinstance(rankings, dict):
        for key, values in rankings.items():
            if isinstance(values, list):
                rankings[key] = [item for item in values if not matches(item)]


def redact_report_document(
    document: dict[str, Any],
    target_ids: list[str],
    *,
    version: int,
    exports: dict[str, str],
) -> dict[str, Any]:
    """复制报告并将指定条目替换为无正文的屏蔽占位卡。"""

    selected = {str(value) for value in target_ids if str(value).strip()}
    if not selected:
        raise ValueError("请至少选择一项需要屏蔽的报告内容。")
    result = copy.deepcopy(document)
    content = result.setdefault("content", {})
    existing = {
        str(item.get("target_id") or ""): dict(item)
        for item in result.get("redactions", []) or []
        if isinstance(item, dict) and str(item.get("target_id") or "")
    }
    target_map = {item["id"]: item for item in list_redaction_targets(result)}
    unknown = sorted(selected - set(target_map))
    if unknown:
        raise ValueError(f"报告中不存在这些屏蔽条目: {', '.join(unknown)}")

    applied: list[dict[str, str]] = []
    for target_id in sorted(selected, key=lambda value: value.count(":"), reverse=True):
        target = target_map[target_id]
        parts = target_id.split(":")
        if parts[0] == "resources":
            group_index = int(parts[1])
            groups = content.get("resources", {}).get("groups", [])
            if len(parts) == 2:
                original = groups[group_index]
                groups[group_index] = _stub(target_id, target["time_label"], original_id=str(original.get("topic_id") or ""))
            else:
                item_index = int(parts[2])
                original = groups[group_index].get("items", [])[item_index]
                groups[group_index]["items"][item_index] = _stub(target_id, target["time_label"], original_id=str(original.get("id") or ""))
        elif parts[0] == "topics" and len(parts) >= 3:
            topic_index = int(parts[1])
            detail_key = parts[2]
            topic = content["topics"][topic_index]
            if len(parts) == 3:
                original = topic.get(detail_key, {})
                original_id = str(original.get("id") or "") if isinstance(original, dict) else ""
                topic[detail_key] = _stub(target_id, target["time_label"], original_id=original_id)
            else:
                detail_index = int(parts[3])
                original = topic.get(detail_key, [])[detail_index]
                original_id = str(original.get("id") or "") if isinstance(original, dict) else ""
                topic[detail_key][detail_index] = _stub(target_id, target["time_label"], original_id=original_id)
        else:
            module_key, index_text = parts[0], parts[1]
            original = content[module_key][int(index_text)]
            if module_key == "members":
                _sanitize_member_stats(result, original)
            original_id = str(original.get("id") or "") if isinstance(original, dict) else ""
            content[module_key][int(index_text)] = _stub(target_id, target["time_label"], original_id=original_id)
        applied.append(
            {
                "target_id": target_id,
                "module_key": str(target["module_key"]),
                "time_label": str(target["time_label"]),
                "notice": REDACTION_NOTICE,
            }
        )

    metadata = result.setdefault("metadata", {})
    previous_report_id = str(metadata.get("report_id") or "")
    chat = metadata.get("chat", {})
    period = metadata.get("period", {})
    metadata.update(
        {
            "report_id": make_report_id(str(chat.get("id") or ""), str(period.get("start") or ""), str(period.get("end") or ""), version),
            "parent_report_id": previous_report_id,
            "version": version,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exports": exports,
            "redaction_count": len(applied),
        }
    )
    for item in applied:
        existing[item["target_id"]] = item
    result["redactions"] = list(existing.values())
    metadata["redaction_count"] = len(result["redactions"])
    return result
