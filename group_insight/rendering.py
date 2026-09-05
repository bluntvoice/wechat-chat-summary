"""统一报告文档的移动端 HTML 与日报长图排版。"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .redaction import REDACTION_NOTICE
from .report_model import BLOCKED_OBSERVATION_PHRASES
from .resources import classify_resource_platform


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _discussion_speaker(value: str, names: dict[str, str] | None = None) -> str:
    """识别段首发言人；仅使用成员占位符或可唯一确认的成员名。"""

    text = str(value or "").lstrip()
    token_match = re.match(r"^\[\[user:([^\]]+)\]\]", text)
    if token_match:
        return f"user:{token_match.group(1)}"
    if re.match(r"^(?:大家|群友们?|群内|众人)(?:[：:，,、]|先|随后|接着|最后|一致|共同)", text):
        return "group"

    counts: dict[str, int] = {}
    for raw_name in (names or {}).values():
        name = str(raw_name or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    for name in sorted((item for item, count in counts.items() if count == 1), key=len, reverse=True):
        if not text.startswith(name):
            continue
        remainder = text[len(name):]
        if not remainder or re.match(
            r"^(?:[：:，,、]|说|认为|表示|提到|提出|补充|回应|建议|先|随后|接着|又|则|进一步)",
            remainder,
        ):
            return f"name:{name}"
    return ""


def _limit_discussion_segments(segments: list[str], limit: int) -> list[str]:
    if len(segments) <= limit:
        return segments
    return [*segments[: limit - 1], " ".join(segments[limit - 1 :])]


def _merge_same_speaker_segments(
    segments: list[str], names: dict[str, str] | None = None
) -> list[str]:
    merged: list[str] = []
    speakers: list[str] = []
    for segment in segments:
        speaker = _discussion_speaker(segment, names)
        if speaker and merged and speakers[-1] == speaker:
            merged[-1] = f"{merged[-1]} {segment}".strip()
            continue
        merged.append(segment)
        speakers.append(speaker)
    return merged


def _discussion_segments(
    value: Any,
    limit: int = 5,
    *,
    names: dict[str, str] | None = None,
) -> list[str]:
    """按发言人或讨论阶段整理段落；同一成员的连续表达不拆段。"""

    text = str(value or "").strip()
    if not text:
        return []
    explicit = [
        re.sub(r"^\s*(?:[-*•]|\d+[.、）)])\s*", "", part).strip()
        for part in re.split(r"[\r\n]+", text)
        if part.strip()
    ]
    if len(explicit) > 1:
        return _limit_discussion_segments(
            _merge_same_speaker_segments(explicit, names), limit
        )
    if len(text) <= 120:
        return [text]

    sentences = [part.strip() for part in re.findall(r".*?(?:[。！？!?]+|$)", text) if part.strip()]
    if len(sentences) < 2:
        return [text]
    speaker_blocks: list[str] = []
    speaker_keys: list[str] = []
    current_speaker = ""
    saw_speaker = False
    for sentence in sentences:
        detected = _discussion_speaker(sentence, names)
        if detected:
            current_speaker = detected
            saw_speaker = True
        effective_speaker = current_speaker
        if effective_speaker and speaker_blocks and speaker_keys[-1] == effective_speaker:
            speaker_blocks[-1] += sentence
        else:
            speaker_blocks.append(sentence)
            speaker_keys.append(effective_speaker)
    if saw_speaker:
        return _limit_discussion_segments(speaker_blocks, limit)

    segments: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 105 and len(segments) < limit - 1:
            segments.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        segments.append(current)
    return segments


def _member_names(stats: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in stats.get("member_aliases", []) or []:
        sender_id = str(item.get("sender_id") or "")
        sender_name = str(item.get("sender_name") or "")
        if sender_id and sender_name:
            result[sender_id] = sender_name
    return result


def _resolve(value: Any, names: dict[str, str]) -> str:
    text = str(value or "")
    return re.sub(r"\[\[user:([^\]]+)\]\]", lambda match: names.get(match.group(1), "群成员"), text)


def _plain_member_pattern(names: dict[str, str]) -> re.Pattern[str] | None:
    """为模型直接写出的唯一成员昵称构造一次受控匹配器。"""
    counts: dict[str, int] = {}
    for raw_name in names.values():
        name = str(raw_name or "").strip()
        if name and name not in {"我", "群成员", "未知成员"}:
            counts[name] = counts.get(name, 0) + 1

    aliases = sorted(
        (name for name, count in counts.items() if count == 1),
        key=len,
        reverse=True,
    )
    if not aliases:
        return None

    alternatives: list[str] = []
    for alias in aliases:
        escaped = re.escape(alias)
        if re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
            escaped = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
        alternatives.append(escaped)
    return re.compile("|".join(alternatives))


def _highlight_plain_member_names(
    value: str,
    pattern: re.Pattern[str] | None,
    *,
    member_class: str,
) -> str:
    if pattern is None:
        return _esc(value)

    output: list[str] = []
    cursor = 0
    for match in pattern.finditer(value):
        output.append(_esc(value[cursor : match.start()]))
        output.append(f'<strong class="{member_class}">{_esc(match.group(0))}</strong>')
        cursor = match.end()
    output.append(_esc(value[cursor:]))
    return "".join(output)


def _resolve_html(
    value: Any,
    names: dict[str, str],
    *,
    member_class: str = "",
    plain_member_pattern: re.Pattern[str] | None = None,
) -> str:
    """转义普通文本，并可对成员占位符施加受控 HTML 样式。"""

    text = str(value or "")
    output: list[str] = []
    cursor = 0
    for match in re.finditer(r"\[\[user:([^\]]+)\]\]", text):
        plain = text[cursor : match.start()]
        output.append(
            _highlight_plain_member_names(plain, plain_member_pattern, member_class=member_class)
            if member_class
            else _esc(plain)
        )
        name = _esc(names.get(match.group(1), "群成员"))
        output.append(f'<strong class="{member_class}">{name}</strong>' if member_class else name)
        cursor = match.end()
    tail = text[cursor:]
    output.append(
        _highlight_plain_member_names(tail, plain_member_pattern, member_class=member_class)
        if member_class
        else _esc(tail)
    )
    return "".join(output)


def _text(item: Any, *keys: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if value:
                return str(value)
    return ""


def _is_redacted(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("redacted"))


def _dedupe_resolved_members(
    members: list[Any],
    names: dict[str, str],
    *,
    limit: int = 6,
) -> list[Any]:
    """按最终展示名去重成员观察，避免多个账号标识映射为同一群昵称后重复。"""

    deduped: list[Any] = []
    seen: set[str] = set()
    for item in members:
        if _is_redacted(item):
            deduped.append(item)
        else:
            resolved_name = _resolve(_text(item, "name"), names).strip()
            key = resolved_name.casefold()
            if not resolved_name or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _redacted_html(item: dict[str, Any], tag: str = "article") -> str:
    time_label = _esc(item.get("time_label") or "当日")
    return (
        f'<{tag} class="redacted-card"><span>所属时间 · {time_label}</span>'
        f'<strong>{_esc(item.get("notice") or REDACTION_NOTICE)}</strong></{tag}>'
    )


def _legacy_document(kwargs: dict[str, Any]) -> dict[str, Any]:
    report = kwargs.get("report", {})
    stats = kwargs.get("stats", {})
    chat_name = str(kwargs.get("chat_name") or "群聊")
    start = str(kwargs.get("start_time") or "")
    date = start[:10]
    return {
        "schema_version": "legacy",
        "metadata": {
            "chat": {"id": kwargs.get("chat_id", ""), "name": chat_name},
            "period": {"start": start, "end": kwargs.get("end_time", ""), "report_date": date},
            "generated_at": "",
        },
        "stats": stats,
        "content": {
            "headline": f"{chat_name}：{date.replace('-', '')} 总结",
            "one_line_summary": report.get("one_line_summary") or report.get("tagline") or report.get("lead_summary", ""),
            "lead_summary": report.get("lead_summary", ""),
            "themes": report.get("theme_cards", []),
            "topics": report.get("sections", []),
            "ai_observations": report.get("ai_observations", []),
            "members": report.get("participant_insights", []) or stats.get("top_speakers", []),
            "quotes": report.get("quotes", []),
            "decisions": report.get("decisions", []),
            "action_items": report.get("action_items", []),
            "open_questions": report.get("open_questions", []),
            "risk_flags": report.get("risk_flags", []),
            "mood": report.get("mood", {}),
            "conclusion": report.get("conclusion", ""),
            "resources": {"count": 0, "groups": []},
        },
    }


def render_html_report(document: dict[str, Any] | None = None, **legacy_kwargs: Any) -> str:
    """将 report schema 2.x 渲染为 HTML；PNG 使用完全相同的正文。"""
    if document is None:
        document = _legacy_document(legacy_kwargs)
    metadata = document.get("metadata", {})
    stats = document.get("stats", {})
    content = document.get("content", {})
    chat = metadata.get("chat", {})
    period = metadata.get("period", {})
    names = _member_names(stats)
    plain_member_pattern = _plain_member_pattern(names)

    def resolved(value: Any) -> str:
        return _esc(_resolve(value, names))

    def topic_resolved(value: Any) -> str:
        return _resolve_html(
            value,
            names,
            member_class="topic-member",
            plain_member_pattern=plain_member_pattern,
        )

    themes = content.get("themes", []) or []
    topics = [item for item in content.get("topics", []) or [] if isinstance(item, dict)]
    members = _dedupe_resolved_members(
        content.get("members", []) or stats.get("top_speakers", []) or [], names, limit=6
    )
    top_speakers = [item for item in stats.get("top_speakers", []) or [] if isinstance(item, dict)]
    resources = content.get("resources", {}) if isinstance(content.get("resources"), dict) else {}
    groups = [item for item in resources.get("groups", []) or [] if isinstance(item, dict)]
    observations = [
        item for item in content.get("ai_observations", []) or []
        if not any(
            phrase in (
                str(item)
                if not isinstance(item, dict)
                else " ".join(str(item.get(key) or "") for key in ("title", "content", "summary"))
            )
            for phrase in BLOCKED_OBSERVATION_PHRASES
        )
    ]
    if not observations and isinstance(content.get("mood"), dict):
        mood = content["mood"]
        if mood.get("label") or mood.get("reason"):
            observations.append(
                {"title": mood.get("label") or "整体氛围", "content": mood.get("reason") or mood.get("label")}
            )

    metric_candidates = [
        ("今日消息", stats.get("message_count", 0), "条"),
        ("今日字数", stats.get("effective_char_count", 0), "字"),
        ("参与人数", stats.get("participant_count", 0), "人"),
    ]
    if resources.get("count", 0):
        metric_candidates.append(("整理资源", resources.get("count", 0), "项"))
    metric_html = "".join(
        f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong><small>{_esc(unit)}</small></div>'
        for label, value, unit in metric_candidates
    )

    theme_html = "".join(
        _redacted_html(item)
        if _is_redacted(item)
        else f'<article class="brief-card"><h3>{topic_resolved(_text(item, "title"))}</h3><p>{topic_resolved(_text(item, "summary"))}</p></article>'
        for item in themes[:5]
        if _is_redacted(item) or _text(item, "title", "summary")
    )
    brief_section = (
        f'<section class="card"><h2>今日速览</h2><div class="brief-grid">{theme_html}</div></section>'
        if theme_html else ""
    )

    def topic_key(item: Any) -> str:
        if not isinstance(item, dict):
            return ""
        return str(item.get("topic_id") or item.get("topic_ref") or item.get("section_id") or "").strip()

    def belongs_to(item: Any, topic: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        expected = str(topic.get("id") or "").strip()
        linked = topic_key(item)
        if linked:
            return linked == expected
        return bool(item.get("topic") and str(item.get("topic")).strip() == str(topic.get("title") or "").strip())

    def time_ranges_html(topic: dict[str, Any]) -> str:
        ranges = topic.get("time_ranges", []) if isinstance(topic.get("time_ranges"), list) else []
        if not ranges and (topic.get("start_time") or topic.get("end_time")):
            ranges = [{"start": topic.get("start_time", ""), "end": topic.get("end_time", "")}]
        labels = []
        for item in ranges:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start") or item.get("start_time") or "").strip()
            end = str(item.get("end") or item.get("end_time") or start).strip()
            if not start and not end:
                continue
            label = start if not end or end == start else f"{start} — {end}"
            labels.append(resolved(label))
        return f'<p class="topic-time">{" · ".join(labels)}</p>' if labels else ""

    def render_quote(item: Any, resolve_value=resolved) -> str:
        if _is_redacted(item):
            return _redacted_html(item)
        quote = _text(item, "quote", "content", "text")
        if not quote:
            return ""
        speaker = resolve_value(item.get("speaker", "")) if isinstance(item, dict) else ""
        sent_at = resolved(item.get("time", "")) if isinstance(item, dict) else ""
        reason = resolve_value(item.get("why_it_matters", "")) if isinstance(item, dict) else ""
        meta = " · ".join(value for value in (speaker, sent_at) if value)
        return (
            '<article class="quote-item">'
            + (f'<div class="quote-meta">{meta}</div>' if meta else "")
            + f'<blockquote>{resolve_value(quote)}</blockquote>'
            + (f'<p>{reason}</p>' if reason else "")
            + '</article>'
        )

    def render_simple_items(label: str, items: list[Any], *keys: str, resolve_value=resolved) -> str:
        rows = []
        for item in items:
            if _is_redacted(item):
                rows.append(_redacted_html(item, "li"))
            else:
                value = _text(item, *keys)
                if value:
                    rows.append(f'<li>{resolve_value(value)}</li>')
        return f'<div class="topic-extra"><h4>{_esc(label)}</h4><ul>{"".join(rows)}</ul></div>' if rows else ""

    def render_resource_group(
        group: dict[str, Any],
        resolve_value=resolved,
        mark_member_senders: bool = False,
    ) -> str:
        if _is_redacted(group):
            return _redacted_html(group)
        items = group.get("items", []) or []
        def resource_sender(item: dict[str, Any]) -> str:
            sender_id = str(item.get("sender_id") or "")
            if mark_member_senders and sender_id:
                return resolve_value(f"[[user:{sender_id}]]")
            return resolve_value(item.get("sender", ""))

        def resource_platform(item: dict[str, Any]) -> dict[str, str]:
            return classify_resource_platform(
                str(item.get("url") or ""), str(item.get("type") or "link")
            )

        items_html = "".join(
            _redacted_html(item, "div")
            if _is_redacted(item)
            else '<div class="resource-item">'
            f'<span class="resource-kind platform-{_esc(resource_platform(item)["platform"])}">{_esc(resource_platform(item)["platform_label"])}</span>'
            f'<div><strong>{resolve_value(item.get("title") or item.get("file_name") or item.get("url"))}</strong>'
            f'<p>{resolve_value(item.get("context_summary", ""))}</p>'
            f'<small>{resource_sender(item)} · {resolved(item.get("sent_at", ""))}</small>'
            + (f'<a href="{_esc(item.get("url"))}" rel="noreferrer">查看链接</a>' if str(item.get("url", "")).startswith(("http://", "https://")) else "")
            + '</div></div>'
            for item in items
            if isinstance(item, dict)
        )
        return (
            '<article class="resource-group">'
            f'<header><h4>{resolve_value(group.get("topic", "相关资源"))}</h4><span>{len(items)} 项</span></header>'
            + (f'<p class="group-note">{resolve_value(group.get("summary", ""))}</p>' if group.get("summary") else "")
            + items_html + '</article>'
        )

    legacy_serious_specs = (
        ("明确结论", content.get("decisions", []) or [], ("content",)),
        ("开放问题", content.get("open_questions", []) or [], ("question", "content")),
        ("风险提示", content.get("risk_flags", []) or [], ("content",)),
    )
    quotes = content.get("quotes", []) or []
    used_item_ids: set[int] = set()

    def render_topic(topic: dict[str, Any], index: int) -> str:
        if _is_redacted(topic):
            return (
                f'<article class="main-topic"><div class="section-index">{index}</div>'
                f'<div class="section-body">{_redacted_html(topic)}</div></article>'
            )
        flow = topic.get("discussion_flow") or topic.get("summary") or ""
        flow_segments = _discussion_segments(flow, names=names)
        outcome = topic.get("outcome") if isinstance(topic.get("outcome"), dict) else {}
        legacy_result = topic.get("result") if isinstance(topic.get("result"), dict) else {}
        outcome_text = outcome.get("content") or legacy_result.get("summary") or topic.get("takeaway") or ""
        legacy_status = str(legacy_result.get("status") or "")
        if legacy_status in {"pending", "no_conclusion"}:
            outcome_text = ""
        extras = [
            render_simple_items("开放问题", topic.get("open_questions", []) or [], "question", "content", resolve_value=topic_resolved),
            render_simple_items("风险提示", topic.get("risk_flags", []) or [], "content", resolve_value=topic_resolved),
        ]
        for label, items, keys in legacy_serious_specs:
            related = [item for item in items if belongs_to(item, topic)]
            used_item_ids.update(id(item) for item in related)
            extras.append(render_simple_items(label, related, *keys, resolve_value=topic_resolved))
        related_quotes = [*(topic.get("quotes", []) or []), *[item for item in quotes if belongs_to(item, topic)]]
        used_item_ids.update(id(item) for item in related_quotes)
        quote_html = "".join(render_quote(item, topic_resolved) for item in related_quotes[:2])
        linked_resource_ids = {str(value) for value in topic.get("resource_ids", []) or []}
        related_groups = [
            group for group in groups
            if belongs_to(group, topic)
            or any(str(item.get("id") or "") in linked_resource_ids for item in group.get("items", []) if isinstance(item, dict))
        ]
        used_item_ids.update(id(item) for item in related_groups)
        resource_html = "".join(render_resource_group(group, topic_resolved, True) for group in related_groups)
        return (
            f'<article class="main-topic"><div class="section-index">{index}</div><div class="section-body">'
            + f'<h3>{topic_resolved(topic.get("title", "主要话题"))}</h3>'
            + time_ranges_html(topic)
            + (
                f'<ul class="discussion-flow discussion-points">{"".join(f"<li>{topic_resolved(segment)}</li>" for segment in flow_segments)}</ul>'
                if len(flow_segments) > 1
                else (f'<p class="discussion-flow">{topic_resolved(flow_segments[0])}</p>' if flow_segments else "")
            )
            + (_redacted_html(outcome) if _is_redacted(outcome) else (f'<div class="topic-result concluded"><span>讨论落点</span><p>{topic_resolved(outcome_text)}</p></div>' if outcome_text else ""))
            + "".join(extras)
            + (f'<div class="topic-extra"><h4>相关原话</h4>{quote_html}</div>' if quote_html else "")
            + (f'<div class="topic-extra resources-in-topic"><h4>相关资源</h4>{resource_html}</div>' if resource_html else "")
            + '</div></article>'
        )

    topics_html = "".join(render_topic(topic, index) for index, topic in enumerate(topics, 1))
    unassigned_groups = [group for group in groups if id(group) not in used_item_ids]
    if unassigned_groups:
        topics_html += (
            f'<article class="main-topic other-topic"><div class="section-index">{len(topics) + 1}</div><div class="section-body"><h3>其他 / 未归类资源</h3>'
            '<p class="discussion-flow">以下链接或文件暂时无法可靠关联到某个主要话题。</p>'
            + "".join(render_resource_group(group) for group in unassigned_groups)
            + '</div></article>'
        )
    main_topics_section = (
        f'<section class="card"><h2>今日主要话题</h2>{topics_html}</section>' if topics_html else ""
    )

    observation_html = "".join(
        _redacted_html(item)
        if _is_redacted(item)
        else f'<article class="observation"><h3>{resolved(_text(item, "title") or "今日观察")}</h3><p>{resolved(_text(item, "content", "summary"))}</p></article>'
        for item in observations
        if _is_redacted(item) or _text(item, "content", "summary")
    )
    supplemental = []
    for label, items, keys in legacy_serious_specs:
        unassigned = [item for item in items if id(item) not in used_item_ids]
        supplemental.append(render_simple_items(label, unassigned, *keys))
    unassigned_quotes = [item for item in quotes if id(item) not in used_item_ids]
    if unassigned_quotes:
        supplemental.append(
            '<div class="topic-extra"><h4>引用原话</h4>'
            + "".join(render_quote(item) for item in unassigned_quotes)
            + '</div>'
        )
    supplemental_html = "".join(supplemental)
    if supplemental_html:
        observation_html += f'<article class="observation supplement"><h3>补充关注</h3>{supplemental_html}</article>'
    observation_section = (
        f'<section class="card"><h2>AI 今日观察</h2>{observation_html}</section>' if observation_html else ""
    )

    member_html = "".join(
        _redacted_html(item, "li")
        if _is_redacted(item)
        else f'<li><span class="rank">{index:02d}</span><div><strong>{resolved(_text(item, "name"))}</strong><p>{resolved(_text(item, "insight") or (str(item.get("message_count", 0)) + " 条消息" if isinstance(item, dict) else ""))}</p></div></li>'
        for index, item in enumerate(members, 1)
    )
    max_speaker_messages = max([int(item.get("message_count", 0)) for item in top_speakers] or [1])
    speaker_html = "".join(
        '<li class="speaker-row">'
        f'<span class="rank">{index:02d}</span><strong>{resolved(item.get("name", "群成员"))}</strong>'
        f'<i><b style="width:{max(3, round(100 * int(item.get("message_count", 0)) / max_speaker_messages))}%"></b></i>'
        f'<span class="speaker-count">{_esc(item.get("message_count", 0))} 条</span></li>'
        for index, item in enumerate(top_speakers[:10], 1)
    )
    word_cloud = stats.get("word_cloud", []) or []
    words_html = "".join(
        f'<span class="word" style="--w:{min(5, 1 + int(item.get("count", 1)) // 4)}">{resolved(item.get("word", ""))}</span>'
        for item in word_cloud[:24] if isinstance(item, dict) and item.get("word")
    )
    time_segments = stats.get("time_segment_breakdown", []) or []
    max_time = max([int(item.get("count", 0)) for item in time_segments if isinstance(item, dict)] or [1])
    time_html = "".join(
        f'<div class="time-row"><span>{resolved(item.get("label", ""))}</span><i><b style="width:{max(3, round(100 * int(item.get("count", 0)) / max_time))}%"></b></i><strong>{_esc(item.get("count", 0))}</strong></div>'
        for item in time_segments if isinstance(item, dict)
    )
    activity_blocks = ""
    if member_html:
        activity_blocks += f'<div class="activity-block"><h3>活跃成员</h3><ol class="member-list">{member_html}</ol></div>'
    if speaker_html:
        activity_blocks += f'<div class="activity-block"><h3>发言排行</h3><ol class="speaker-list">{speaker_html}</ol></div>'
    if words_html:
        activity_blocks += f'<div class="activity-block"><h3>群关键词</h3><div class="words">{words_html}</div></div>'
    if time_html:
        activity_blocks += f'<div class="activity-block"><h3>活跃时段</h3>{time_html}</div>'
    activity_section = f'<section class="card"><h2>今日活跃情况</h2>{activity_blocks}</section>' if activity_blocks else ""

    conclusion = content.get("conclusion") or "以上为本次群聊日报整理。"
    generated_at = metadata.get("generated_at") or ""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{resolved(content.get('headline', '群聊总结'))}</title>
<style>
:root{{--ink:#23452d;--muted:#6b7f71;--green:#7bc96f;--green-dark:#4d9f5f;--paper:#f8fff4;--yellow:#fff7cf;--pink:#fff0f1;--blue:#edf7fb;--line:rgba(35,69,45,.10);--shadow:0 10px 28px rgba(92,135,83,.10);}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(180deg,#fffef7,var(--paper));color:var(--ink);font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65}}
.page{{width:min(100%,520px);margin:0 auto;padding:8px 8px 24px}} .hero{{padding:16px 14px;border-radius:8px;background:linear-gradient(160deg,var(--green),#9bd58a 45%,#ffd86b);box-shadow:var(--shadow)}}
.eyebrow{{display:inline-flex;padding:3px 10px;border-radius:99px;background:#efffe9aa;font-size:12px;font-weight:800;letter-spacing:.12em}} h1{{font-size:25px;line-height:1.3;margin:13px 0 9px;letter-spacing:-.02em}} .one-line{{font-size:14px;margin:0;color:#314b37}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}} .metric{{background:rgba(255,255,255,.55);border:1px solid rgba(255,255,255,.65);border-radius:8px;padding:10px;min-width:0}} .metric span{{display:block;font-size:10px;color:var(--muted)}} .metric strong{{font-size:20px;margin-right:2px}} .metric small{{font-size:10px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:8px;margin-top:10px;padding:14px 12px;box-shadow:var(--shadow)}} .card>h2{{font-size:17px;margin:0 0 10px;font-weight:900}} h3{{font-size:16px;margin:0 0 5px}} h4{{font-size:13px;margin:0 0 5px}} p{{margin:0;font-size:14px;color:#526159}}
.brief-grid{{display:grid;gap:8px}} .brief-card{{padding:12px;border-radius:8px;background:linear-gradient(180deg,#fffdf5,#fff7fb);border:1px solid rgba(225,106,151,.15)}} .brief-card h3{{font-size:16px;color:#e16a97}} .brief-card p{{font-size:14px}} .topic-member{{color:#3478bd;font-weight:800}}
.main-topic{{display:grid;grid-template-columns:32px 1fr;gap:8px;padding:10px 0;border-bottom:1px solid var(--line)}} .main-topic:last-child{{border-bottom:0;padding-bottom:0}} .section-index{{width:28px;height:28px;border-radius:50%;background:var(--green);color:#fff;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:900;margin-top:1px}} .section-body{{min-width:0}} .topic-time{{margin:-1px 0 6px;color:var(--muted);font-size:11px;line-height:1.55}} .discussion-flow{{line-height:1.72;font-size:14px}} .discussion-points{{margin:7px 0 0;padding-left:19px;color:#526159}} .discussion-points li+li{{margin-top:6px}} .topic-extra{{margin-top:8px;padding:8px 9px;border-radius:8px;background:#f8fbf6}} .topic-extra ul{{margin:0;padding-left:18px;font-size:12px;color:#526159;line-height:1.65}} .topic-result{{display:flex;gap:7px;align-items:flex-start;margin-top:8px;padding:7px 9px;border-left:3px solid #78b889;border-radius:6px;background:#f2f9f2}} .topic-result span{{flex:0 0 auto;padding:1px 6px;border-radius:99px;background:#dff0df;font-size:10px;color:#477557}} .topic-result p{{font-size:12px}}
.observation{{padding:12px 13px;border-radius:11px;background:#f5faf2;margin-top:8px}} .observation:first-of-type{{margin-top:0}} .observation:nth-child(2n){{background:#fff9e8}} .supplement{{background:#f7f5fb}}
.member-list{{list-style:none;padding:0;margin:0;display:grid;gap:6px}} .member-list li{{display:flex;align-items:center;gap:10px;padding:9px 10px;background:#f7fbf5;border-radius:10px}} .rank{{display:inline-flex;align-items:center;justify-content:center;flex:0 0 28px;width:28px;height:28px;border-radius:50%;background:#dff0df;color:#3f8757;font:700 12px ui-monospace}} .member-list strong{{font-size:13px}} .member-list p{{font-size:12px}}
.activity-block{{padding:12px 0;border-top:1px dashed #dfe8da}} .activity-block:first-of-type{{border-top:0;padding-top:0}} .speaker-list{{list-style:none;padding:0;margin:0;display:grid;gap:6px}} .speaker-row{{display:grid;grid-template-columns:28px minmax(90px,.8fr) 1fr 48px;align-items:center;gap:9px;padding:8px 10px;background:#f7fbf5;border-radius:10px}} .speaker-row strong{{font-size:12px;overflow-wrap:anywhere}} .speaker-row i{{height:8px;border-radius:8px;background:#e7efe2;overflow:hidden}} .speaker-row i b{{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,#8bd092,#5eae79)}} .speaker-count{{font-size:11px;color:var(--muted);text-align:right;white-space:nowrap}}
.words{{display:flex;gap:8px 11px;align-items:baseline;flex-wrap:wrap;padding:6px 2px}} .word{{color:#4b8e60;font-weight:700;font-size:calc(11px + var(--w) * 1.5px)}} .time-row{{display:grid;grid-template-columns:58px 1fr 28px;align-items:center;gap:8px;font-size:11px;margin:7px 0}} .time-row i{{height:8px;border-radius:8px;background:#edf2e9;overflow:hidden}} .time-row b{{display:block;height:100%;background:linear-gradient(90deg,#8bd092,#5eae79);border-radius:8px}} .time-row strong{{text-align:right}}
.resource-group{{border:1px solid rgba(225,106,151,.15);border-radius:8px;padding:11px;margin-top:8px;background:linear-gradient(180deg,#fffdf5,#fff7fb)}} .resource-group header{{display:flex;justify-content:space-between;gap:10px}} .resource-group header span{{font-size:11px;color:var(--muted)}} .group-note{{font-size:12px;margin-bottom:7px}} .resource-item{{display:grid;grid-template-columns:62px 1fr;gap:8px;border-top:1px dashed #e8e6d7;padding:9px 0}} .resource-kind{{font-size:10px;color:#48775a;background:#dff0df;border-radius:6px;height:max-content;text-align:center;padding:2px 4px;font-weight:800}} .platform-xiaohongshu{{background:#ffe8e8;color:#a9343c}} .platform-taobao{{background:#fff0dd;color:#a65314}} .platform-wechat{{background:#e2f4e5;color:#267044}} .platform-zhihu{{background:#e6f1ff;color:#2767a3}} .platform-jd{{background:#ffe8e8;color:#ad2d2d}} .platform-douyin{{background:#ecebed;color:#443d49}} .platform-bilibili{{background:#e5f5fb;color:#28738f}} .platform-weibo{{background:#fff0de;color:#9b541d}} .platform-web{{background:#edf1ef;color:#56645c}} .platform-file{{background:#e7f1e8;color:#3f704c}} .resource-item strong{{font-size:13px;display:block}} .resource-item p{{font-size:12px;line-height:1.55}} .resource-item small,.resource-item a{{display:block;font-size:11px;color:var(--muted)}} .resource-item a{{color:#3b79bb}}
.quote-item{{padding:8px 0}} blockquote{{margin:5px 0 0;padding:12px;border-radius:8px;background:linear-gradient(180deg,#fffdf5,#fdf2f8);border:1px solid rgba(225,106,151,.15);font-size:13px;color:#526159}} .quote-item p{{font-size:11px;margin:6px 9px 0}} .quote-meta{{font-size:10px;color:var(--green-dark);font-weight:700}}
.redacted-card{{display:flex!important;flex-direction:column;align-items:flex-start;gap:4px;padding:12px 13px!important;margin:6px 0;border:1px dashed #d5b96a!important;border-radius:10px;background:#fff9e5!important;list-style:none}} .redacted-card span{{font-size:10px;color:#91783a}} .redacted-card strong{{font-size:12px;color:#6b5a32}}
.report-end{{text-align:center}} .report-end p{{font-size:13px;color:#43584a}} .footer{{display:grid;gap:2px;text-align:center;padding:14px 6px 0;font-size:11px;line-height:1.6;color:#8b978f}} .empty{{font-size:12px;color:#87928b}}
@media(max-width:520px){{.metrics{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main class="page">
<header class="hero"><span class="eyebrow">群聊拾遗</span><h1>{resolved(content.get('headline'))}</h1><p class="one-line">{resolved(content.get('one_line_summary'))}</p><div class="metrics">{metric_html}</div></header>
{brief_section}
{main_topics_section}
{observation_section}
{activity_section}
<section class="card report-end"><h2>报告结尾</h2><p>{resolved(conclusion)}</p></section>
<footer class="footer"><span>报告由群聊拾遗生成 · {_esc(chat.get('name'))} · {_esc(period.get('report_date'))}</span>{(f'<span>生成时间：{_esc(generated_at)}</span>' if generated_at else '')}</footer>
</main></body></html>"""


def invalidate_cached_outputs_if_needed(output_dir: Path, signature: dict[str, Any]) -> None:
    """当运行签名变化时清理当前报告数据目录中的过期阶段缓存。"""
    signature_path = output_dir / "snapshot" / "run_signature.json"
    try:
        previous_signature = json.loads(signature_path.read_text(encoding="utf-8")) if signature_path.exists() else None
    except Exception:
        previous_signature = {}
    if previous_signature == signature:
        return
    for dirname in ("map", "reduce", "final"):
        target_dir = output_dir / dirname
        if target_dir.exists():
            shutil.rmtree(target_dir)
    for pattern in ("group_insight_report.json", "group_insight_report.html", "group_insight_report.png", "*_群聊总结.json", "*_群聊总结.html", "*_群聊总结.png"):
        for target_file in output_dir.glob(pattern):
            if target_file.is_file():
                target_file.unlink()
