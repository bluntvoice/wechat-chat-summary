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
    WECHAT_DATA_LOCAL_SOURCE_DIR,
    WECHAT_DATA_LOCAL_SOURCE_PORT,
    WECHAT_DATA_SOURCE,
)
from .wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError

_GROUP_NICKNAME_CACHE: dict[str, dict[str, str]] = {}
_IGNORED_MEMBER_NAME_CHARACTERS = "\x7f"


def get_group_nickname_map(chat_id: str) -> dict[str, str]:
    """返回本次 API 拉取过程中收集到的群成员显示名。"""
    return dict(_GROUP_NICKNAME_CACHE.get(chat_id, {}))


def normalize_member_display_text(value: Any) -> str:
    """移除 WeChatDataAnalysis 可能写入昵称的 DEL 占位字符。"""

    text = str(value or "")
    for character in _IGNORED_MEMBER_NAME_CHARACTERS:
        text = text.replace(character, "")
    return text.strip()


def is_resolved_member_display(username: str, display_name: str) -> bool:
    """判断显示名是否已经脱离原始账号占位。"""
    username = (username or "").strip()
    display_name = normalize_member_display_text(display_name)
    if not username or not display_name or display_name == username:
        return False
    if display_name.startswith(("wxid_", "gh_")) or display_name.endswith("@chatroom"):
        return False
    return True


def resolve_sender_display(
    username: str,
    sender_display: str,
    contact_profile: dict[str, Any] | None,
) -> str:
    """按群昵称、微信网名、账号 ID 的顺序选择名称，并排除个人备注。"""

    username = (username or "").strip()
    sender_display = normalize_member_display_text(sender_display)
    profile = contact_profile or {}
    remark = normalize_member_display_text(profile.get("remark"))
    nickname = normalize_member_display_text(profile.get("nickname"))
    profile_display = normalize_member_display_text(profile.get("displayName"))

    # WeChatDataAnalysis 的 senderDisplayName 优先给群昵称；没有群昵称时可能
    # 回落到用户自己的联系人备注。只有与 remark 相同的值才明确排除。
    if (
        sender_display
        and sender_display != "我"
        and (not remark or sender_display.casefold() != remark.casefold())
        and is_resolved_member_display(username, sender_display)
    ):
        return sender_display
    if nickname and is_resolved_member_display(username, nickname):
        return nickname
    if (
        profile_display
        and (not remark or profile_display.casefold() != remark.casefold())
        and is_resolved_member_display(username, profile_display)
    ):
        return profile_display
    return username or "unknown"


def _contact_fallback_display(
    username: str,
    contact_profile: dict[str, Any] | None,
) -> str:
    """忽略消息显示名，仅按微信网名、非备注资料名、账号 ID 回退。"""

    username = (username or "").strip()
    profile = contact_profile or {}
    remark = normalize_member_display_text(profile.get("remark"))
    nickname = normalize_member_display_text(profile.get("nickname"))
    profile_display = normalize_member_display_text(profile.get("displayName"))
    if nickname and is_resolved_member_display(username, nickname):
        return nickname
    if (
        profile_display
        and (not remark or profile_display.casefold() != remark.casefold())
        and is_resolved_member_display(username, profile_display)
    ):
        return profile_display
    return username or "unknown"


def find_member_display_collisions(
    sender_displays: list[tuple[str, str]],
    *,
    min_distinct_accounts: int = 2,
) -> set[str]:
    """返回共享同一上游显示名的账号 ID。"""

    accounts_by_display: dict[str, set[str]] = {}
    for raw_username, raw_display_name in sender_displays:
        username = (raw_username or "").strip()
        display_name = normalize_member_display_text(raw_display_name)
        if not username or not is_resolved_member_display(username, display_name):
            continue
        accounts_by_display.setdefault(display_name.casefold(), set()).add(username)

    collision_keys = {
        display_key
        for display_key, usernames in accounts_by_display.items()
        if len(usernames) >= max(2, int(min_distinct_accounts))
    }
    return {
        username
        for display_key in collision_keys
        for username in accounts_by_display[display_key]
    }


