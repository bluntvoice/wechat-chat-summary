"""当日链接与文件资源的确定性提取、校验和主题归类。"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from collections import OrderedDict
from typing import Any

from .common import extract_topic_tokens, normalize_text, topic_similarity
from .models import StructuredMessage

URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
REDPACKET_URL_MARKERS = (
    "/mmpayhb/",
    "wxhb_personalreceive",
    "/hongbao/",
    "sendid=",
)
RESOURCE_PLATFORMS = (
    ("xiaohongshu", "小红书", ("xiaohongshu.com", "xhslink.com")),
    ("taobao", "淘宝 / 天猫", ("taobao.com", "tmall.com", "tb.cn")),
    ("wechat", "公众号", ("mp.weixin.qq.com",)),
    ("zhihu", "知乎", ("zhihu.com",)),
    ("jd", "京东", ("jd.com", "3.cn")),
    ("douyin", "抖音", ("douyin.com", "iesdouyin.com")),
    ("bilibili", "哔哩哔哩", ("bilibili.com", "b23.tv")),
    ("weibo", "微博", ("weibo.com", "weibo.cn")),
)


def _clean_url(value: str) -> str:
    value = (value or "").strip().rstrip(".,;:!?，。；：！？、）)]}")
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def classify_resource_platform(value: str, kind: str = "link") -> dict[str, str]:
    """仅按资源类型和 URL 主机名确定平台，不依赖模型猜测。"""

    if str(kind or "").casefold() == "file":
        return {"platform": "file", "platform_label": "文件"}
    url = _clean_url(value)
    if not url:
        return {"platform": "web", "platform_label": "网页"}
    host = urllib.parse.urlsplit(url).netloc.casefold().split(":", 1)[0].rstrip(".")
    for platform, label, domains in RESOURCE_PLATFORMS:
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return {"platform": platform, "platform_label": label}
    return {"platform": "web", "platform_label": "网页"}


def _resource_id(message: StructuredMessage, kind: str, identity: str) -> str:
    seed = f"{message.chat_id}|{message.id}|{kind}|{identity}"
    return "res_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def is_probable_redpacket_url(value: str) -> bool:
    """识别微信红包领取页及红包素材链接，避免当作普通资源整理。"""

    url = _clean_url(value)
    if not url:
        return False
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.casefold().split(":", 1)[0]
    haystack = f"{parsed.path}?{parsed.query}".casefold()
    if host == "wxapp.tenpay.com" and any(marker in haystack for marker in REDPACKET_URL_MARKERS):
        return True
    if host == "wx.gtimg.com" and "/hongbao/" in haystack:
        return True
    return False


def _context_summary(messages: list[StructuredMessage], index: int) -> str:
    """生成短上下文摘要，不持久化完整消息窗口。"""

    current = messages[index]
    snippets: list[str] = []
    for nearby_index in range(max(0, index - 2), min(len(messages), index + 3)):
        if nearby_index == index:
            continue
        nearby = messages[nearby_index]
        if abs(nearby.timestamp - current.timestamp) > 15 * 60:
            continue
        text = URL_RE.sub("", normalize_text(nearby.text, max_len=90)).strip(" —-；;，,")
        if not text or text.startswith("[") and text.endswith("]"):
            continue
        snippets.append(text)
        if len(snippets) >= 2:
            break
    return normalize_text("；".join(snippets), max_len=180)


def extract_resources(messages: list[StructuredMessage]) -> list[dict[str, Any]]:
    """从普通 URL、链接卡片和文件卡片中提取稳定资源对象。"""

    resources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, message in enumerate(messages):
        metadata = message.metadata or {}
        rich_kind = str(metadata.get("rich_kind") or "")
        context = _context_summary(messages, index)

        if str(metadata.get("interaction_kind") or "") in {"redpacket", "direct_redpacket"}:
            continue

        if rich_kind in {"link_card", "file_card"}:
            kind = "file" if rich_kind == "file_card" else "link"
            url = _clean_url(str(metadata.get("url") or ""))
            if is_probable_redpacket_url(url):
                continue
            title = normalize_text(metadata.get("title", ""), max_len=180)
            file_name = normalize_text(metadata.get("file_name", "") or title, max_len=180)
            identity = url or file_name or message.id
            key = (kind, identity.casefold())
            if key not in seen:
                seen.add(key)
                resources.append(
                    {
                        "id": _resource_id(message, kind, identity),
                        "type": kind,
                        "title": file_name if kind == "file" else (title or url),
                        "url": url,
                        "sender_id": message.sender_username,
                        "sender": message.sender,
                        "sent_at": message.time,
                        "message_id": message.id,
                        "file_name": file_name if kind == "file" else "",
                        "file_extension": normalize_text(metadata.get("file_extension", "") or metadata.get("file_ext", ""), max_len=24),
                        "file_size": int(metadata.get("file_size") or 0),
                        "source": normalize_text(metadata.get("source", ""), max_len=80),
                        "context_summary": context or normalize_text(metadata.get("summary", ""), max_len=180),
                        **classify_resource_platform(url, kind),
                    }
                )

        rich_url = _clean_url(str(metadata.get("url") or ""))
        for raw_url in URL_RE.findall(message.text or ""):
            url = _clean_url(raw_url)
            if not url or url == rich_url or is_probable_redpacket_url(url):
                continue
            key = ("link", url.casefold())
            if key in seen:
                continue
            seen.add(key)
            resources.append(
                {
                    "id": _resource_id(message, "link", url),
                    "type": "link",
                    "title": urllib.parse.urlsplit(url).netloc,
                    "url": url,
                    "sender_id": message.sender_username,
                    "sender": message.sender,
                    "sent_at": message.time,
                    "message_id": message.id,
                    "file_name": "",
                    "file_extension": "",
                    "file_size": 0,
                    "source": "普通 URL",
                    "context_summary": context,
                    **classify_resource_platform(url),
                }
            )
    return resources


def compact_resources_for_prompt(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅向模型提供主题归类所需的受控字段。"""

    return [
        {
            "id": item.get("id", ""),
            "type": item.get("type", ""),
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "sender": item.get("sender", ""),
            "sent_at": item.get("sent_at", ""),
            "context_summary": item.get("context_summary", ""),
        }
        for item in resources
    ]


