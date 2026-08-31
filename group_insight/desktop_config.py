"""Windows 桌面端的本机配置与私有密钥存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .settings import DEFAULT_API_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_OUTPUT_ROOT, WECHAT_DATA_API_URL


DEFAULT_DESKTOP_DATA_DIR = Path(r"D:\工具\WeChat Chat Summary\data")
DEEPSEEK_TEXT_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
LEGACY_DEEPSEEK_MODELS = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-flash",
}


def normalize_desktop_model(provider: str, model: str) -> str:
    """规范化桌面端模型，并阻止 DeepSeek 非法模型名静默保存。"""

    normalized_provider = (provider or "deepseek").strip().lower()
    normalized_model = (model or "").strip().lower()
    if normalized_provider != "deepseek":
        if not normalized_model:
            raise ValueError("模型名称不能为空。")
        return normalized_model
    normalized_model = LEGACY_DEEPSEEK_MODELS.get(normalized_model, normalized_model)
    if normalized_model not in DEEPSEEK_TEXT_MODELS:
        choices = "、".join(sorted(DEEPSEEK_TEXT_MODELS))
        raise ValueError(f"DeepSeek 模型必须选择：{choices}")
    return normalized_model


def desktop_data_dir() -> Path:
    configured = os.environ.get("WECHAT_CHAT_SUMMARY_DATA_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DESKTOP_DATA_DIR


def default_settings() -> dict[str, Any]:
    return {
        "wechat_api_url": WECHAT_DATA_API_URL,
        "provider": "deepseek",
        "api_url": DEFAULT_API_URL,
        "model": DEFAULT_DEEPSEEK_MODEL,
        "thinking": False,
        "export_root": str(DEFAULT_OUTPUT_ROOT),
        "image_dpi": 300,
        "range_mode": "single",
        "last_chat_id": "",
        "last_chat_name": "",
        "schedule_enabled": False,
        "schedule_time": "22:30",
        "schedule_chat_id": "",
        "schedule_chat_name": "",
        "schedule_last_attempt_date": "",
        "schedule_last_run_date": "",
        "schedule_last_status": "",
    }


def _config_path() -> Path:
    return desktop_data_dir() / "config.json"


def _secret_path() -> Path:
    return desktop_data_dir() / "secrets.env"


def load_desktop_settings(*, include_secret: bool = False) -> dict[str, Any]:
    settings = default_settings()
    path = _config_path()
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            settings.update(payload)
    secret = ""
    secret_path = _secret_path()
    if secret_path.exists():
        for raw_line in secret_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith("AI_API_KEY="):
                secret = raw_line.split("=", 1)[1]
                break
    settings["api_key_configured"] = bool(secret)
    if include_secret:
        settings["api_key"] = secret
    return settings


def save_desktop_settings(values: dict[str, Any]) -> dict[str, Any]:
    data_dir = desktop_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    current = load_desktop_settings(include_secret=True)
    api_key = str(values.get("api_key", current.get("api_key", ""))).strip()
    allowed = {
        "wechat_api_url",
        "provider",
        "api_url",
        "model",
        "thinking",
        "export_root",
        "image_dpi",
        "range_mode",
        "last_chat_id",
        "last_chat_name",
        "schedule_enabled",
        "schedule_time",
        "schedule_chat_id",
        "schedule_chat_name",
        "schedule_last_attempt_date",
        "schedule_last_run_date",
        "schedule_last_status",
    }
    for key in allowed:
        if key in values:
            current[key] = values[key]
    current["provider"] = str(current.get("provider") or "deepseek").strip().lower()
    current["model"] = normalize_desktop_model(
        current["provider"], str(current.get("model") or "")
    )
    public = {key: current[key] for key in allowed if key in current}
    temporary = _config_path().with_suffix(".json.tmp")
    temporary.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(_config_path())
    secret_temporary = _secret_path().with_suffix(".env.tmp")
    secret_temporary.write_text(f"AI_API_KEY={api_key}\n", encoding="utf-8")
    secret_temporary.replace(_secret_path())
    return load_desktop_settings(include_secret=False)
