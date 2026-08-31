"""最终日报结构的修复、去重和本地 fallback 生成。

LLM 输出进入渲染前会在这里被规范化，避免缺字段、重复主题或
dry-run 无模型时无法生成报表。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .common import extract_topic_tokens, make_user_placeholder, normalize_text, topic_similarity
from .models import MessageChunk
from .settings import MAX_REPORT_SECTIONS, SECTION_TOPIC_COVERAGE_THRESHOLD


NON_FORMAL_TONES = {"joke", "sarcasm", "casual", "uncertain", "teasing", "夸张", "反话", "玩笑", "调侃", "闲聊"}


def filter_serious_items(items: Any, *, content_key: str = "content", threshold: float = 0.72) -> list[Any]:
    """过滤被模型明确标为玩笑/低置信度的严肃事项，同时兼容旧版字符串结构。"""
    if not isinstance(items, list):
        return []
    filtered: list[Any] = []
    for item in items:
        if isinstance(item, str):
            text = normalize_text(item, max_len=320)
            if text:
                filtered.append(text)
            continue
        if not isinstance(item, dict):
            continue
        tone = str(item.get("tone") or "").strip().lower()
        if tone in NON_FORMAL_TONES:
            continue
        confidence_value = item.get("confidence")
        try:
            confidence = float(confidence_value) if confidence_value not in (None, "") else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and confidence < threshold:
            continue
        cleaned = dict(item)
        if content_key in cleaned:
            cleaned[content_key] = normalize_text(cleaned.get(content_key, ""), max_len=320)
            if not cleaned[content_key]:
                continue
        filtered.append(cleaned)
    return filtered


def normalize_light_moments(items: Any) -> list[dict[str, Any]]:
    """清洗轻松插曲，避免玩笑丢失后又进入严肃模块。"""
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            content = normalize_text(item, max_len=320)
            if content:
                result.append({"content": content, "tone": "casual"})
        elif isinstance(item, dict):
            content = normalize_text(item.get("content", ""), max_len=320)
            if content:
                result.append({**item, "content": content, "tone": str(item.get("tone") or "casual")})
        if len(result) >= 6:
            break
    return result


def parse_report_time(value: str) -> datetime | None:
    """解析报表 section 中允许的时间字符串。"""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def section_sort_key(section: dict[str, Any]) -> tuple[float, float, str]:
    """生成 section 按时间线排序时使用的键。"""
    start_dt = parse_report_time(section.get("start_time", ""))
    end_dt = parse_report_time(section.get("end_time", ""))
    start_ts = start_dt.timestamp() if start_dt else float("inf")
    end_ts = end_dt.timestamp() if end_dt else float("inf")
    return start_ts, end_ts, section.get("title", "")


def dedupe_theme_cards(cards: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """清洗并去重主题卡片。"""
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for card in cards:
        title = normalize_text(card.get("title", ""), max_len=120)
        summary = normalize_text(card.get("summary", ""), max_len=420)
        if not title and not summary:
            continue
        key = (title.lower(), summary.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"title": title or "主题", "summary": summary})
        if len(deduped) >= limit:
            break
    return deduped


def _normalized_text_list(items: Any, *, limit: int = 6, max_len: int = 320) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = normalize_text(item, max_len=max_len)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _normalized_time_ranges(section: dict[str, Any]) -> list[dict[str, str]]:
    ranges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    source_ranges = section.get("time_ranges", []) if isinstance(section.get("time_ranges"), list) else []
    if not source_ranges and (section.get("start_time") or section.get("end_time")):
        source_ranges = [{"start": section.get("start_time", ""), "end": section.get("end_time", "")}]
    for item in source_ranges:
        if not isinstance(item, dict):
            continue
        start = str(item.get("start") or item.get("start_time") or "").strip()
        end = str(item.get("end") or item.get("end_time") or start).strip()
        if not start and not end:
            continue
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        ranges.append({"start": start, "end": end})
    return sorted(ranges, key=lambda item: (item["start"], item["end"]))


def _normalized_topic_result(value: Any, takeaway: Any = "") -> dict[str, str]:
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip().lower()
        summary = normalize_text(value.get("summary", ""), max_len=320)
    else:
        status = ""
        summary = normalize_text(value, max_len=320)
    if not summary:
        summary = normalize_text(takeaway, max_len=320)
    allowed = {"concluded", "pending", "no_conclusion"}
    if status not in allowed:
        status = "pending" if summary else "no_conclusion"
    if status == "no_conclusion" and not summary:
        summary = "未形成明确结论。"
    return {"status": status, "summary": summary}


def normalize_ai_observations(items: Any, mood: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    source = items if isinstance(items, list) else []
    for item in source:
        if isinstance(item, str):
            content = normalize_text(item, max_len=420)
            if content:
                result.append({"title": "今日观察", "content": content, "kind": "observation"})
        elif isinstance(item, dict):
            content = normalize_text(item.get("content", ""), max_len=420)
            if not content:
                continue
            result.append(
                {
                    "title": normalize_text(item.get("title", ""), max_len=80) or "今日观察",
                    "content": content,
                    "kind": normalize_text(item.get("kind", ""), max_len=40) or "observation",
                }
            )
        if len(result) >= 4:
            break
    if not result and isinstance(mood, dict):
        label = normalize_text(mood.get("label", ""), max_len=60)
        reason = normalize_text(mood.get("reason", ""), max_len=420)
        if label or reason:
            result.append({"title": label or "整体氛围", "content": reason or label, "kind": "mood"})
    return result


def dedupe_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """清洗并按语义话题标识合并 section，不再按连续时间片强制拆分。"""
    indexes: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = normalize_text(section.get("title", ""), max_len=140)
        topic_id = normalize_text(section.get("id", "") or section.get("topic_key", ""), max_len=80)
        discussion_flow = normalize_text(
            section.get("discussion_flow", "") or section.get("summary", ""), max_len=1800
        )
        key_points = _normalized_text_list(
            section.get("key_points", []) or section.get("bullets", []), limit=6
        )
        turning_points = _normalized_text_list(section.get("turning_points", []), limit=4)
        result = _normalized_topic_result(section.get("result"), section.get("takeaway", ""))
        time_ranges = _normalized_time_ranges(section)
        if not title and not discussion_flow:
            continue
        merge_key = (topic_id or title).casefold()
        item = {
            "id": topic_id or f"topic-{len(deduped) + 1}",
            "title": title or "主要话题",
            "start_time": time_ranges[0]["start"] if time_ranges else str(section.get("start_time") or ""),
            "end_time": time_ranges[-1]["end"] if time_ranges else str(section.get("end_time") or ""),
            "time_ranges": time_ranges,
            "discussion_flow": discussion_flow,
            "key_points": key_points,
            "turning_points": turning_points,
            "result": result,
            # 保留旧读取器所需字段；新渲染器优先读取上面的结构化字段。
            "summary": discussion_flow,
            "bullets": key_points,
            "takeaway": result.get("summary", ""),
        }
        if merge_key not in indexes:
            indexes[merge_key] = len(deduped)
            deduped.append(item)
            continue
        existing = deduped[indexes[merge_key]]
        existing["time_ranges"] = _normalized_time_ranges(
            {"time_ranges": [*existing.get("time_ranges", []), *time_ranges]}
        )
        if existing["time_ranges"]:
            existing["start_time"] = existing["time_ranges"][0]["start"]
            existing["end_time"] = existing["time_ranges"][-1]["end"]
        if discussion_flow and discussion_flow not in existing["discussion_flow"]:
            existing["discussion_flow"] = normalize_text(
                f"{existing['discussion_flow']} {discussion_flow}", max_len=1800
            )
            existing["summary"] = existing["discussion_flow"]
        existing["key_points"] = _normalized_text_list(
            [*existing.get("key_points", []), *key_points], limit=6
        )
        existing["bullets"] = existing["key_points"]
        existing["turning_points"] = _normalized_text_list(
            [*existing.get("turning_points", []), *turning_points], limit=4
        )
        rank = {"no_conclusion": 0, "pending": 1, "concluded": 2}
        if rank.get(result["status"], 0) > rank.get(existing["result"]["status"], 0):
            existing["result"] = result
            existing["takeaway"] = result.get("summary", "")
    return deduped



def select_timeline_sections(sections: list[dict[str, Any]], limit: int = MAX_REPORT_SECTIONS) -> list[dict[str, Any]]:
    """在 section 过多时按时间线均匀保留代表片段。"""
    if len(sections) <= limit:
        return sections
    if limit <= 1:
        return sections[:1]
    selected_indexes = {0, len(sections) - 1}
    for slot in range(1, limit - 1):
        index = round(slot * (len(sections) - 1) / (limit - 1))
        selected_indexes.add(index)
    index = 0
    while len(selected_indexes) < limit and index < len(sections):
        selected_indexes.add(index)
        index += 1
    return [sections[i] for i in sorted(selected_indexes)[:limit]]


def build_report_sections_from_bundles(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 reduce bundles 中恢复可兜底使用的主体 section。"""
    sections: list[dict[str, Any]] = []
    for bundle in bundles:
        for section in bundle.get("highlight_sections", []):
            sections.append(
                {
                    "id": section.get("id") or section.get("topic_key", ""),
                    "title": section.get("title", "讨论片段"),
                    "start_time": section.get("start_time", ""),
                    "end_time": section.get("end_time", ""),
                    "time_ranges": section.get("time_ranges", []),
                    "discussion_flow": section.get("discussion_flow") or section.get("summary", ""),
                    "key_points": section.get("key_points", []) or section.get("bullets", [])[:3],
                    "turning_points": section.get("turning_points", []),
                    "result": section.get("result", {}),
                }
            )
    return select_timeline_sections(dedupe_sections(sections), limit=MAX_REPORT_SECTIONS)



