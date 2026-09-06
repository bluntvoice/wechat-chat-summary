"""正常报告的本地确定性派生；不依赖任何 AI 客户端。"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from .member_references import USER_REFERENCE_PATTERN, member_names_from_stats
from .report_schema import SCHEMA_VERSION

PRIVACY_NOTICE = "匿名版会隐藏成员昵称和成员级统计，但不会自动删除聊天正文中自行出现的其他个人信息或敏感内容，分享前仍需自行确认。"


def first_seen_members(messages: list) -> list[str]:
    """按真实消息时间排序；同秒保留数据源消息顺序，系统事件不算发言。"""
    return list(dict.fromkeys(
        message.sender_username
        for message in sorted(messages, key=lambda item: item.timestamp)
        if message.sender_username and message.msg_type != "系统"
        and not message.sender_username.endswith("@chatroom")
    ))


GROUP_STATS = {
    "message_count", "effective_message_count", "participant_count", "effective_char_count",
    "type_breakdown", "category_breakdown", "effective_breakdown", "excluded_breakdown",
    "busiest_hours", "time_segment_breakdown", "resource_breakdown", "hourly_distribution",
    "unknown_message_count", "system_message_count",
    "analysis_message_count", "substantive_message_count", "excluded_message_count", "raw_char_count",
}
IDENTITY_KEYS = {
    "member_id", "sender_id", "sender_username", "username", "wxid", "alias", "nickname",
    "sender_name", "sender_nickname", "uploader", "uploader_name", "member_aliases",
    "speaker_directory", "participants", "participant_ids", "representative_members",
    "evidence_ids", "message_ids", "message_id", "metadata", "source",
}
SIGNATURE_KEYS = {"speaker", "sender", "author", "owner", "name"}
CONTENT_KEYS = {
    "headline", "one_line_summary", "lead_summary", "themes", "topics", "ai_observations",
    "members", "mood", "conclusion", "resources", "id", "title", "summary", "content",
    "discussion_flow", "start_time", "end_time", "time_ranges", "start", "end", "outcome",
    "action_items", "open_questions", "risk_flags", "quotes", "quote", "question", "answer",
    "resource_ids", "groups", "items", "count", "type", "topic", "topic_id", "url",
    "file_name", "file_ext", "file_size", "sent_at", "context_summary", "label", "reason",
    "tone", "confidence", "redacted", "notice", "time_label", "redaction_id", "result",
    "hour", "word", "link", "file", "video", "image", "voice",
} | SIGNATURE_KEYS | GROUP_STATS


def anonymize_report(document: dict[str, Any], order: list[str]) -> dict[str, Any]:
    metadata = document["metadata"]
    if metadata.get("report_variant", "normal") != "normal":
        raise ValueError("请从正常报告生成匿名版。")
    if not order or len(set(order)) != len(order) or any(not isinstance(x, str) or not x for x in order):
        raise ValueError("缺少可靠的成员首次发言顺序，无法生成匿名版。")
    names = member_names_from_stats(document.get("stats", {}))
    anonymous = {sender: f"群友{index:02d}" for index, sender in enumerate(order, 1)}

    def token(match: re.Match) -> str:
        sender = match.group(1)
        if sender not in anonymous:
            raise ValueError("报告引用了无法确认首次发言顺序的成员，已停止匿名导出。")
        return anonymous[sender]

    def clean(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            if key in SIGNATURE_KEYS and not USER_REFERENCE_PATTERN.search(value):
                return anonymous.get(value, "")  # 只接受稳定 ID，不按昵称猜测署名。
            result = USER_REFERENCE_PATTERN.sub(token, value)
            # 明确账号残留不能作为普通正文放行。
            if any(sender in result for sender in set(order) | set(names)):
                raise ValueError("正文仍含成员账号，无法安全匿名，已停止导出。")
            # 只检查成员引用语境，普通词（如苹果手机）不替换也不删除。
            for name in set(names.values()):
                if name and (len(name) > 3 and name in result or re.search(r"(?:@" + re.escape(name) + r"|" + re.escape(name) + r"\s*(?:认为|表示|提到|说|：|:|$))", result)):
                    raise ValueError("旧报告含无法可靠关联身份的纯文本成员引用，请先重新生成正常报告或屏蔽对应条目。")
            return result
        if isinstance(value, list):
            return [clean(item, key) for item in value]
        if isinstance(value, dict):
            result = {k: clean(v, k) for k, v in value.items() if k in CONTENT_KEYS and k not in IDENTITY_KEYS}
            # 资源和引用的明确身份字段优先于纯文本署名。
            sender = value.get("sender_id") or value.get("sender_username") or value.get("member_id")
            if sender in anonymous:
                for signature in ("sender", "speaker", "author"):
                    if signature in value:
                        result[signature] = anonymous[sender]
            return result
        return value

    content = copy.deepcopy(document.get("content", {}))
    for topic in content.get("topics", []) or []:
        if not isinstance(topic, dict):
            continue
        legacy_outcome = topic.get("outcome")
        if legacy_outcome not in (None, "", [], {}):
            if isinstance(legacy_outcome, dict):
                outcome_text = next(
                    (str(legacy_outcome.get(key) or "").strip() for key in ("content", "summary", "result") if legacy_outcome.get(key)),
                    "",
                )
            else:
                outcome_text = str(legacy_outcome).strip()
            if outcome_text:
                discussion = str(topic.get("discussion_flow") or "").rstrip()
                topic["discussion_flow"] = f"{discussion}\n\n讨论结果：{outcome_text}" if discussion else outcome_text
        topic["outcome"] = None
        topic["action_items"] = []
    for key in ("members", "participant_insights", "top_speakers", "interaction_rankings", "action_items"):
        content.pop(key, None)
    content["members"] = []
    # 观察只保留群级条目，涉及成员的观察整体移除。
    content["ai_observations"] = [
        item for item in content.get("ai_observations", [])
        if not USER_REFERENCE_PATTERN.search(json.dumps(item, ensure_ascii=False))
        and not any(name and name in json.dumps(item, ensure_ascii=False) for name in names.values())
    ]
    result = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "report_id": metadata["report_id"] + "-anonymous",
            "report_variant": "anonymous",
            "source_report_id": metadata["report_id"],
            "anonymization_version": 1,
            "version": metadata.get("version", 1),
            "chat": {"id": "anonymous-chat", "name": metadata["chat"]["name"]},
            "period": copy.deepcopy(metadata["period"]),
            "generated_at": metadata.get("generated_at", ""),
            "privacy_notice": PRIVACY_NOTICE,
        },
        "stats": clean({k: v for k, v in document.get("stats", {}).items() if k in GROUP_STATS}),
        "content": clean(content),
    }
    return result
