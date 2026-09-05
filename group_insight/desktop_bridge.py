"""桌面端与 Python 分析核心之间的 JSONL 桥接进程。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from pathlib import Path
from typing import Any

from .desktop_config import (
    ensure_desktop_data_dir,
    load_desktop_api_key,
    load_desktop_settings,
    save_desktop_settings,
)
from .fetching import fetch_structured_messages
from .heatmap import build_heatmap_data, ensure_chat_daily_stats
from .history_store import HistoryStore
from .progress import read_progress
from .llm import DeepSeekClient, OpenAICompatibleClient, normalize_chat_completions_url
from .redaction import list_redaction_targets, redact_report_document
from .rendering import render_html_report
from .report_paths import allocate_report_paths
from .report_schema import upgrade_legacy_report
from .settings import DEFAULT_REPORT_IMAGE_TIMEOUT_MS, DEFAULT_REPORT_IMAGE_WIDTH
from .transport import export_report_image
from .wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError


def _force_utf8_stdio() -> None:
    """避免 Windows 管道在包含 emoji 的群名上回退到 GBK。"""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _client(settings: dict[str, Any], *, timeout: float = 15.0) -> WeChatDataAPIClient:
    return WeChatDataAPIClient(
        str(settings.get("wechat_api_url", "")),
        timeout=timeout,
    )


def _list_chats(settings: dict[str, Any]) -> dict[str, Any]:
    payload = _client(settings).list_sessions(limit=1000)
    with HistoryStore() as history:
        summarized = set(history.summarized_chat_ids())
    seen: set[str] = set()
    chats: list[dict[str, Any]] = []
    for item in payload.get("sessions", []):
        if not isinstance(item, dict) or not bool(item.get("isGroup")):
            continue
        username = str(item.get("username") or "").strip()
        name = str(item.get("name") or username).strip()
        if not username or username in seen:
            continue
        seen.add(username)
        chats.append({"id": username, "name": name, "summarized": username in summarized})
    chats.sort(key=lambda item: (not bool(item["summarized"]), item["name"].casefold(), item["id"]))
    return {
        "status": "connected",
        "connected": True,
        "account": str(payload.get("account") or ""),
        "source": str(payload.get("source") or ""),
        "chats": chats,
    }


def _test_wechat(settings: dict[str, Any]) -> dict[str, Any]:
    """探测当前 API 状态；不根据连接失败推断软件是否安装。"""

    try:
        result = _list_chats(settings)
    except WeChatDataAPIError as exc:
        detail = str(exc)
        if "无效 JSON" in detail or "响应不是 JSON 对象" in detail:
            status = "invalid_response"
        elif "请求失败" in detail or "返回 HTTP" in detail:
            status = "service_error"
        else:
            status = "unreachable"
        return {
            "status": status,
            "connected": False,
            "group_count": 0,
            "detail": detail,
        }
    return {key: value for key, value in result.items() if key != "chats"} | {
        "group_count": len(result["chats"])
    }


def _test_ai(settings: dict[str, Any]) -> dict[str, Any]:
    api_key = str(settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("请先填写 AI API Key。")
    provider = str(settings.get("provider") or "deepseek")
    api_url = normalize_chat_completions_url(str(settings.get("api_url") or ""), provider)
    common = {
        "api_key": api_key,
        "model": str(settings.get("model") or "").strip(),
        "api_url": api_url,
        "timeout": 45,
        "max_retries": 1,
    }
    client = (
        DeepSeekClient(
            **common,
            thinking_enabled=bool(settings.get("thinking", False)),
            reasoning_effort=str(settings.get("reasoning_effort") or "high"),
        )
        if provider == "deepseek"
        else OpenAICompatibleClient(**common)
    )
    result = client.chat_json(
        "你是连接测试助手，只输出 JSON。",
        '只返回 {"ok": true}。',
        max_tokens=32,
        temperature=0,
    )
    response_model = str(getattr(client, "last_response_model", "") or "").strip()
    model_verified = bool(response_model) and response_model.casefold() == client.model.casefold()
    if response_model and not model_verified:
        raise RuntimeError(
            f"API 实际响应模型为 {response_model}，与已选择的 {client.model} 不一致。"
        )
    return {
        "connected": True,
        "provider": provider,
        "model": client.model,
        "response_model": response_model,
        "model_verified": model_verified,
        "response": result,
    }


def build_report_entrypoint(*, frozen: bool | None = None) -> list[str]:
    """返回开发环境或安装版分析引擎的报告子进程入口。"""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return [sys.executable, "--run-report"]
    return [sys.executable, "-m", "group_insight"]


def _generate(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    required = ["chat", "start", "end", "export_root"]
    missing = [key for key in required if not str(payload.get(key) or settings.get(key) or "").strip()]
    if missing:
        raise ValueError(f"缺少生成参数: {', '.join(missing)}")
    provider = str(settings.get("provider") or "deepseek")
    api_key = str(settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未配置 AI API Key。")
    api_url = normalize_chat_completions_url(str(settings.get("api_url") or ""), provider)
    export_root = Path(str(payload.get("export_root") or settings.get("export_root"))).expanduser()
    export_root.mkdir(parents=True, exist_ok=True)
    job_id = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("job_id") or "current"))[:80] or "current"
    jobs_dir = ensure_desktop_data_dir() / "jobs"
    progress_path = jobs_dir / f"{job_id}.json"
    result_path = jobs_dir / f"{job_id}.result.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    for stale_path in (progress_path, result_path):
        if stale_path.exists():
            stale_path.unlink()

    command = [
        *build_report_entrypoint(),
        "--chat",
        str(payload["chat"]),
        "--start",
        str(payload["start"]),
        "--end",
        str(payload["end"]),
        "--output-root",
        str(export_root),
        "--wechat-api-url",
        str(settings.get("wechat_api_url") or ""),
        "--wechat-local-source-dir",
        str(settings.get("wechat_local_source_dir") or ""),
        "--wechat-local-source-port",
        str(int(settings.get("wechat_local_source_port") or 10393)),
        "--provider",
        provider,
        "--api-url",
        api_url,
        "--model",
        str(settings.get("model") or ""),
        "--image-dpi",
        str(int(settings.get("image_dpi") or 300)),
        "--no-send-after-run",
        "--progress-file",
        str(progress_path),
        "--result-file",
        str(result_path),
    ]
    if provider == "deepseek":
        command.append("--thinking" if bool(settings.get("thinking", False)) else "--no-thinking")
        if bool(settings.get("thinking", False)):
            command.extend(["--reasoning-effort", str(settings.get("reasoning_effort") or "high")])

    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            (
                "DEEPSEEK_API_KEY"
                if provider == "deepseek"
                else "OPENAI_COMPATIBLE_API_KEY"
            ): api_key,
            "GROUP_INSIGHT_NO_VENV_REDIRECT": "1",
        }
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(
        command,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    if completed.returncode != 0:
        tail = "\n".join(output.splitlines()[-20:])
        raise RuntimeError(tail or f"分析进程退出码: {completed.returncode}")

    if not result_path.is_file():
        raise RuntimeError("分析进程未返回结构化结果文件。")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"结构化生成结果无法读取: {exc}") from exc
    if (
        not isinstance(result, dict)
        or result.get("protocol_version") != 1
        or result.get("completed") is not True
    ):
        raise RuntimeError("结构化生成结果协议版本无效。")
    result["log"] = "\n".join(output.splitlines()[-30:])
    required_outputs = ["json_path", "html_path", "png_path"]
    missing_outputs = [
        key
        for key in required_outputs
        if not result.get(key) or not Path(str(result[key])).exists()
    ]
    if missing_outputs:
        detail = str(result.get("png_error") or ", ".join(missing_outputs))
        raise RuntimeError(f"报告导出不完整: {detail}")
    save_desktop_settings({
        "last_chat_id": str(payload.get("chat") or ""),
        "last_chat_name": str(payload.get("chat_name") or ""),
        "range_mode": str(payload.get("range_mode") or "single"),
    })
    with HistoryStore() as history:
        result["summarized_chat_ids"] = history.summarized_chat_ids()
    return result


def _refresh_history_state(
    settings: dict[str, Any] | None = None,
    *,
    import_reports: bool = True,
) -> dict[str, Any]:
    settings = dict(settings or load_desktop_settings(include_secret=False))
    with HistoryStore() as history:
        export_root = str(settings.get("export_root") or "").strip()
        import_result = (
            history.import_export_root(Path(export_root))
            if export_root and import_reports
            else {"scanned": 0, "imported": 0, "skipped": 0, "failed": 0}
        )
        summarized_chat_ids = history.summarized_chat_ids()
        settings["summarized_chat_ids"] = summarized_chat_ids
        settings["history_import"] = import_result
        if not str(settings.get("last_chat_id") or "") and summarized_chat_ids:
            last_chat_id = summarized_chat_ids[0]
            row = history.connection.execute(
                "SELECT display_name FROM chats WHERE chat_id=?", (last_chat_id,)
            ).fetchone()
            settings["last_chat_id"] = last_chat_id
            settings["last_chat_name"] = str(row["display_name"] if row else "")
        settings["history_chats"] = history.list_history_chats()
    return settings


def _state_with_history() -> dict[str, Any]:
    return _refresh_history_state()


def _get_heatmap_data(payload: dict[str, Any]) -> dict[str, Any]:
    chat_id = str(payload.get("chat_id") or "").strip()
    if not chat_id:
        raise ValueError("请先选择群聊。")
    with HistoryStore() as history:
        result = build_heatmap_data(
            history,
            chat_id=chat_id,
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or ""),
        )
        row = history.connection.execute(
            "SELECT display_name FROM chats WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
        result["chat_name"] = str(row["display_name"] if row else payload.get("chat_name") or chat_id)
        return result


def _ensure_daily_stats(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """按需读取微信消息并仅持久化聚合统计；此路径不创建 AI 客户端。"""

    chat_id = str(payload.get("chat_id") or "").strip()
    if not chat_id:
        raise ValueError("请先选择群聊。")
    api_url = str(settings.get("wechat_api_url") or "").strip()
    chat = _client(settings, timeout=30).resolve_chat(chat_id)

    def fetch_range(start_date: str, end_date: str):
        return fetch_structured_messages(
            chat.username,
            start_date,
            end_date,
            api_url=api_url,
            account=chat.account,
            source=chat.source,
        )

    with HistoryStore() as history:
        result = ensure_chat_daily_stats(
            history,
            chat_id=chat.username,
            chat_name=chat.display_name,
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or ""),
            fetch_range=fetch_range,
        )
    result["chat_name"] = chat.display_name
    result["ai_called"] = False
    return result


def _load_report_document(payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    source_path = Path(str(payload.get("json_path") or "")).expanduser()
    if not source_path.is_file():
        raise ValueError("找不到需要编辑的报告 JSON。")
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"报告 JSON 无法读取: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("报告 JSON 顶层必须是对象。")
    return source_path, upgrade_legacy_report(raw, source_path)


def _get_redaction_targets(payload: dict[str, Any]) -> dict[str, Any]:
    _source_path, document = _load_report_document(payload)
    return {
        "version": int(document.get("metadata", {}).get("version") or 1),
        "targets": list_redaction_targets(document),
    }


def _redact_report(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """仅在本机重渲染报告；不读取聊天，也不调用 AI。"""

    _source_path, document = _load_report_document(payload)
    target_ids = payload.get("target_ids", [])
    if not isinstance(target_ids, list) or not target_ids:
        raise ValueError("请至少选择一项需要屏蔽的报告内容。")
    metadata = document.get("metadata", {})
    chat = metadata.get("chat", {})
    period = metadata.get("period", {})
    configured_output_root = str(settings.get("export_root") or "").strip()
    if not configured_output_root:
        raise ValueError("请先选择独立的报告根目录。")
    output_root = Path(configured_output_root).expanduser()
    paths = allocate_report_paths(
        output_root,
        str(chat.get("name") or "群聊"),
        str(period.get("start") or ""),
        str(period.get("end") or ""),
    )
    json_path = paths.data_dir / f"{paths.data_stem}.json"
    html_path = paths.data_dir / f"{paths.data_stem}.html"
    exports = {
        "json": str(json_path.resolve()),
        "html": str(html_path.resolve()),
        "png": str(paths.image_path.resolve()),
    }
    redacted = redact_report_document(
        document,
        [str(value) for value in target_ids],
        version=paths.version,
        exports=exports,
    )
    json_path.write_text(json.dumps(redacted, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html_report(redacted), encoding="utf-8")
    image_error = export_report_image(
        html_path,
        paths.image_path,
        viewport_width=DEFAULT_REPORT_IMAGE_WIDTH,
        timeout_ms=DEFAULT_REPORT_IMAGE_TIMEOUT_MS,
        dpi=max(1, int(settings.get("image_dpi") or 300)),
    )
    if image_error or not paths.image_path.exists():
        raise RuntimeError(f"屏蔽版 PNG 生成失败: {image_error or '未生成图片'}")
    with HistoryStore() as history:
        history.upsert_report(redacted)
        summarized_chat_ids = history.summarized_chat_ids()
    return {
        "completed": True,
        "report_id": str(redacted.get("metadata", {}).get("report_id") or ""),
        "version": paths.version,
        "redaction_count": len(redacted.get("redactions", []) or []),
        "chat_dir": str(paths.chat_dir),
        "data_dir": str(paths.data_dir),
        "image_dir": str(paths.image_dir),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "png_path": str(paths.image_path),
        "summarized_chat_ids": summarized_chat_ids,
    }


def handle(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command == "get_state":
        return _state_with_history()
    if command == "save_settings":
        values = payload.get("settings", payload)
        if not isinstance(values, dict):
            raise ValueError("设置必须是 JSON 对象。")
        return save_desktop_settings(values)
    if command == "refresh_history_state":
        settings = load_desktop_settings(include_secret=False)
        overrides = payload.get("settings", {})
        if isinstance(overrides, dict):
            settings.update(overrides)
        return _refresh_history_state(
            settings,
            import_reports=bool(payload.get("import_reports", True)),
        )
    if command == "list_history_chats":
        with HistoryStore() as history:
            return {
                "items": history.list_history_chats(
                    keyword=str(payload.get("keyword") or ""),
                    limit=int(payload.get("limit") or 500),
                )
            }
    if command == "list_history_reports":
        with HistoryStore() as history:
            return history.list_reports(
                chat_id=str(payload.get("chat_id") or ""),
                start_date=str(payload.get("start_date") or ""),
                end_date=str(payload.get("end_date") or ""),
                module_filter=str(payload.get("module_filter") or "all"),
                keyword=str(payload.get("keyword") or ""),
                version_strategy=str(payload.get("version_strategy") or "latest"),
                limit=int(payload.get("limit") or 50),
                offset=int(payload.get("offset") or 0),
            )
    if command == "get_history_report":
        with HistoryStore() as history:
            return history.get_report_detail(str(payload.get("report_id") or ""))
    if command == "search_history":
        with HistoryStore() as history:
            return history.search_history(
                str(payload.get("keyword") or payload.get("query") or ""),
                chat_id=str(payload.get("chat_id") or ""),
                start_date=str(payload.get("start_date") or ""),
                end_date=str(payload.get("end_date") or ""),
                module_filter=str(payload.get("module_filter") or "all"),
                version_strategy=str(payload.get("version_strategy") or "latest"),
                limit=int(payload.get("limit") or 50),
                offset=int(payload.get("offset") or 0),
            )
    if command == "get_report_versions":
        with HistoryStore() as history:
            return {"items": history.list_report_versions(str(payload.get("report_id") or ""))}
    if command == "list_history_resources":
        with HistoryStore() as history:
            return history.list_resources(
                report_id=str(payload.get("report_id") or ""),
                chat_id=str(payload.get("chat_id") or ""),
                keyword=str(payload.get("keyword") or ""),
                limit=int(payload.get("limit") or 200),
                offset=int(payload.get("offset") or 0),
            )
    if command == "get_heatmap_data":
        return _get_heatmap_data(payload)
    if command == "ensure_daily_stats":
        settings = load_desktop_settings(include_secret=False)
        overrides = payload.get("settings", {})
        if isinstance(overrides, dict):
            settings.update(overrides)
        return _ensure_daily_stats(settings, payload)

    settings = load_desktop_settings(include_secret=False)
    overrides = payload.get("settings", {})
    if isinstance(overrides, dict):
        settings.update(overrides)
    provider = str(settings.get("provider") or "deepseek")
    settings["api_key"] = (
        str(overrides.get("api_key") or "").strip()
        if isinstance(overrides, dict) and "api_key" in overrides
        else load_desktop_api_key(provider)
    )
    if command == "test_wechat":
        return _test_wechat(settings)
    if command == "list_chats":
        return _list_chats(settings)
    if command == "test_ai":
        return _test_ai(settings)
    if command == "generate":
        return _generate(settings, payload)
    if command == "get_progress":
        job_id = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("job_id") or "current"))[:80] or "current"
        return read_progress(ensure_desktop_data_dir() / "jobs" / f"{job_id}.json")
    if command == "get_redaction_targets":
        return _get_redaction_targets(payload)
    if command == "redact_report":
        return _redact_report(settings, payload)
    raise ValueError(f"未知命令: {command}")


def main() -> None:
    _force_utf8_stdio()
    if len(sys.argv) > 1 and sys.argv[1] == "--run-mcp-server":
        from .mcp_server import main as run_mcp_server

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run_mcp_server()
        return
    if bool(getattr(sys, "frozen", False)) and len(sys.argv) > 1 and sys.argv[1] == "--run-report":
        from .cli import main as run_report

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run_report()
        return
    for raw_line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(raw_line)
            request_id = str(request.get("id") or "")
            command = str(request.get("command") or "")
            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON 对象。")
            response = {"id": request_id, "ok": True, "result": handle(command, payload)}
        except Exception as exc:
            response = {
                "id": request_id,
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
