"""群成员引用的可靠识别、占位符固化与最终显示支持。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any


USER_REFERENCE_PATTERN = re.compile(r"\[\[user:([^\]]+)\]\]")

_ALIAS_SPLIT_PATTERN = re.compile(r"[\s\-—–‐|｜+/&()（）\[\]【】]+")
_LEFT_BOUNDARY_CHARACTERS = "，。！？；：、,.!?;:（）()【】[]《》<>“”‘’\"'\n\r\t"
_LEFT_REFERENCE_PREFIXES = (
    "由", "请", "让", "向", "对", "据", "与", "和", "及", "随后", "之后", "其中", "而",
)
_REFERENCE_FOLLOWERS = tuple(
    sorted(
        {
            "发起", "分享", "补充", "提出", "认为", "表示", "指出", "质疑", "回应", "回复",
            "解释", "建议", "总结", "提问", "询问", "吐槽", "调侃", "坦言", "强调", "反思",
            "讲述", "评论", "证实", "感叹", "提醒", "介绍", "透露", "呼吁", "引用", "附和",
            "分析", "澄清", "开玩笑", "随即", "随后", "主动", "详细", "直言", "猜测", "认同",
            "确认", "回应称", "补充说明", "提到", "提及", "转发", "评价", "共鸣", "感慨",
            "反问", "讨论", "抱怨", "发红包", "宣布", "进一步", "提议", "发言", "参与",
            "观察", "带来", "在", "对", "问", "以", "称", "说", "等",
            "早上", "早间",
        },
        key=len,
        reverse=True,
    )
)
_DERIVED_REFERENCE_FOLLOWERS = ("的", "因", "则")
_MEMBER_TITLE_SUFFIXES = ("老师", "律师", "同学", "先生", "女士")
_GENERIC_DERIVED_ALIASES = {
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "宁波", "武汉", "江苏", "浙江",
    "律师", "法务", "涉外", "合规", "风控", "金融", "医疗", "制造业", "物流", "咨询", "快消",
}
_REFERENCE_SKIP_KEYS = {
    "id", "topic_id", "resource_id", "resource_ids", "message_id", "sender_id", "sender_username",
    "url", "file_name", "file_ext", "source", "start_time", "end_time", "sent_at", "time", "quote", "headline",
}


def member_names_from_stats(stats: dict[str, Any]) -> dict[str, str]:
    """从 Report Schema 统计区提取账号 ID 到最终显示名的映射。"""

    result: dict[str, str] = {}
    for item in stats.get("member_aliases", []) or []:
        if not isinstance(item, dict):
            continue
        sender_id = str(item.get("sender_id") or "").strip()
        sender_name = str(item.get("sender_name") or "").replace("\x7f", "").strip()
        if sender_id and sender_name and not sender_id.casefold().endswith("@chatroom"):
            result[sender_id] = sender_name
    return result


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _is_useful_derived_alias(value: str) -> bool:
    compact = _compact_whitespace(value).strip("()（）[]【】")
    if not compact or compact in {"我", "群成员", "未知成员"} or compact in _GENERIC_DERIVED_ALIASES:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.]+", compact):
        return len(compact) >= 3
    return len(compact) >= 2


def _derived_aliases(canonical_name: str) -> set[str]:
    """提取仅用于旧报告语境匹配的候选短称，不直接作为显示名。"""

    # 群昵称常见格式为“昵称-地区-行业”或“地区-行业-昵称”。只考虑括号外首尾片段，
    # 避免把中间的角色、行业或地区词误当成成员。
    outside_parentheses = re.split(r"[（(]", canonical_name, maxsplit=1)[0]
    parts = [part.strip("()（）[]【】") for part in _ALIAS_SPLIT_PATTERN.split(outside_parentheses)]
    edge_parts = parts[:1] + parts[-1:] if parts else []
    aliases = {part for part in edge_parts if _is_useful_derived_alias(part)}
    if parts and "律师" in canonical_name and parts[0] and not parts[0].endswith("律师"):
        aliases.add(f"{parts[0]}律师")
    return aliases


def _left_context_allows_reference(text: str, start: int) -> bool:
    if start <= 0:
        return True
    previous = text[start - 1]
    if previous.isspace() or previous in _LEFT_BOUNDARY_CHARACTERS:
        return True
    return text[:start].endswith(_LEFT_REFERENCE_PREFIXES)


def _right_context_allows_reference(text: str, end: int, *, derived: bool) -> bool:
    if end >= len(text):
        return True
    remainder = text[end:]
    trimmed = remainder.lstrip()
    if not trimmed:
        return True
    if trimmed.startswith(_MEMBER_TITLE_SUFFIXES) or trimmed.startswith(_REFERENCE_FOLLOWERS):
        return True
    if derived and trimmed.startswith(_DERIVED_REFERENCE_FOLLOWERS):
        return True
    next_character = remainder[0]
    if not derived and (next_character.isspace() or next_character in _LEFT_BOUNDARY_CHARACTERS):
        return True
    return False


@lru_cache(maxsize=64)
def _member_alias_index_cached(
    name_items: tuple[tuple[str, str], ...],
) -> tuple[re.Pattern[str] | None, dict[str, tuple[str, bool]]]:
    owners: dict[str, set[str]] = {}
    spellings: dict[str, str] = {}
    derived_keys: set[str] = set()

    def add(alias: str, sender_id: str, *, derived: bool = False) -> None:
        alias = str(alias or "").replace("\x7f", "").strip()
        if not alias:
            return
        key = alias.casefold()
        owners.setdefault(key, set()).add(sender_id)
        spellings.setdefault(key, alias)
        if derived:
            derived_keys.add(key)

    for raw_sender_id, raw_name in name_items:
        sender_id = str(raw_sender_id or "").strip()
        canonical_name = str(raw_name or "").replace("\x7f", "").strip()
        if not sender_id or not canonical_name:
            continue
        add(sender_id, sender_id)
        if canonical_name not in {"我", "群成员", "未知成员"}:
            add(canonical_name, sender_id)
            compact_name = _compact_whitespace(canonical_name)
            if compact_name != canonical_name:
                add(compact_name, sender_id)
            for alias in _derived_aliases(canonical_name):
                if alias.casefold() not in {canonical_name.casefold(), compact_name.casefold()}:
                    add(alias, sender_id, derived=True)

    unique: dict[str, tuple[str, bool]] = {}
    for key, alias_owners in owners.items():
        if len(alias_owners) != 1:
            continue
        sender_id = next(iter(alias_owners))
        unique[key] = (sender_id, key in derived_keys)
    if not unique:
        return None, {}

    aliases_by_length = sorted((spellings[key] for key in unique), key=len, reverse=True)
    return re.compile("|".join(re.escape(alias) for alias in aliases_by_length), re.IGNORECASE), unique


def _member_alias_index(
    names: dict[str, str],
) -> tuple[re.Pattern[str] | None, dict[str, tuple[str, bool]]]:
    return _member_alias_index_cached(tuple(sorted(names.items(), key=lambda item: item[0].casefold())))


def normalize_member_reference_text(value: Any, names: dict[str, str]) -> str:
    """把可靠成员引用固化为 ``[[user:id]]``，歧义文本保持原样。"""

    text = str(value or "")
    pattern, aliases = _member_alias_index(names)
    if pattern is None or not text:
        return text

    def normalize_plain(plain: str) -> str:
        output: list[str] = []
        cursor = 0
        for match in pattern.finditer(plain):
            key = match.group(0).casefold()
            sender_id, derived = aliases[key]
            is_sender_id = match.group(0).casefold() == sender_id.casefold()
            if is_sender_id:
                left = plain[match.start() - 1] if match.start() else ""
                right = plain[match.end()] if match.end() < len(plain) else ""
                safe = (
                    (not left or not re.match(r"[A-Za-z0-9_]", left))
                    and (not right or not re.match(r"[A-Za-z0-9_]", right))
                )
            else:
                safe = _left_context_allows_reference(plain, match.start()) and _right_context_allows_reference(
                    plain, match.end(), derived=derived
                )
            if not safe:
                continue
            output.append(plain[cursor : match.start()])
            output.append(f"[[user:{sender_id}]]")
            cursor = match.end()
        output.append(plain[cursor:])
        return "".join(output)

    output: list[str] = []
    cursor = 0
    for token in USER_REFERENCE_PATTERN.finditer(text):
        output.append(normalize_plain(text[cursor : token.start()]))
        output.append(token.group(0))
        cursor = token.end()
    output.append(normalize_plain(text[cursor:]))
    return "".join(output)


def normalize_member_references(value: Any, names: dict[str, str]) -> Any:
    """递归规范化报告正文，保留原有容器与非文本值。"""

    if isinstance(value, str):
        return normalize_member_reference_text(value, names)
    if isinstance(value, list):
        return [normalize_member_references(item, names) for item in value]
    if isinstance(value, dict):
        return {
            key: item if key in _REFERENCE_SKIP_KEYS else normalize_member_references(item, names)
            for key, item in value.items()
        }
    return value


def resolve_member_reference_text(value: Any, names: dict[str, str]) -> str:
    """把成员引用恢复为完整最终显示名；未知引用保持中性称呼。"""

    normalized = normalize_member_reference_text(value, names)
    return USER_REFERENCE_PATTERN.sub(lambda match: names.get(match.group(1), "群成员"), normalized)


def member_safe_prompt_value(value: Any, names: dict[str, str]) -> Any:
    """将提示词统计中的精确成员字段匿名化为稳定引用。"""

    exact = {str(sender_id).casefold(): f"[[user:{sender_id}]]" for sender_id in names}
    owners: dict[str, list[str]] = {}
    for sender_id, name in names.items():
        key = str(name).strip().casefold()
        if key:
            owners.setdefault(key, []).append(sender_id)
    exact.update(
        {key: f"[[user:{sender_ids[0]}]]" for key, sender_ids in owners.items() if len(sender_ids) == 1}
    )
    if isinstance(value, str):
        return exact.get(value.strip().casefold(), value)
    if isinstance(value, list):
        return [member_safe_prompt_value(item, names) for item in value]
    if isinstance(value, dict):
        return {key: member_safe_prompt_value(item, names) for key, item in value.items()}
    return value
