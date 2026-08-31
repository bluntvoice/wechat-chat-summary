"""从 WeChatDataAnalysis 本地 API 拉取并归一化微信消息。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from .common import format_ts, normalize_text
from .models import StructuredMessage
from .rich_content import extract_rich_message_metadata
from .settings import (
    MAX_LINE_TEXT_LEN,
    WECHAT_DATA_ACCOUNT,
    WECHAT_DATA_API_URL,
    WECHAT_DATA_SOURCE,
)
from .wechat_data_api import WeChatDataAPIClient

_GROUP_NICKNAME_CACHE: dict[str, dict[str, str]] = {}


def get_group_nickname_map(chat_id: str) -> dict[str, str]:
    """返回本次 API 拉取过程中收集到的群成员显示名。"""
    return dict(_GROUP_NICKNAME_CACHE.get(chat_id, {}))


def is_resolved_member_display(username: str, display_name: str) -> bool:
    """判断显示名是否已经脱离原始账号占位。"""
    username = (username or "").strip()
    display_name = (display_name or "").strip()
    if not username or not display_name or display_name == username:
        return False
    if display_name.startswith(("wxid_", "gh_")) or display_name.endswith("@chatroom"):
        return False
    return True


def collect_member_aliases_from_messages(messages: list[StructuredMessage]) -> dict[str, str]:
    """从已结构化消息中汇总可展示的成员别名。"""
    aliases: dict[str, str] = {}

    def add_alias(username: str, display_name: str) -> None:
        username = (username or "").strip()
        display_name = (display_name or "").strip()
        if is_resolved_member_display(username, display_name):
            aliases[username] = display_name

    for message in messages:
        metadata = message.metadata or {}
        add_alias(message.sender_username, message.sender)
        for username_key, name_key in (
            ("reply_to_username", "reply_to_name"),
            ("pat_from_username", "pat_from_name"),
            ("pat_to_username", "pat_to_name"),
            ("redpacket_sender_username", "redpacket_sender_name"),
            ("redpacket_receiver_username", "redpacket_receiver_name"),
        ):
            add_alias(str(metadata.get(username_key, "")), str(metadata.get(name_key, "")))
    return aliases


def _parse_local_time(value: str, *, is_end: bool = False) -> int:
    text = normalize_text(value)
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
    for pattern in formats:
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if pattern == "%Y-%m-%d" and is_end:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return int(parsed.timestamp())
    raise ValueError(f"无法解析时间: {value}")


def _format_message_type(raw_type: Any, render_type: str) -> str:
    render = (render_type or "").strip().lower()
    if render in {"text", "quote", "reply"}:
        return "文本"
    if render in {"image", "image_group"}:
        return "图片"
    if render in {"emoji", "sticker"}:
        return "表情"
    if render in {"voice", "audio"}:
        return "语音"
    if render in {"video", "short_video"}:
        return "视频"
    if render in {"system", "notice", "revoke", "voip"}:
        return "系统"
    try:
        local_type = int(raw_type)
    except (TypeError, ValueError):
        local_type = 0
    return {
        1: "文本",
        3: "图片",
        34: "语音",
        43: "视频",
        47: "表情",
        49: "链接/文件",
        10000: "系统",
    }.get(local_type, "链接/文件")


def _analysis_text(row: dict[str, Any], msg_type: str) -> str:
    content = str(row.get("content") or "").strip()
    title = str(row.get("title") or "").strip()
    quote = str(row.get("quoteContent") or row.get("quoteTitle") or "").strip()
    transcript = str(row.get("voiceTranscript") or "").strip()
    location = str(row.get("locationLabel") or row.get("locationPoiname") or "").strip()
    if msg_type == "语音":
        return transcript or content or "[语音]"
    if msg_type == "图片":
        return title or content or "[图片]"
    if msg_type == "视频":
        return title or content or "[视频]"
    if msg_type == "表情":
        return content or title or "[表情]"
    if location:
        return f"[位置] {location}"
    parts: list[str] = []
    for item in (title, content):
        if item and item not in parts:
            parts.append(item)
    text = " — ".join(parts) or "(无内容)"
    if quote:
        text = f"{text}\n↳ 回复：{quote}"
    return text


def _build_metadata(row: dict[str, Any], raw_content: str, local_type: int) -> dict[str, Any]:
    metadata = extract_rich_message_metadata(raw_content, local_type, True)
    render_type = str(row.get("renderType") or "").strip().lower()
    title = normalize_text(str(row.get("title") or ""), max_len=180)
    url = normalize_text(str(row.get("url") or ""), max_len=600)
    content = normalize_text(str(row.get("content") or ""), max_len=240)
    source_value = row.get("from")
    source = normalize_text(source_value if isinstance(source_value, str) else "", max_len=80)
    if not metadata.get("rich_kind") and render_type == "link":
        metadata.update(
            {
                "rich_kind": "link_card",
                "title": title,
                "summary": content if content != title else "",
                "source": source,
                "url": url,
                "analysis_text": f"[链接] {title or url}" + (f"；摘要：{content}" if content and content != title else ""),
            }
        )
    elif not metadata.get("rich_kind") and render_type in {"file", "attachment"}:
        file_name = title or content
        file_ext = file_name.rsplit(".", 1)[-1] if "." in file_name else ""
        metadata.update(
            {
                "rich_kind": "file_card",
                "title": file_name,
                "file_name": file_name,
                "file_ext": normalize_text(file_ext, max_len=16),
                "file_size": int(row.get("fileSize") or 0),
                "url": url,
                "analysis_text": f"[文件] {file_name}" if file_name else "[文件]",
            }
        )
    elif render_type.lower() in {"redpacket", "transfer"}:
        metadata.setdefault("interaction_kind", "redpacket")
    metadata.update(
        {
            "data_source": "wechat_data_analysis_api",
            "render_type": str(row.get("renderType") or ""),
            "is_sent": bool(row.get("isSent")),
            "server_id": str(row.get("serverIdStr") or row.get("serverId") or ""),
        }
    )
    quote_username = str(row.get("quoteUsername") or "").strip()
    quote_text = str(row.get("quoteContent") or row.get("quoteTitle") or "").strip()
    if quote_username or quote_text:
        metadata.update(
            {
                "interaction_kind": "reply",
                "reply_to_username": quote_username,
                "reply_to_name": quote_username,
                "reply_text": quote_text,
            }
        )
    return metadata


def fetch_structured_messages(
    chat_ref: str,
    start_time: str,
    end_time: str,
    batch_size: int = 500,
    *,
    api_url: str = WECHAT_DATA_API_URL,
    account: str = WECHAT_DATA_ACCOUNT,
    source: str = WECHAT_DATA_SOURCE,
) -> tuple[dict[str, Any], list[StructuredMessage]]:
    """读取指定群聊与时间窗，并转换为分析流程使用的消息结构。"""
    start_ts = _parse_local_time(start_time)
    end_ts = _parse_local_time(end_time, is_end=True)
    client = WeChatDataAPIClient(api_url, account=account, source=source)
    chat = client.resolve_chat(chat_ref)
    collected: list[StructuredMessage] = []
    seen_ids: set[str] = set()
    fingerprints: set[tuple[Any, ...]] = set()
    aliases: dict[str, str] = {}

    for row in client.iter_messages(
        chat.username,
        start_ts=start_ts,
        end_ts=end_ts,
        batch_size=batch_size,
    ):
        try:
            timestamp = int(row.get("createTime", 0) or 0)
            local_id = int(row.get("localId", 0) or 0)
            local_type = int(row.get("type", 0) or 0)
        except (TypeError, ValueError):
            continue
        render_type = str(row.get("renderType") or "")
        msg_type = _format_message_type(local_type, render_type)
        raw_content = str(row.get("content") or "")
        metadata = _build_metadata(row, raw_content, local_type)
        text = str(metadata.get("analysis_text") or _analysis_text(row, msg_type))
        text = normalize_text(text or "(无内容)", max_len=MAX_LINE_TEXT_LEN)
        sender_username = str(row.get("senderUsername") or "").strip()
        sender_display = str(row.get("senderDisplayName") or "").strip()
        if not sender_display and bool(row.get("isSent")):
            sender_display = "我"
        sender_display = sender_display or sender_username or "unknown"
        if sender_username and is_resolved_member_display(sender_username, sender_display):
            aliases[sender_username] = sender_display
        fingerprint = (timestamp, sender_username or sender_display, msg_type, text)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        raw_id = str(row.get("id") or "").strip()
        if raw_id:
            message_id = raw_id
        else:
            seed = f"{chat.username}|{timestamp}|{sender_username}|{local_type}|{text}"
            message_id = "m_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        collected.append(
            StructuredMessage(
                id=message_id,
                local_id=local_id,
                timestamp=timestamp,
                time=format_ts(timestamp),
                sender_username=sender_username,
                sender=sender_display,
                text=text,
                msg_type=msg_type,
                chat_id=chat.username,
                chat_name=chat.display_name,
                table_name="wechat_data_analysis_api",
                metadata=metadata,
            )
        )

    _GROUP_NICKNAME_CACHE[chat.username] = aliases
    collected.sort(key=lambda item: (item.timestamp, item.local_id, item.id))
    ctx = {
        "username": chat.username,
        "display_name": chat.display_name,
        "is_group": chat.is_group,
        "account": chat.account,
        "source": chat.source,
        "data_source": "wechat_data_analysis_api",
    }
    return ctx, collected