def find_member_display_account_misbindings(
    sender_displays: list[tuple[str, str]],
    known_account_ids: set[str] | None = None,
) -> set[str]:
    """返回把另一成员账号 ID 错当成显示名的发送者账号。

    WeChatDataAnalysis 的群资料解析可能把同一 ``ext_buffer`` 子记录中的
    关联成员账号误认为群昵称。这里仅在显示名精确命中另一个已知账号时
    判定异常，避免把普通英文群昵称一概视为账号占位。
    """

    account_keys = {
        str(account_id or "").strip().casefold()
        for account_id in (known_account_ids or set())
        if str(account_id or "").strip()
    }
    for raw_username, _ in sender_displays:
        username = str(raw_username or "").strip()
        if username:
            account_keys.add(username.casefold())

    misbound_usernames: set[str] = set()
    for raw_username, raw_display_name in sender_displays:
        username = str(raw_username or "").strip()
        display_name = normalize_member_display_text(raw_display_name)
        if (
            username
            and is_resolved_member_display(username, display_name)
            and display_name.casefold() != username.casefold()
            and display_name.casefold() in account_keys
        ):
            misbound_usernames.add(username)
    return misbound_usernames


def repair_member_display_collisions(
    messages: list[StructuredMessage],
    contact_profiles: dict[str, dict[str, Any]],
    collision_usernames: set[str] | None = None,
) -> set[str]:
    """修复上游碰撞或跨成员误绑定产生的异常显示名。

    调用方传入需要修复的账号集合。修复后不再信任消息接口的
    ``senderDisplayName``，改用联系人微信网名；没有可靠联系人资料时显示
    账号 ID，避免成员继续冒用同一个错误名称。
    """

    if collision_usernames is None:
        collision_usernames = find_member_display_collisions(
            [(message.sender_username, message.sender) for message in messages]
        )
    if not collision_usernames:
        return set()

    repaired_names: dict[str, str] = {}
    for message in messages:
        username = (message.sender_username or "").strip()
        if not username or username not in collision_usernames:
            continue
        repaired = repaired_names.setdefault(
            username,
            _contact_fallback_display(username, contact_profiles.get(username)),
        )
        message.sender = repaired

    metadata_name_pairs = (
        ("reply_to_username", "reply_to_name"),
        ("pat_from_username", "pat_from_name"),
        ("pat_to_username", "pat_to_name"),
        ("redpacket_sender_username", "redpacket_sender_name"),
        ("redpacket_receiver_username", "redpacket_receiver_name"),
    )
    for message in messages:
        metadata = message.metadata or {}
        for username_key, name_key in metadata_name_pairs:
            username = str(metadata.get(username_key, "")).strip()
            if username in repaired_names:
                metadata[name_key] = repaired_names[username]
    return set(repaired_names)


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


def find_unresolved_member_usernames(messages: list[StructuredMessage]) -> set[str]:
    """返回仍只能显示账号 ID、不能安全进入报告的成员。"""

    known_accounts = {
        str(message.sender_username or "").strip().casefold()
        for message in messages
        if str(message.sender_username or "").strip()
    }
    unresolved: set[str] = set()
    for message in messages:
        username = str(message.sender_username or "").strip()
        display = str(message.sender or "").strip()
        if not username:
            continue
        if (
            not is_resolved_member_display(username, display)
            or (
                display.casefold() in known_accounts
                and display.casefold() != username.casefold()
            )
        ):
            unresolved.add(username)
    return unresolved


def require_resolved_report_member_names(ctx: dict[str, Any]) -> None:
    """阻止仍含账号 ID 占位的消息范围进入报告生成。"""

    unresolved = [
        str(username).strip()
        for username in (ctx.get("unresolved_member_usernames") or [])
        if str(username).strip()
    ]
    if unresolved:
        raise ValueError(
            f"仍有 {len(unresolved)} 名参与成员无法取得可靠群昵称或微信网名，"
            "已停止生成报告；请刷新 WeChatDataAnalysis 实时数据或修复上游昵称映射。"
        )


