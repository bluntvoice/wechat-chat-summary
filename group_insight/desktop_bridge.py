"""桌面端与 Python 分析核心之间的 JSONL 桥接进程。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from .desktop_config import load_desktop_settings, save_desktop_settings
from .llm import DeepSeekClient
from .wechat_data_api import WeChatDataAPIClient


def _force_utf8_stdio() -> None:
    """避免 Windows 管道在包含 emoji 的群名上回退到 GBK。"""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def normalize_chat_completions_url(value: str, provider: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        raise ValueError("API URL 不能为空。")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API URL 必须是有效的 http/https 地址。")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/chat/completions" if provider == "deepseek" else "/v1/chat/completions"
    elif path.endswith("/v1"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _client(settings: dict[str, Any], *, timeout: float = 15.0) -> WeChatDataAPIClient:
    return WeChatDataAPIClient(
        str(settings.get("wechat_api_url", "")),
        timeout=timeout,
    )


def _list_chats(settings: dict[str, Any]) -> dict[str, Any]:
    payload = _client(settings).list_sessions(limit=1000)
    seen: set[str] = set()
    chats: list[dict[str, str]] = []
    for item in payload.get("sessions", []):
        if not isinstance(item, dict) or not bool(item.get("isGroup")):
            continue
        username = str(item.get("username") or "").strip()
        name = str(item.get("name") or username).strip()
        if not username or username in seen:
            continue
        seen.add(username)
        chats.append({"id": username, "name": name})
    chats.sort(key=lambda item: item["name"].casefold())
    return {
        "connected": True,
        "account": str(payload.get("account") or ""),
        "source": str(payload.get("source") or ""),
        "chats": chats,
    }


def _test_ai(settings: dict[str, Any]) -> dict[str, Any]:
    api_key = str(settings.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("请先填写 AI API Key。")
    provider = str(settings.get("provider") or "deepseek")
    api_url = normalize_chat_completions_url(str(settings.get("api_url") or ""), provider)
    client = DeepSeekClient(
        api_key=api_key,
        model=str(settings.get("model") or "").strip(),
        api_url=api_url,
        timeout=45,
        max_retries=1,
        provider=provider,
        thinking_enabled=bool(settings.get("thinking", False)) if provider == "deepseek" else False,
    )
    result = client.chat_json(
        "你是连接测试助手，只输出 JSON。",
        '只返回 {"ok": true}。',
        max_tokens=32,
        temperature=0,
    )
    return {"connected": True, "provider": provider, "model": client.model, "response": result}


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
        "--provider",
        provider,
        "--api-url",
        api_url,
        "--model",
        str(settings.get("model") or ""),
        "--image-dpi",
        str(int(settings.get("image_dpi") or 300)),
        "--no-send-after-run",
    ]
    if bool(settings.get("thinking", False)) and provider == "deepseek":
        command.append("--thinking")

    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "DEEPSEEK_API_KEY": api_key,
            "GROUP_INSIGHT_NO_VENV_REDIRECT": "1",
        }
    )
    completed = subprocess.run(
        command,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    if completed.returncode != 0:
        tail = "\n".join(output.splitlines()[-20:])
        raise RuntimeError(tail or f"分析进程退出码: {completed.returncode}")

    result: dict[str, Any] = {"completed": True, "log": "\n".join(output.splitlines()[-30:])}
    labels = {
        "群聊报告目录: ": "chat_dir",
        "报告数据目录: ": "data_dir",
        "PNG目录: ": "image_dir",
        "JSON: ": "json_path",
        "HTML: ": "html_path",
        "PNG: ": "png_path",
    }
    for line in output.splitlines():
        for prefix, key in labels.items():
            if not line.startswith(prefix):
                continue
            value = line[len(prefix) :].strip()
            if key == "png_path" and (value.startswith("failed (") or value.startswith("skipped")):
                result["png_error"] = value
            else:
                result[key] = value
    required_outputs = ["json_path", "html_path", "png_path"]
    missing_outputs = [
        key
        for key in required_outputs
        if not result.get(key) or not Path(str(result[key])).exists()
    ]
    if missing_outputs:
        detail = str(result.get("png_error") or ", ".join(missing_outputs))
        raise RuntimeError(f"报告导出不完整: {detail}")
    return result


def handle(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command == "get_state":
        return load_desktop_settings(include_secret=False)
    if command == "save_settings":
        values = payload.get("settings", payload)
        if not isinstance(values, dict):
            raise ValueError("设置必须是 JSON 对象。")
        return save_desktop_settings(values)

    settings = load_desktop_settings(include_secret=True)
    overrides = payload.get("settings", {})
    if isinstance(overrides, dict):
        settings.update(overrides)
    if command == "test_wechat":
        result = _list_chats(settings)
        return {key: value for key, value in result.items() if key != "chats"} | {
            "group_count": len(result["chats"])
        }
    if command == "list_chats":
        return _list_chats(settings)
    if command == "test_ai":
        return _test_ai(settings)
    if command == "generate":
        return _generate(settings, payload)
    raise ValueError(f"未知命令: {command}")


def main() -> None:
    _force_utf8_stdio()
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