def section_topic_tokens(section: dict[str, Any]) -> set[str]:
    """抽取 section 文本中的主题 token，用于覆盖度判断。"""
    parts = [
        normalize_text(section.get("title", ""), max_len=120),
        normalize_text(section.get("summary", ""), max_len=240),
        normalize_text(section.get("takeaway", ""), max_len=160),
    ]
    bullets = section.get("bullets", [])
    for bullet in bullets[:3]:
        parts.append(normalize_text(bullet, max_len=120))

    tokens: set[str] = set()
    for part in parts:
        if part:
            tokens.update(extract_topic_tokens(part))
    return tokens


def bundle_section_is_covered(
    report_sections: list[dict[str, Any]],
    bundle_section: dict[str, Any],
) -> bool:
    """判断 bundle 中的一个 section 是否已被最终报表覆盖。"""
    candidate_tokens = section_topic_tokens(bundle_section)
    candidate_start = parse_report_time(bundle_section.get("start_time", ""))
    candidate_end = parse_report_time(bundle_section.get("end_time", ""))
    if not candidate_start or not candidate_end or candidate_end <= candidate_start:
        candidate_title = normalize_text(bundle_section.get("title", "")).lower()
        for item in report_sections:
            if normalize_text(item.get("title", "")).lower() != candidate_title:
                continue
            if candidate_tokens and topic_similarity(candidate_tokens, section_topic_tokens(item)) < SECTION_TOPIC_COVERAGE_THRESHOLD:
                continue
            return True
        return False

    midpoint = candidate_start.timestamp() + (candidate_end.timestamp() - candidate_start.timestamp()) / 2
    candidate_duration = max(60.0, candidate_end.timestamp() - candidate_start.timestamp())
    for section in report_sections:
        report_start = parse_report_time(section.get("start_time", ""))
        report_end = parse_report_time(section.get("end_time", ""))
        if not report_start or not report_end or report_end <= report_start:
            continue
        if candidate_tokens and topic_similarity(candidate_tokens, section_topic_tokens(section)) < SECTION_TOPIC_COVERAGE_THRESHOLD:
            continue
        report_start_ts = report_start.timestamp()
        report_end_ts = report_end.timestamp()
        if report_start_ts <= midpoint <= report_end_ts:
            return True
        overlap = min(candidate_end.timestamp(), report_end_ts) - max(candidate_start.timestamp(), report_start_ts)
        if overlap > 0 and (overlap / candidate_duration) >= 0.5:
            return True
    return False