def _local_topic(item: dict[str, Any], topics: list[dict[str, Any]]) -> tuple[str, str]:
    item_tokens = extract_topic_tokens(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "source", "context_summary")
        )
    )
    best_title = ""
    best_key = ""
    best_score = 0.0
    for index, topic in enumerate(topics, start=1):
        title = normalize_text(topic.get("title", ""), max_len=60)
        summary = normalize_text(topic.get("discussion_flow", "") or topic.get("summary", ""), max_len=220)
        score = topic_similarity(item_tokens, extract_topic_tokens(f"{title} {summary}"))
        if score > best_score:
            best_title = title
            best_key = str(topic.get("id") or f"topic-{index}")
            best_score = score
    return (best_key, best_title) if best_title and best_score >= 0.18 else ("other", "其他 / 未归类")


def _matches_topic(item: dict[str, Any], topic: dict[str, Any]) -> bool:
    """用资源标题与短上下文复核模型关联，宁可未归类也不串错话题。"""

    item_tokens = extract_topic_tokens(
        " ".join(str(item.get(key) or "") for key in ("title", "source", "context_summary"))
    )
    topic_tokens = extract_topic_tokens(
        " ".join(
            str(topic.get(key) or "")
            for key in ("title", "discussion_flow", "summary")
        )
    )
    return bool(item_tokens and topic_tokens and topic_similarity(item_tokens, topic_tokens) >= 0.18)


def build_resource_catalog(
    resources: list[dict[str, Any]],
    ai_groups: list[dict[str, Any]] | None,
    topics: list[dict[str, Any]],
) -> dict[str, Any]:
    """校验模型归类并为遗漏资源提供本地主题兜底。"""

    by_id = {str(item.get("id")): dict(item) for item in resources if item.get("id")}
    topic_by_id = {
        str(topic.get("id") or topic.get("topic_key") or f"topic-{index}"): topic
        for index, topic in enumerate(topics, start=1)
        if isinstance(topic, dict)
    }
    proposed_groups = list(ai_groups or [])
    if not proposed_groups:
        proposed_groups = [
            {
                "topic_id": topic_id,
                "topic": topic.get("title", ""),
                "resource_ids": topic.get("resource_ids", []),
            }
            for topic_id, topic in topic_by_id.items()
            if isinstance(topic.get("resource_ids"), list) and topic.get("resource_ids")
        ]

    assignments: dict[str, tuple[str, str, str]] = {}
    for group in proposed_groups:
        title = normalize_text(group.get("topic", ""), max_len=60)
        if not title:
            continue
        requested_key = normalize_text(group.get("topic_id", ""), max_len=80)
        is_other = title in {"其他", "未归类", "其他 / 未归类"} or requested_key == "other"
        if not is_other and requested_key not in topic_by_id:
            continue
        group_key = "other" if is_other else requested_key
        if group_key in topic_by_id:
            title = normalize_text(topic_by_id[group_key].get("title", ""), max_len=60) or title
        summary = normalize_text(group.get("summary", ""), max_len=180)
        for resource_id in group.get("resource_ids", []):
            resource_id = str(resource_id)
            if (
                resource_id in by_id
                and resource_id not in assignments
                and (group_key == "other" or _matches_topic(by_id[resource_id], topic_by_id[group_key]))
            ):
                assignments[resource_id] = (group_key, title, summary)

    grouped: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for resource_id, item in by_id.items():
        if resource_id in assignments:
            topic_key, topic_title, group_summary = assignments[resource_id]
        else:
            topic_key, topic_title = _local_topic(item, topics)
            group_summary = ""
        item["topic_id"] = topic_key
        item["topic"] = topic_title
        group = grouped.setdefault(
            topic_key,
            {"topic_id": topic_key, "topic": topic_title, "summary": group_summary, "items": []},
        )
        group["items"].append(item)

    groups = list(grouped.values())
    groups.sort(key=lambda group: (group["topic_id"] == "other", -len(group["items"]), group["topic"]))
    return {"count": len(resources), "groups": groups}
