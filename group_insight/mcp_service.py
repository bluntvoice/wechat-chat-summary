"""MCP tools 的受控业务服务；不包含 transport 或 AI Provider。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import make_user_placeholder, normalize_text
from .desktop_config import load_desktop_settings, save_desktop_settings
from .fetching import fetch_structured_messages, require_resolved_report_member_names
from .history_store import HistoryStore
from .rendering import render_html_report
from .report_paths import allocate_report_paths
from .report_schema import build_report_document, validate_report_schema_2_2
from .resources import build_resource_catalog, compact_resources_for_prompt, extract_resources
from .stats import build_chat_daily_stats, build_local_stats
from .transport import export_report_image
from .wechat_data_api import WeChatDataAPIClient

MAX_ANALYSIS_RANGE_DAYS = 31
MAX_ANALYSIS_MESSAGES = 2000
MAX_ANALYSIS_TEXT_CHARS = 1_000_000
MAX_SUBMITTED_REPORT_BYTES = 2 * 1024 * 1024


def _require_identifier(value: str, label: str, *, max_len: int = 256) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空。")
    if len(normalized) > max_len or any(character in normalized for character in "\r\n\x00"):
        raise ValueError(f"{label} 格式无效。")
    return normalized


def _optional_date(value: str, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label} 必须使用 YYYY-MM-DD。") from exc
    return normalized


def _parse_time(value: str, *, is_end: bool) -> datetime:
    text = normalize_text(value)
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if pattern == "%Y-%m-%d" and is_end:
            return parsed.replace(hour=23, minute=59, second=59)
        return parsed
    raise ValueError(f"无法解析时间: {value}")


def validate_analysis_range(start: str, end: str) -> tuple[str, str]:
    start_at = _parse_time(start, is_end=False)
    end_at = _parse_time(end, is_end=True)
    if end_at < start_at:
        raise ValueError("结束时间不能早于开始时间。")
    if (end_at - start_at).total_seconds() > MAX_ANALYSIS_RANGE_DAYS * 86400:
        raise ValueError(f"单次原始聊天分析范围不能超过 {MAX_ANALYSIS_RANGE_DAYS} 天。")
    return start_at.strftime("%Y-%m-%d %H:%M:%S"), end_at.strftime("%Y-%m-%d %H:%M:%S")


class MCPService:
    """复用数据读取、统计、Schema、渲染与历史能力的 MCP 服务层。"""

    def _settings(self) -> dict[str, Any]:
        return load_desktop_settings(include_secret=False)

    def _wechat(self) -> WeChatDataAPIClient:
        settings = self._settings()
        return WeChatDataAPIClient(str(settings.get("wechat_api_url") or ""), timeout=30)

    def list_chats(self) -> dict[str, Any]:
        payload = self._wechat().list_sessions(limit=1000)
        chats = [
            {"chat_id": str(item.get("username") or ""), "name": str(item.get("name") or item.get("username") or "")}
            for item in payload.get("sessions", [])
            if isinstance(item, dict) and bool(item.get("isGroup")) and item.get("username")
        ]
        chats.sort(key=lambda item: (item["name"].casefold(), item["chat_id"]))
        return {"items": chats, "count": len(chats)}

    def _require_current_chat(self, chat_id: str) -> dict[str, str]:
        needle = _require_identifier(chat_id, "chat_id")
        matches = [item for item in self.list_chats()["items"] if item["chat_id"] == needle]
        if not matches:
            raise ValueError("chat_id 不在当前可分析群聊列表中。请先调用 list_chats。")
        return matches[0]

    def _messages(self, chat_id: str, start: str, end: str):
        chat = self._require_current_chat(chat_id)
        start_at, end_at = validate_analysis_range(start, end)
        settings = self._settings()
        ctx, messages = fetch_structured_messages(
            chat["chat_id"],
            start_at,
            end_at,
            api_url=str(settings.get("wechat_api_url") or ""),
            local_source_dir=str(settings.get("wechat_local_source_dir") or ""),
            local_source_port=int(settings.get("wechat_local_source_port") or 10393),
        )
        if len(messages) > MAX_ANALYSIS_MESSAGES:
            raise ValueError(
                f"当前范围包含 {len(messages)} 条消息，超过单次 {MAX_ANALYSIS_MESSAGES} 条限制，请缩短时间范围。"
            )
        text_chars = sum(len(item.text) for item in messages)
        if text_chars > MAX_ANALYSIS_TEXT_CHARS:
            raise ValueError(
                f"当前范围包含 {text_chars} 个消息字符，超过单次 {MAX_ANALYSIS_TEXT_CHARS} 字符限制，请缩短时间范围。"
            )
        return ctx, messages, start_at, end_at

    def get_chat_stats(self, chat_id: str, start: str, end: str) -> dict[str, Any]:
        ctx, messages, start_at, end_at = self._messages(chat_id, start, end)
        stats = build_local_stats(messages)
        return {
            "chat": {"id": ctx["username"], "name": ctx["display_name"]},
            "period": {"start": start_at, "end": end_at},
            "stats": stats,
        }

    def get_chat_analysis_context(self, chat_id: str, start: str, end: str) -> dict[str, Any]:
        ctx, messages, start_at, end_at = self._messages(chat_id, start, end)
        stats = build_local_stats(messages)
        resources = extract_resources(messages)
        stats["resource_breakdown"] = {
            "link": sum(1 for item in resources if item.get("type") == "link"),
            "file": sum(1 for item in resources if item.get("type") == "file"),
        }
        controlled_messages = [
            {
                "id": item.id,
                "time": item.time,
                "sender_id": item.sender_username,
                "sender_ref": make_user_placeholder(item.sender_username),
                "sender_name": item.sender,
                "message_type": item.msg_type,
                "text": item.text,
            }
            for item in messages
        ]
        return {
            "schema_version": "2.2",
            "chat": {"id": ctx["username"], "name": ctx["display_name"]},
            "period": {"start": start_at, "end": end_at},
            "stats": stats,
            "resources": compact_resources_for_prompt(resources),
            "messages": controlled_messages,
            "limits": {
                "max_range_days": MAX_ANALYSIS_RANGE_DAYS,
                "max_messages": MAX_ANALYSIS_MESSAGES,
                "max_text_chars": MAX_ANALYSIS_TEXT_CHARS,
            },
            "privacy": {"persisted_raw_messages": False},
        }

    def get_daily_stats(self, chat_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        chat_id = _require_identifier(chat_id, "chat_id")
        start_date = _optional_date(start_date, "start_date")
        end_date = _optional_date(end_date, "end_date")
        if not start_date or not end_date:
            raise ValueError("start_date 和 end_date 不能为空。")
        start_at = datetime.strptime(start_date, "%Y-%m-%d")
        end_at = datetime.strptime(end_date, "%Y-%m-%d")
        if end_at < start_at or (end_at - start_at).days > 365:
            raise ValueError("每日统计范围必须有效且不超过 366 天。")
        with HistoryStore() as history:
            row = history.connection.execute("SELECT 1 FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
            if row is None:
                raise ValueError("历史库中不存在该 chat_id。")
            items = history.get_chat_daily_stats(chat_id, start_date=start_date, end_date=end_date)
        return {"chat_id": chat_id, "start_date": start_date, "end_date": end_date, "items": items}

    def list_history(
        self,
        chat_id: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        chat_id = _require_identifier(chat_id, "chat_id") if chat_id else ""
        start_date = _optional_date(start_date, "start_date")
        end_date = _optional_date(end_date, "end_date")
        if start_date and end_date and end_date < start_date:
            raise ValueError("end_date 不能早于 start_date。")
        with HistoryStore() as history:
            return history.list_reports(
                chat_id=chat_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                offset=offset,
            )

    def search_history(
        self,
        query: str,
        chat_id: str = "",
        start_date: str = "",
        end_date: str = "",
        module_filter: str = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = normalize_text(query, max_len=201)
        if not query:
            raise ValueError("query 不能为空。")
        if len(query) > 200:
            raise ValueError("query 不能超过 200 个字符。")
        chat_id = _require_identifier(chat_id, "chat_id") if chat_id else ""
        start_date = _optional_date(start_date, "start_date")
        end_date = _optional_date(end_date, "end_date")
        if start_date and end_date and end_date < start_date:
            raise ValueError("end_date 不能早于 start_date。")
        with HistoryStore() as history:
            return history.search_history(
                query,
                chat_id=chat_id,
                start_date=start_date,
                end_date=end_date,
                module_filter=module_filter,
                limit=limit,
                offset=offset,
            )

    def get_report(self, report_id: str) -> dict[str, Any]:
        report_id = _require_identifier(report_id, "report_id", max_len=200)
        with HistoryStore() as history:
            detail = history.get_report_detail(report_id)
        return {
            "schema_version": detail["schema_version"],
            "metadata": {
                "report_id": detail["report_id"],
                "chat": {"id": detail["chat_id"], "name": detail["display_name"]},
                "period": {
                    "start": detail["period_start"],
                    "end": detail["period_end"],
                    "report_date": detail["report_date"],
                },
                "version": detail["version"],
                "generated_at": detail["generated_at"],
                "ai": {"provider": detail["provider"], "model": detail["model"]},
            },
            "stats": detail["stats"],
            "content": detail["content"],
        }

    @staticmethod
    def _report_payload(content: dict[str, Any]) -> dict[str, Any]:
        return {
            "one_line_summary": content.get("one_line_summary", ""),
            "lead_summary": content.get("lead_summary", ""),
            "theme_cards": content.get("themes", []),
            "sections": content.get("topics", []),
            "ai_observations": content.get("ai_observations", []),
            "participant_insights": content.get("members", []),
            "mood": content.get("mood", {}),
            "conclusion": content.get("conclusion", ""),
        }

    def submit_report(self, document: dict[str, Any]) -> dict[str, Any]:
        serialized = json.dumps(document, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > MAX_SUBMITTED_REPORT_BYTES:
            raise ValueError("提交报告超过 2 MiB 限制。")
        validate_report_schema_2_2(document)
        metadata = document["metadata"]
        chat = metadata["chat"]
        period = metadata["period"]
        ctx, messages, start_at, end_at = self._messages(chat["id"], period["start"], period["end"])
        require_resolved_report_member_names(ctx)
        if str(chat.get("name") or "") != str(ctx["display_name"]):
            raise ValueError("报告 chat.name 与当前数据源不一致。")
        stats = build_local_stats(messages)
        extracted = extract_resources(messages)
        stats["resource_breakdown"] = {
            "link": sum(1 for item in extracted if item.get("type") == "link"),
            "file": sum(1 for item in extracted if item.get("type") == "file"),
        }
        submitted_stats = document.get("stats", {})
        for key in ("message_count", "effective_message_count", "participant_count"):
            if int(submitted_stats.get(key) or 0) != int(stats.get(key) or 0):
                raise ValueError(f"报告 stats.{key} 与本地统计不一致。")
        content = document["content"]
        incoming_groups = []
        for group in content.get("resources", {}).get("groups", []):
            if not isinstance(group, dict):
                continue
            incoming_groups.append(
                {
                    "topic_id": group.get("topic_id", ""),
                    "topic": group.get("topic", ""),
                    "summary": group.get("summary", ""),
                    "resource_ids": [
                        str(item.get("id"))
                        for item in group.get("items", [])
                        if isinstance(item, dict) and item.get("id")
                    ],
                }
            )
        report_payload = self._report_payload(content)
        resources = build_resource_catalog(extracted, incoming_groups, report_payload["sections"])
        settings = self._settings()
        export_root = str(settings.get("export_root") or "").strip()
        if not export_root:
            raise ValueError("尚未配置独立报告根目录。")
        paths = allocate_report_paths(Path(export_root).expanduser(), ctx["display_name"], start_at, end_at)
        json_path = paths.data_dir / f"{paths.data_stem}.json"
        html_path = paths.data_dir / f"{paths.data_stem}.html"
        exports = {"json": str(json_path.resolve()), "html": str(html_path.resolve()), "png": str(paths.image_path.resolve())}
        ai = metadata.get("ai", {}) if isinstance(metadata.get("ai"), dict) else {}
        final_document = build_report_document(
            ctx=ctx,
            start_time=start_at,
            end_time=end_at,
            version=paths.version,
            stats=stats,
            report=report_payload,
            resources=resources,
            exports=exports,
            provider="mcp-host",
            model=normalize_text(ai.get("model", "external-ai"), max_len=120) or "external-ai",
            dry_run=False,
            chunk_count=0,
            chunk_plan={"strategy": "external-mcp-host", "mode": "mcp", "estimated_tokens": 0},
        )
        validate_report_schema_2_2(final_document)
        created = [json_path, html_path, paths.image_path]
        try:
            json_path.write_text(json.dumps(final_document, ensure_ascii=False, indent=2), encoding="utf-8")
            html_path.write_text(render_html_report(final_document), encoding="utf-8")
            image_error = export_report_image(
                html_path,
                paths.image_path,
                dpi=max(1, int(settings.get("image_dpi") or 300)),
            )
            if image_error or not paths.image_path.is_file():
                raise RuntimeError(f"MCP 报告 PNG 生成失败: {image_error or '未生成图片'}")
            with HistoryStore() as history:
                report_id = history.upsert_report(final_document, daily_stats=build_chat_daily_stats(messages))
                summarized = history.summarized_chat_ids()
            save_desktop_settings({"summarized_chat_ids": summarized})
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return {
            "completed": True,
            "report_id": report_id,
            "version": paths.version,
            "schema_version": "2.2",
            "summarized_chat_ids": summarized,
        }

    def render_report(self, report_id: str) -> dict[str, Any]:
        """只恢复历史库中报告缺失的受控导出，不接受任意路径。"""

        report_id = _require_identifier(report_id, "report_id", max_len=200)
        settings = self._settings()
        export_root_value = str(settings.get("export_root") or "").strip()
        if not export_root_value:
            raise ValueError("尚未配置独立报告根目录。")
        export_root = Path(export_root_value).expanduser().resolve()
        with HistoryStore() as history:
            detail = history.get_report_detail(report_id)
        paths = {key: Path(str(value["path"])).expanduser().resolve() for key, value in detail["exports"].items()}
        for path in paths.values():
            if not path.is_relative_to(export_root):
                raise ValueError("历史报告路径不在当前受控导出根目录内。")
        document = self.get_report(report_id)
        document["metadata"]["exports"] = {key: str(path) for key, path in paths.items()}
        validate_report_schema_2_2(document)
        restored: list[str] = []
        if not paths["json"].is_file():
            paths["json"].parent.mkdir(parents=True, exist_ok=True)
            paths["json"].write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            restored.append("json")
        if not paths["html"].is_file():
            paths["html"].parent.mkdir(parents=True, exist_ok=True)
            paths["html"].write_text(render_html_report(document), encoding="utf-8")
            restored.append("html")
        if not paths["png"].is_file():
            error = export_report_image(paths["html"], paths["png"], dpi=max(1, int(settings.get("image_dpi") or 300)))
            if error or not paths["png"].is_file():
                raise RuntimeError(f"历史报告 PNG 恢复失败: {error or '未生成图片'}")
            restored.append("png")
        return {"completed": True, "report_id": report_id, "restored": restored}
