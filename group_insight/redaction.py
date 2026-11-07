"""报告条目编辑：屏蔽或删除内容，并生成可回退的新版本。"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from .report_schema import make_report_id


REDACTION_NOTICE = "已屏蔽，建议在群内查看"
REDACTION_MASK = "■"
TEXT_REDACTION_FIELDS = {"one_line_summary": "开头一句话总结", "conclusion": "报告结尾"}
REDACTABLE_MODULES = {
    "themes": "今日速览",
    "topics": "今日主要话题",
    "ai_observations": "AI 今日观察",
    "members": "活跃成员",
    "quotes": "引用原话",
    "decisions": "明确结论",
    "open_questions": "开放问题",
    "risk_flags": "风险提示",
}
TOPIC_DETAIL_MODULES = {
    "outcome": "讨论落点",
    "open_questions": "开放问题",
    "risk_flags": "风险提示",
    "quotes": "相关原话",
}


def _member_names(document: dict[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in document.get("stats", {}).get("member_aliases", []) or []:
        if not isinstance(item, dict):
            continue
        sender_id = str(item.get("sender_id") or "").strip()
        sender_name = str(item.get("sender_name") or "").strip()
        if sender_id and sender_name:
            names[sender_id] = sender_name
    return names


def _resolve_members(value: str, names: dict[str, str]) -> str:
    return re.sub(
        r"\[\[user:([^\]]+)\]\]",
        lambda match: names.get(match.group(1), "群成员"),
        value,
    )


def _preview(item: Any, names: dict[str, str]) -> str:
    if isinstance(item, str):
        return _resolve_members(item, names)[:100]
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
            return _resolve_members(value, names)[:100]
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
    names = _member_names(document)
    targets: list[dict[str, Any]] = []
    for key, label in TEXT_REDACTION_FIELDS.items():
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            text, offsets = _display_text_offsets(value, names)
            atomic_ranges: list[dict[str, int]] = []
            for index, (start, end) in enumerate(offsets):
                if value[start:end].startswith("[[user:"):
                    if index and offsets[index - 1] == (start, end):
                        atomic_ranges[-1]["end"] = index + 1
                    else:
                        atomic_ranges.append({"start": index, "end": index + 1})
            targets.append({
                "id": key, "module_key": key, "module_label": label,
                "preview": text[:100], "text": text,
                "atomic_ranges": atomic_ranges,
                "time_label": _period_label(document),
                "redacted": value == REDACTION_NOTICE, "redact_only": True,
            })
    words = document.get("stats", {}).get("word_cloud", []) or []
    if words:
        targets.append({
            "id": "word_cloud", "module_key": "word_cloud", "module_label": "群关键词",
            "preview": "全部群关键词", "time_label": _period_label(document),
            "redacted": all(isinstance(item, dict) and item.get("redacted") for item in words),
            "redact_only": True,
        })
    for index, item in enumerate(words):
        if not isinstance(item, dict) or not (item.get("word") or item.get("redacted")):
            continue
        targets.append({
            "id": f"word_cloud:{index}", "module_key": "word_cloud", "module_label": "群关键词",
            "preview": REDACTION_NOTICE if item.get("redacted") else _resolve_members(str(item["word"]), names),
            "time_label": _period_label(document), "redacted": bool(item.get("redacted")),
            "redact_only": True,
        })
    for module_key, module_label in REDACTABLE_MODULES.items():
        for index, item in enumerate(content.get(module_key, []) or []):
            target_id = str(item.get("redaction_id") or f"{module_key}:{index}") if isinstance(item, dict) else f"{module_key}:{index}"
            targets.append(
                {
                    "id": target_id,
                    "module_key": module_key,
                    "module_label": module_label,
                    "preview": _preview(item, names),
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
                            "preview": _preview(detail_item, names),
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
                "preview": _preview(group, names),
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
                    "preview": _preview(item, names),
                    "time_label": _time_label(item, document),
                    "redacted": bool(item.get("redacted")),
                }
            )
    return targets


def _display_text_offsets(value: str, names: dict[str, str]) -> tuple[str, list[tuple[int, int]]]:
    """显示昵称与标准换行，同时保留每个显示字符对应的原文范围。"""
    text: list[str] = []
    offsets: list[tuple[int, int]] = []
    for match in re.finditer(r"\[\[user:([^\]]+)\]\]|\r\n|\r|[\s\S]", value):
        displayed = names.get(match.group(1), "群成员") if match.group(1) else match.group().replace("\r\n", "\n").replace("\r", "\n")
        text.append(displayed)
        offsets.extend([(match.start(), match.end())] * len(displayed))
    return "".join(text), offsets


def _redact_text_ranges(document: dict[str, Any], edits: Any) -> dict[str, str]:
    if not isinstance(edits, list):
        raise ValueError("局部屏蔽必须是文字范围列表。")
    ranges: dict[str, list[tuple[int, int]]] = {}
    content = document.get("content", {})
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("target_id"), str) or edit["target_id"] not in TEXT_REDACTION_FIELDS:
            raise ValueError("局部屏蔽仅支持开头一句话总结和报告结尾。")
        key = edit["target_id"]
        value = content.get(key)
        if not isinstance(value, str) or value == REDACTION_NOTICE:
            raise ValueError("该总结不存在或已经全部屏蔽。")
        text, offsets = _display_text_offsets(value, _member_names(document))
        start, end = edit.get("start"), edit.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError("局部屏蔽的文字范围无效，请重新选择。")
        if edit.get("text") != text[start:end]:
            raise ValueError("待屏蔽文字与当前报告不一致，请重新选择。")
        ranges.setdefault(key, []).append((offsets[start][0], offsets[end - 1][1]))
    replacements: dict[str, str] = {}
    for key, spans in ranges.items():
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        value = content[key]
        for start, end in reversed(merged):
            displayed, _offsets = _display_text_offsets(value[start:end], _member_names(document))
            value = value[:start] + REDACTION_MASK * len(displayed) + value[end:]
        replacements[key] = value
    return replacements


def _stub(target_id: str, time_label: str, *, original_id: str = "") -> dict[str, Any]:
    return {
        "id": original_id or target_id,
        "redaction_id": target_id,
        "redacted": True,
        "time_label": time_label,
        "notice": REDACTION_NOTICE,
    }


def _sanitize_member_stats(document: dict[str, Any], original: Any) -> None:
    """移除所选成员的统计回退；保留可见正文仍需使用的昵称映射。"""

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

    def referenced_ids(value: Any) -> set[str]:
        if isinstance(value, str):
            return set(re.findall(r"\[\[user:([^\]]+)\]\]", value))
        if isinstance(value, dict):
            if value.get("redacted"):
                return set()
            return set().union(*(referenced_ids(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(referenced_ids(item) for item in value))
        return set()

    visible_ids = referenced_ids(document.get("content", {}))
    if isinstance(stats.get("member_aliases"), list):
        stats["member_aliases"] = [
            item for item in stats["member_aliases"]
            if not matches(item) or (isinstance(item, dict) and str(item.get("sender_id") or "") in visible_ids)
        ]
    for key in ("speaker_directory", "top_speakers"):
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
    text_redactions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """复制报告并将指定条目替换为无正文的屏蔽占位卡。"""

    selected = {str(value) for value in target_ids if str(value).strip()}
    replacements = _redact_text_ranges(document, text_redactions if text_redactions is not None else [])
    if not selected and not replacements:
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
    edited_members: list[Any] = []
    for target_id in sorted(selected | set(replacements), key=lambda value: value.count(":"), reverse=True):
        target = target_map[target_id]
        parts = target_id.split(":")
        if target_id in TEXT_REDACTION_FIELDS:
            original = content[target_id]
            content[target_id] = REDACTION_NOTICE if target_id in selected else replacements[target_id]
            if target_id == "one_line_summary" and content.get("lead_summary") == original:
                content["lead_summary"] = content[target_id]
        elif parts[0] == "word_cloud":
            words = result["stats"]["word_cloud"]
            indices = range(len(words)) if len(parts) == 1 else [int(parts[1])]
            for index in indices:
                words[index] = _stub(f"word_cloud:{index}", target["time_label"])
        elif parts[0] == "resources":
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
                edited_members.append(original)
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

    for member in edited_members:
        _sanitize_member_stats(result, member)

    metadata = result.setdefault("metadata", {})
    metadata.pop("redaction_revision", None)
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


def _deletion_sort_key(target_id: str) -> tuple[Any, ...]:
    """先处理较深层、较大下标的条目，避免删除时数组下标漂移。"""

    parts = target_id.split(":")
    first_index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else -1
    detail_key = parts[2] if len(parts) > 2 and not parts[2].isdigit() else ""
    nested_index = int(parts[-1]) if len(parts) > 2 and parts[-1].isdigit() else -1
    return parts[0], first_index, len(parts), detail_key, nested_index


def _resource_ids(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    if isinstance(value.get("items"), list):
        return {
            str(item.get("id") or "").strip()
            for item in value["items"]
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
    resource_id = str(value.get("id") or "").strip()
    return {resource_id} if resource_id else set()


def delete_report_content(
    document: dict[str, Any],
    target_ids: list[str],
    *,
    version: int,
    exports: dict[str, str],
) -> dict[str, Any]:
    """复制报告并彻底移除所选条目；原报告版本保持不变。"""

    selected = {str(value) for value in target_ids if str(value).strip()}
    if not selected:
        raise ValueError("请至少选择一项需要删除的报告内容。")
    result = copy.deepcopy(document)
    content = result.setdefault("content", {})
    target_map = {item["id"]: item for item in list_redaction_targets(result)}
    unknown = sorted(selected - set(target_map))
    if unknown:
        raise ValueError(f"报告中不存在这些待删除条目: {', '.join(unknown)}")
    if any(target_map[target_id].get("redact_only") for target_id in selected):
        raise ValueError("总结和群关键词请使用屏蔽功能编辑。")

    deleted_resource_ids: set[str] = set()
    deleted_prefixes: list[str] = []
    edited_members: list[Any] = []
    applied = 0
    for target_id in sorted(selected, key=_deletion_sort_key, reverse=True):
        target = target_map[target_id]
        parts = target_id.split(":")
        if parts[0] == "resources":
            group_index = int(parts[1])
            groups = content.get("resources", {}).get("groups", [])
            if len(parts) == 2:
                original = groups.pop(group_index)
                deleted_resource_ids.update(_resource_ids(original))
            else:
                item_index = int(parts[2])
                original = groups[group_index].get("items", []).pop(item_index)
                deleted_resource_ids.update(_resource_ids(original))
        elif parts[0] == "topics" and len(parts) >= 3:
            topic_index = int(parts[1])
            detail_key = parts[2]
            topic = content["topics"][topic_index]
            if len(parts) == 3:
                topic[detail_key] = None
            else:
                topic.get(detail_key, []).pop(int(parts[3]))
        else:
            module_key, index_text = parts[0], parts[1]
            original = content[module_key].pop(int(index_text))
            if module_key == "members":
                edited_members.append(original)
        deleted_prefixes.append(target_id)
        applied += 1

    for member in edited_members:
        _sanitize_member_stats(result, member)

    resources = content.get("resources", {}) if isinstance(content.get("resources"), dict) else {}
    groups = resources.get("groups", []) if isinstance(resources.get("groups"), list) else []
    resources["groups"] = [
        group for group in groups
        if isinstance(group, dict) and isinstance(group.get("items"), list) and group["items"]
    ]
    resources["count"] = sum(
        1
        for group in resources["groups"]
        for item in group.get("items", [])
        if isinstance(item, dict) and not item.get("redacted")
    )
    if deleted_resource_ids:
        for topic in content.get("topics", []) or []:
            if not isinstance(topic, dict) or not isinstance(topic.get("resource_ids"), list):
                continue
            topic["resource_ids"] = [
                resource_id for resource_id in topic["resource_ids"]
                if str(resource_id) not in deleted_resource_ids
            ]

    had_redactions = "redactions" in result
    existing_redactions = [
        item for item in result.get("redactions", []) or []
        if isinstance(item, dict) and not any(
            str(item.get("target_id") or "") == prefix
            or str(item.get("target_id") or "").startswith(prefix + ":")
            for prefix in deleted_prefixes
        )
    ]
    if existing_redactions or had_redactions:
        result["redactions"] = existing_redactions

    metadata = result.setdefault("metadata", {})
    previous_report_id = str(metadata.get("report_id") or "")
    chat = metadata.get("chat", {})
    period = metadata.get("period", {})
    metadata.pop("redaction_revision", None)
    previous_deletion_count = int(metadata.get("deletion_count") or 0)
    metadata.update(
        {
            "report_id": make_report_id(str(chat.get("id") or ""), str(period.get("start") or ""), str(period.get("end") or ""), version),
            "parent_report_id": previous_report_id,
            "version": version,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exports": exports,
            "redaction_count": len(existing_redactions),
            "deletion_count": previous_deletion_count + applied,
        }
    )
    return result