def disambiguate_duplicate_member_names(messages: list[StructuredMessage]) -> dict[str, str]:
    """把可靠但重名的成员稳定显示为 ``昵称（01）``、``昵称（02）``。"""

    names_by_key: dict[str, dict[str, str]] = {}
    for message in messages:
        username = str(message.sender_username or "").strip()
        display = str(message.sender or "").strip()
        if username and is_resolved_member_display(username, display):
            names_by_key.setdefault(display.casefold(), {})[username] = display

    replacements: dict[str, str] = {}
    for members in names_by_key.values():
        if len(members) < 2:
            continue
        for index, username in enumerate(sorted(members, key=str.casefold), 1):
            replacements[username] = f"{members[username]}（{index:02d}）"
    if not replacements:
        return {}

    for message in messages:
        username = str(message.sender_username or "").strip()
        if username in replacements:
            message.sender = replacements[username]
        metadata = message.metadata or {}
        for username_key, name_key in (
            ("reply_to_username", "reply_to_name"),
            ("pat_from_username", "pat_from_name"),
            ("pat_to_username", "pat_to_name"),
            ("redpacket_sender_username", "redpacket_sender_name"),
            ("redpacket_receiver_username", "redpacket_receiver_name"),
        ):
            referenced = str(metadata.get(username_key, "")).strip()
            if referenced in replacements:
                metadata[name_key] = replacements[referenced]
    return replacements


def _repair_unresolved_members_from_profiles(
    messages: list[StructuredMessage],
    *,
    api_url: str,
    account: str,
    source: str,
) -> set[str]:
    """按账号调用实时资料接口，修复群昵称错绑后的微信网名。"""

    unresolved = find_unresolved_member_usernames(messages)
    if not unresolved:
        return set()
    client = WeChatDataAPIClient(
        api_url,
        account=account,
        source=source or "realtime",
        timeout=15.0,
    )
    profiles: dict[str, dict[str, Any]] = {}
    for username in sorted(unresolved, key=str.casefold):
        try:
            profile = client.get_contact_profile(username)
        except (WeChatDataAPIError, AttributeError):
            continue
        if profile:
            profiles[username] = profile
    repair_member_display_collisions(messages, profiles, set(profiles))
    return find_unresolved_member_usernames(messages)


def has_same_message_coverage(
    primary_messages: list[StructuredMessage],
    retry_messages: list[StructuredMessage],
) -> bool:
    """确认源码复读没有因快照滞后而遗漏或替换消息。"""

    if len(primary_messages) != len(retry_messages):
        return False
    primary_ids = {message.id for message in primary_messages}
    retry_ids = {message.id for message in retry_messages}
    return len(primary_ids) == len(primary_messages) and primary_ids == retry_ids


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


def _fetch_structured_messages_once(
    chat_ref: str,
    start_time: str,
    end_time: str,
    batch_size: int = 500,
    *,
    api_url: str = WECHAT_DATA_API_URL,
    account: str = WECHAT_DATA_ACCOUNT,
    source: str = WECHAT_DATA_SOURCE,
) -> tuple[dict[str, Any], list[StructuredMessage], set[str]]:
    """从单个 API 读取消息，并返回原始显示名异常账号。"""
    start_ts = _parse_local_time(start_time)
    end_ts = _parse_local_time(end_time, is_end=True)
    client = WeChatDataAPIClient(api_url, account=account, source=source)
    chat = client.resolve_chat(chat_ref)
    collected: list[StructuredMessage] = []
    seen_ids: set[str] = set()
    fingerprints: set[tuple[Any, ...]] = set()
    upstream_sender_displays: list[tuple[str, str]] = []
    try:
        contact_profiles = client.list_contact_profiles()
    except (WeChatDataAPIError, AttributeError):
        # 兼容旧版 WeChatDataAnalysis：资料接口失败时继续使用消息显示名。
        contact_profiles = {}

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
        upstream_sender_display = normalize_member_display_text(row.get("senderDisplayName"))
        upstream_sender_displays.append((sender_username, upstream_sender_display))
        sender_display = resolve_sender_display(
            sender_username,
            upstream_sender_display,
            contact_profiles.get(sender_username),
        )
        for name_key in (
            "reply_to_name",
            "pat_from_name",
            "pat_to_name",
            "redpacket_sender_name",
            "redpacket_receiver_name",
        ):
            if name_key in metadata:
                metadata[name_key] = normalize_member_display_text(metadata.get(name_key))
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

    invalid_display_usernames = find_member_display_collisions(upstream_sender_displays)
    invalid_display_usernames.update(
        find_member_display_account_misbindings(
            upstream_sender_displays,
            known_account_ids=set(contact_profiles),
        )
    )
    repair_member_display_collisions(collected, contact_profiles, invalid_display_usernames)
    collected.sort(key=lambda item: (item.timestamp, item.local_id, item.id))
    ctx = {
        "username": chat.username,
        "display_name": chat.display_name,
        "is_group": chat.is_group,
        "account": chat.account,
        "source": chat.source,
        "data_source": "wechat_data_analysis_api",
    }
    return ctx, collected, invalid_display_usernames