def final_sections_need_repair(
    report_sections: list[dict[str, Any]],
    bundle_sections: list[dict[str, Any]],
) -> bool:
    """判断最终报表 section 是否需要用 bundle 内容补齐。"""
    if not bundle_sections:
        return False
    if not report_sections:
        return True
    if len(report_sections) < min(6, len(bundle_sections)):
        return True

    uncovered = [section for section in bundle_sections if not bundle_section_is_covered(report_sections, section)]
    for section in uncovered:
        start_dt = parse_report_time(section.get("start_time", ""))
        end_dt = parse_report_time(section.get("end_time", ""))
        if start_dt and end_dt and (end_dt.timestamp() - start_dt.timestamp()) >= 7200:
            return True
    if len(uncovered) > max(1, len(bundle_sections) // 3):
        return True

    first_bundle = parse_report_time(bundle_sections[0].get("start_time", ""))
    last_bundle = parse_report_time(bundle_sections[-1].get("end_time", ""))
    first_report = parse_report_time(report_sections[0].get("start_time", ""))
    last_report = parse_report_time(report_sections[-1].get("end_time", ""))
    if first_bundle and first_report and (first_report.timestamp() - first_bundle.timestamp()) > 5400:
        return True
    if last_bundle and last_report and (last_bundle.timestamp() - last_report.timestamp()) > 5400:
        return True
    return False


def merge_repaired_sections(
    report_sections: list[dict[str, Any]],
    bundle_sections: list[dict[str, Any]],
    limit: int = MAX_REPORT_SECTIONS,
) -> list[dict[str, Any]]:
    """把缺失的 bundle section 合并回最终报表并重新去重。"""
    merged = dedupe_sections(report_sections)
    for section in bundle_sections:
        if not bundle_section_is_covered(merged, section):
            merged.append(section)
    return select_timeline_sections(dedupe_sections(merged), limit=limit)


def build_theme_cards_from_bundles(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 bundles 中收集主题卡片作为兜底摘要。"""
    cards: list[dict[str, Any]] = []
    for bundle in bundles:
        cards.extend(bundle.get("theme_cards", []))
    return dedupe_theme_cards(cards, limit=4)


def repair_final_report(
    report: dict[str, Any],
    chat_name: str,
    start_time: str,
    end_time: str,
    stats: dict[str, Any],
    bundles: list[dict[str, Any]],
) -> dict[str, Any]:
    """规范化最终报表结构，并修复缺字段或覆盖不足的问题。"""
    repaired = {
        "headline": normalize_text(report.get("headline", ""), max_len=120) or f"{chat_name} 群洞察报表",
        "tagline": normalize_text(report.get("tagline", ""), max_len=180) or f"{start_time} - {end_time}",
        "lead_summary": normalize_text(report.get("lead_summary", ""), max_len=1600),
        "one_line_summary": normalize_text(report.get("one_line_summary", ""), max_len=120),
        "theme_cards": dedupe_theme_cards(report.get("theme_cards", []), limit=5),
        "sections": dedupe_sections(report.get("sections", [])),
        "ai_observations": normalize_ai_observations(report.get("ai_observations", []), report.get("mood", {})),
        "participant_insights": report.get("participant_insights", [])[:6],
        "quotes": report.get("quotes", [])[:4],
        "decisions": filter_serious_items(report.get("decisions", []), content_key="content")[:6],
        "action_items": filter_serious_items(report.get("action_items", []), content_key="task")[:6],
        "open_questions": report.get("open_questions", [])[:6],
        "risk_flags": filter_serious_items(report.get("risk_flags", []), content_key="content")[:6],
        "light_moments": normalize_light_moments(report.get("light_moments", [])),
        "resource_groups": report.get("resource_groups", []) if isinstance(report.get("resource_groups"), list) else [],
        "mood": report.get("mood", {}) if isinstance(report.get("mood"), dict) else {},
        "conclusion": normalize_text(report.get("conclusion", ""), max_len=240),
    }

    bundle_sections = build_report_sections_from_bundles(bundles)
    if not repaired["sections"] and bundle_sections:
        repaired["sections"] = bundle_sections
        bundle_theme_cards = build_theme_cards_from_bundles(bundles)
        if bundle_theme_cards:
            repaired["theme_cards"] = bundle_theme_cards

    if not repaired["lead_summary"]:
        repaired["lead_summary"] = (
            f"本次统计区间内原始消息 {stats.get('message_count', 0)} 条，"
            f"有效对话 {stats.get('effective_message_count', 0)} 条，"
            f"参与成员 {stats.get('participant_count', 0)} 位。"
        )
    if not repaired["one_line_summary"]:
        repaired["one_line_summary"] = normalize_text(repaired["lead_summary"], max_len=90)
    if not repaired["theme_cards"]:
        repaired["theme_cards"] = build_theme_cards_from_bundles(bundles) or [
            {
                "title": "消息概览",
                "summary": (
                    f"原始消息 {stats.get('message_count', 0)} 条，"
                    f"有效对话 {stats.get('effective_message_count', 0)} 条。"
                ),
            }
        ]
    if not repaired["conclusion"]:
        repaired["conclusion"] = "以上为本次群聊日报整理。"
    return repaired


def fallback_map_analysis(chunk: MessageChunk) -> dict[str, Any]:
    """在 dry-run 或 map 失败时生成本地片段分析结果。"""
    speaker_counts = Counter(message.sender for message in chunk.messages)
    top_names = [name for name, _ in speaker_counts.most_common(3)]
    top_line_ids = [message.id for message in chunk.messages[:3]]
    speaker_placeholders = {
        message.sender: make_user_placeholder(message.sender_username) or message.sender
        for message in chunk.messages
        if message.sender
    }
    highlight_title = f"{chunk.start_time} - {chunk.end_time} 讨论片段"
    return {
        "shard_id": chunk.id,
        "time_range": {"start": chunk.start_time, "end": chunk.end_time},
        "summary": f"该时间片共 {chunk.message_count} 条消息，主要发言者为 {'、'.join(top_names) if top_names else '未知成员'}。",
        "theme_cards": [
            {
                "title": "时间片概览",
                "summary": f"本片段覆盖 {chunk.start_time} 至 {chunk.end_time}，共 {chunk.message_count} 条消息。",
                "evidence_ids": top_line_ids,
            }
        ],
        "highlight_sections": [
            {
                "topic_key": f"shard-{chunk.id}",
                "title": highlight_title,
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "summary": f"主要发言者为 {'、'.join(top_names) if top_names else '未知成员'}。",
                "bullets": [
                    f"消息量 {chunk.message_count} 条",
                    f"涉及 {len(speaker_counts)} 位发言者",
                ],
                "evidence_ids": top_line_ids,
            }
        ],
        "participant_notes": [
            {
                "name": speaker_placeholders.get(name, name),
                "observation": f"在该时间片发言 {count} 条。",
                "evidence_ids": top_line_ids[:1],
            }
            for name, count in speaker_counts.most_common(3)
        ],
        "quotes": [
            {
                "speaker": make_user_placeholder(message.sender_username) or message.sender,
                "time": message.time,
                "quote": message.text,
                "message_id": message.id,
                "why_it_matters": "作为该时间片的代表性原话。",
            }
            for message in chunk.messages[:2]
        ],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "light_moments": [],
        "mood": {
            "label": "活跃",
            "reason": "使用本地 dry-run，未调用外部模型，仅基于消息量做概览。",
            "evidence_ids": top_line_ids,
        },
    }


def fallback_reduce_bundle(bundle_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """在 dry-run 或 reduce 失败时本地合并分析结果。"""
    theme_cards = []
    highlight_sections = []
    participant_notes = []
    quotes = []
    action_items = []
    decisions = []
    open_questions = []
    risk_flags = []
    light_moments = []
    source_refs = []

    for item in items:
        ref = item.get("shard_id") or item.get("bundle_id") or "unknown"
        source_refs.append(ref)
        theme_cards.extend(item.get("theme_cards", [])[:1])
        highlight_sections.extend(item.get("highlight_sections", [])[:2])
        participant_notes.extend(item.get("participant_notes", [])[:2])
        quotes.extend(item.get("quotes", [])[:2])
        action_items.extend(item.get("action_items", []))
        decisions.extend(item.get("decisions", []))
        open_questions.extend(item.get("open_questions", []))
        risk_flags.extend(item.get("risk_flags", []))
        light_moments.extend(item.get("light_moments", []))

    summary = items[0].get("summary", "") if items else ""
    return {
        "bundle_id": bundle_id,
        "summary": summary or f"{len(items)} 个片段的合并摘要。",
        "theme_cards": [
            {
                "title": card.get("title", "主题"),
                "summary": card.get("summary", ""),
                "source_refs": source_refs,
            }
            for card in theme_cards[:4]
        ],
        "highlight_sections": [
            {
                "topic_key": section.get("topic_key") or section.get("id", ""),
                "title": section.get("title", "讨论片段"),
                "start_time": section.get("start_time", ""),
                "end_time": section.get("end_time", ""),
                "time_ranges": section.get("time_ranges", []) or [
                    {"start": section.get("start_time", ""), "end": section.get("end_time", "")}
                ],
                "summary": section.get("summary", ""),
                "bullets": section.get("bullets", [])[:3],
                "source_refs": source_refs,
            }
            for section in highlight_sections[:6]
        ],
        "participant_notes": [
            {
                "name": note.get("name", ""),
                "observation": note.get("observation", ""),
                "source_refs": source_refs,
            }
            for note in participant_notes[:6]
        ],
        "quotes": [
            {
                "speaker": quote.get("speaker", ""),
                "time": quote.get("time", ""),
                "quote": quote.get("quote", ""),
                "source_refs": source_refs,
            }
            for quote in quotes[:6]
        ],
        "decisions": [
            {
                "content": decision.get("content", ""),
                "source_refs": source_refs,
            }
            for decision in decisions[:6]
        ],
        "action_items": [
            {
                "owner": action.get("owner", ""),
                "task": action.get("task", ""),
                "deadline": action.get("deadline", ""),
                "status_hint": action.get("status_hint", ""),
                "source_refs": source_refs,
            }
            for action in action_items[:6]
        ],
        "open_questions": [
            {"question": question.get("question", ""), "source_refs": source_refs}
            for question in open_questions[:6]
        ],
        "risk_flags": risk_flags[:6],
        "light_moments": light_moments[:6],
        "mood": {
            "label": "概览",
            "reason": "本地 dry-run 合并结果。",
            "source_refs": source_refs,
        },
    }


def fallback_final_report(
    chat_name: str,
    start_time: str,
    end_time: str,
    stats: dict[str, Any],
    bundles: list[dict[str, Any]],
) -> dict[str, Any]:
    """在 dry-run 或 final 失败时生成可渲染的本地日报。"""
    sections = []
    for bundle in bundles:
        for section in bundle.get("highlight_sections", [])[:8]:
            sections.append(
                {
                    "id": section.get("id") or section.get("topic_key", ""),
                    "title": section.get("title", "讨论片段"),
                    "start_time": section.get("start_time", ""),
                    "end_time": section.get("end_time", ""),
                    "time_ranges": section.get("time_ranges", []),
                    "discussion_flow": section.get("discussion_flow") or section.get("summary", ""),
                    "key_points": section.get("key_points", []) or section.get("bullets", [])[:3],
                    "turning_points": section.get("turning_points", []),
                    "result": {
                        "status": "pending",
                        "summary": "本地 dry-run 输出，建议接入 AI 获取更强语义总结。",
                    },
                }
            )
    sections.sort(key=lambda item: (item["start_time"], item["end_time"]))
    theme_cards = []
    for bundle in bundles:
        for card in bundle.get("theme_cards", []):
            theme_cards.append(
                {
                    "title": card.get("title", "主题"),
                    "summary": card.get("summary", ""),
                }
            )
    theme_cards = theme_cards[:4] or [
        {
            "title": "消息概览",
            "summary": (
                f"原始消息 {stats['message_count']} 条，"
                f"有效对话 {stats['effective_message_count']} 条，"
                f"{stats['participant_count']} 位参与者。"
            ),
        }
    ]
    ranking_labels = {
        "pat_sender": "拍一拍最多",
        "pat_target": "被拍最多",
        "direct_redpacket_receiver": "定向红包收到最多",
        "reply_sender": "回复他人最多",
    }
    interaction_bits = []
    for key, label in ranking_labels.items():
        top_items = stats.get("interaction_rankings", {}).get(key, [])
        if top_items:
            top_item = top_items[0]
            interaction_bits.append(f"{label}：{top_item.get('name', '')} {top_item.get('count', 0)} 次")
    interaction_summary = f"互动榜单：{'；'.join(interaction_bits)}。" if interaction_bits else ""

    return {
        "headline": f"{chat_name} 群洞察报表",
        "tagline": f"{start_time} - {end_time}",
        "lead_summary": (
            f"本次统计区间内原始消息 {stats['message_count']} 条，"
            f"其中有效对话 {stats['effective_message_count']} 条，"
            f"已剔除拍一拍、系统消息、红包、占位链接/文件等 {stats['excluded_message_count']} 条非对话消息；"
            f"有效参与者 {stats['participant_count']} 位。"
            f"{interaction_summary}"
            "当前为本地 dry-run 结果，已完成导出、分片、汇总和报表渲染链路验证。"
        ),
        "one_line_summary": f"{stats['participant_count']} 位群友参与，围绕 {len(theme_cards)} 个主要话题展开讨论。",
        "theme_cards": theme_cards,
        "sections": sections[:MAX_REPORT_SECTIONS],
        "ai_observations": [
            {
                "title": "生成说明",
                "content": "当前为本地 dry-run，仅验证数据、统计与渲染链路，未进行外部语义分析。",
                "kind": "system",
            }
        ],
        "participant_insights": [
            {
                "name": speaker["name"],
                "insight": f"在有效对话口径下发言 {speaker['message_count']} 条。",
            }
            for speaker in stats["top_speakers"][:5]
        ],
        "quotes": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "risk_flags": ["当前为 dry-run，未接入外部语义分析。"],
        "light_moments": [],
        "resource_groups": [],
        "mood": {
            "label": "活跃",
            "reason": "基于消息量与参与人数的本地判断。",
        },
        "conclusion": "以上为本次群聊日报整理。",
    }
