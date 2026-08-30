"""WeChatDataAnalysis 本地 HTTP API 客户端。

数据源适配层只负责会话解析和消息分页，不包含任何 LLM 或报表逻辑。这样后续
无论分析由 AI API 还是外部 MCP 客户端完成，都可以复用同一份结构化消息。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


class WeChatDataAPIError(RuntimeError):
    """WeChatDataAnalysis 本地 API 请求或响应异常。"""


@dataclass(frozen=True)
class ChatReference:
    """已解析的微信会话。"""

    username: str
    display_name: str
    is_group: bool
    account: str
    source: str


class WeChatDataAPIClient:
    """访问 WeChatDataAnalysis 桌面端随附的本地 REST API。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:10392",
        *,
        account: str = "",
        source: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account = account.strip()
        self.source = source.strip()
        self.timeout = timeout

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = {
            key: value
            for key, value in (params or {}).items()
            if value is not None and value != ""
        }
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise WeChatDataAPIError(
                f"WeChatDataAnalysis API 返回 HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WeChatDataAPIError(
                f"无法连接 WeChatDataAnalysis 本地 API ({self.base_url})。"
                "请确认桌面工具已启动并完成微信数据加载。"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeChatDataAPIError("WeChatDataAnalysis API 返回了无效 JSON。") from exc

        if not isinstance(payload, dict):
            raise WeChatDataAPIError("WeChatDataAnalysis API 响应不是 JSON 对象。")
        if str(payload.get("status", "ok")).lower() in {"error", "failed"}:
            detail = payload.get("message") or payload.get("detail") or "未知错误"
            raise WeChatDataAPIError(f"WeChatDataAnalysis API 请求失败: {detail}")
        return payload

    def list_accounts(self) -> dict[str, Any]:
        """返回当前工具中可用的微信账号与数据源状态。"""

        return self._request("/api/chat/accounts")

    def list_sessions(self, *, limit: int = 400) -> dict[str, Any]:
        """返回会话列表；包含隐藏会话，避免群聊不在最近列表时无法解析。"""

        return self._request(
            "/api/chat/sessions",
            {
                "account": self.account,
                "source": self.source,
                "limit": max(1, limit),
                "include_hidden": "true",
                "include_official": "false",
                "preview": "none",
            },
        )

    def list_group_contacts(self, keyword: str) -> dict[str, Any]:
        """按关键词搜索群聊联系人，覆盖不在最近会话列表中的群。"""
        return self._request(
            "/api/chat/contacts",
            {
                "account": self.account,
                "source": self.source,
                "keyword": keyword,
                "include_friends": "false",
                "include_groups": "true",
                "include_officials": "false",
                "include_former_friends": "false",
                "include_blocked": "false",
            },
        )

    def resolve_chat(self, chat_ref: str) -> ChatReference:
        """按群名或 username 精确解析会话；唯一部分匹配仅作为显式兜底。"""

        needle = chat_ref.strip()
        if not needle:
            raise ValueError("群聊名称不能为空。")
        payload = self.list_sessions()
        sessions = [item for item in payload.get("sessions", []) if isinstance(item, dict)]
        groups = [item for item in sessions if bool(item.get("isGroup"))]
        exact = [
            item
            for item in groups
            if needle == str(item.get("username", "")).strip()
            or needle.casefold() == str(item.get("name", "")).strip().casefold()
        ]
        candidates = exact
        if not candidates:
            folded = needle.casefold()
            candidates = [
                item
                for item in groups
                if folded in str(item.get("name", "")).strip().casefold()
            ]
        if not candidates:
            contacts_payload = self.list_group_contacts(needle)
            contact_candidates: list[dict[str, Any]] = []
            for item in contacts_payload.get("contacts", []):
                if not isinstance(item, dict) or str(item.get("type", "")).lower() != "group":
                    continue
                name = str(
                    item.get("displayName")
                    or item.get("nickname")
                    or item.get("remark")
                    or item.get("username")
                    or ""
                ).strip()
                contact_candidates.append(
                    {
                        "username": item.get("username", ""),
                        "name": name,
                        "isGroup": True,
                    }
                )
            exact_contacts = [
                item
                for item in contact_candidates
                if needle == str(item.get("username", "")).strip()
                or needle.casefold() == str(item.get("name", "")).strip().casefold()
            ]
            candidates = exact_contacts or contact_candidates
            if candidates:
                payload = contacts_payload
        if not candidates:
            raise ValueError(f"找不到群聊: {chat_ref}")
        if len(candidates) > 1:
            names = "、".join(str(item.get("name", "")) for item in candidates[:8])
            raise ValueError(f"群聊名称不唯一，请使用完整名称或 @chatroom ID: {names}")

        item = candidates[0]
        username = str(item.get("username", "")).strip()
        if not username:
            raise WeChatDataAPIError("会话响应缺少 username，无法读取消息。")
        return ChatReference(
            username=username,
            display_name=str(item.get("name") or username).strip(),
            is_group=bool(item.get("isGroup")),
            account=str(payload.get("account") or self.account).strip(),
            source=str(payload.get("source") or self.source).strip(),
        )

    def iter_messages(
        self,
        username: str,
        *,
        start_ts: int,
        end_ts: int,
        batch_size: int = 500,
    ) -> Iterator[dict[str, Any]]:
        """按时间倒序分页读取消息，只产出闭区间 ``[start_ts, end_ts]`` 内的数据。"""

        if end_ts < start_ts:
            raise ValueError("结束时间不能早于开始时间。")
        offset = 0
        page_size = max(1, min(int(batch_size), 1000))
        seen_page_markers: set[tuple[str, str, int]] = set()

        while True:
            payload = self._request(
                "/api/chat/messages",
                {
                    "username": username,
                    "account": self.account,
                    "source": self.source,
                    "limit": page_size,
                    "offset": offset,
                    "order": "desc",
                },
            )
            rows = [item for item in payload.get("messages", []) if isinstance(item, dict)]
            if not rows:
                break

            first_id = str(rows[0].get("id", ""))
            last_id = str(rows[-1].get("id", ""))
            marker = (first_id, last_id, len(rows))
            if marker in seen_page_markers:
                raise WeChatDataAPIError("消息分页游标未前进，已停止以避免重复读取。")
            seen_page_markers.add(marker)

            oldest_ts: int | None = None
            for row in rows:
                try:
                    timestamp = int(row.get("createTime", 0) or 0)
                except (TypeError, ValueError):
                    continue
                oldest_ts = timestamp if oldest_ts is None else min(oldest_ts, timestamp)
                if start_ts <= timestamp <= end_ts:
                    yield row

            if oldest_ts is not None and oldest_ts < start_ts:
                break
            offset += len(rows)
            if len(rows) < page_size or not bool(payload.get("hasMore", False)):
                break