def fetch_structured_messages(
    chat_ref: str,
    start_time: str,
    end_time: str,
    batch_size: int = 500,
    *,
    api_url: str = WECHAT_DATA_API_URL,
    account: str = WECHAT_DATA_ACCOUNT,
    source: str = WECHAT_DATA_SOURCE,
    local_source_dir: str = WECHAT_DATA_LOCAL_SOURCE_DIR,
    local_source_port: int = WECHAT_DATA_LOCAL_SOURCE_PORT,
) -> tuple[dict[str, Any], list[StructuredMessage]]:
    """读取消息；发现昵称异常时优先用本地上游修复分支复读。"""

    primary_ctx, primary_messages, invalid_usernames = _fetch_structured_messages_once(
        chat_ref,
        start_time,
        end_time,
        batch_size,
        api_url=api_url,
        account=account,
        source=source,
    )
    primary_ctx["nickname_anomaly_detected"] = bool(invalid_usernames)
    primary_ctx["nickname_source"] = "local_contact_fallback" if invalid_usernames else "upstream"

    configured_source_dir = str(local_source_dir or "").strip()
    if invalid_usernames and configured_source_dir:
        try:
            from .local_upstream_service import LocalUpstreamService, derive_upstream_output_dir

            primary_client = WeChatDataAPIClient(api_url, account=account, source=source)
            output_dir = derive_upstream_output_dir(
                primary_client.list_accounts(),
                primary_ctx.get("account", account),
            )
            with LocalUpstreamService(
                configured_source_dir,
                output_dir=output_dir,
                port=local_source_port,
            ) as local_service:
                source_ctx, source_messages, source_invalid = _fetch_structured_messages_once(
                    primary_ctx["username"],
                    start_time,
                    end_time,
                    batch_size,
                    api_url=local_service.base_url,
                    account=primary_ctx.get("account", account),
                    source=str(primary_ctx.get("source") or source or "realtime"),
                )
            if not source_invalid and has_same_message_coverage(primary_messages, source_messages):
                source_ctx["nickname_anomaly_detected"] = True
                source_ctx["nickname_source"] = "local_upstream_branch"
                source_ctx["local_upstream_attempted"] = True
                disambiguate_duplicate_member_names(source_messages)
                source_ctx["unresolved_member_usernames"] = sorted(
                    find_unresolved_member_usernames(source_messages), key=str.casefold
                )
                _GROUP_NICKNAME_CACHE[source_ctx["username"]] = collect_member_aliases_from_messages(
                    source_messages
                )
                return source_ctx, source_messages
            if source_invalid:
                primary_ctx["local_upstream_error"] = "本地上游复读结果仍存在昵称异常。"
            else:
                primary_ctx["local_upstream_error"] = "本地上游快照未覆盖正式服务返回的同一批消息。"
        except Exception as exc:
            primary_ctx["local_upstream_error"] = str(exc)
        primary_ctx["local_upstream_attempted"] = True

    unresolved_before_profiles = find_unresolved_member_usernames(primary_messages)
    unresolved = _repair_unresolved_members_from_profiles(
        primary_messages,
        api_url=api_url,
        account=str(primary_ctx.get("account") or account),
        source=str(primary_ctx.get("source") or source or "realtime"),
    )
    if len(unresolved) < len(unresolved_before_profiles):
        primary_ctx["nickname_source"] = "realtime_contact_repair"
    disambiguate_duplicate_member_names(primary_messages)
    primary_ctx["unresolved_member_usernames"] = sorted(unresolved, key=str.casefold)

    _GROUP_NICKNAME_CACHE[primary_ctx["username"]] = collect_member_aliases_from_messages(
        primary_messages
    )
    return primary_ctx, primary_messages
