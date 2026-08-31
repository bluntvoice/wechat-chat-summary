"""Windows 桌面端的本机配置与私有密钥存储。"""

from __future__ import annotations

import json
import os
import hashlib
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import DEFAULT_API_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_OUTPUT_ROOT, WECHAT_DATA_API_URL


APP_IDENTIFIER = "com.bluntvoice.wechat-chat-summary"
LEGACY_DESKTOP_DATA_DIR = Path(r"D:\工具\WeChat Chat Summary\data")
LEGACY_MIGRATION_MARKER = ".legacy-data-migration-v1.json"
MIGRATED_DATA_FILES = ("config.json", "secrets.env", "history.sqlite3")
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


def _fallback_app_local_data_dir() -> Path:
    """为非 Tauri 入口提供与 Windows LocalAppData 一致的兜底路径。"""

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / APP_IDENTIFIER
    return Path.home() / ".local" / "share" / APP_IDENTIFIER


def desktop_data_dir() -> Path:
    """返回软件自身数据目录；桌面正式入口优先使用 Tauri 解析结果。"""

    configured = os.environ.get("WECHAT_CHAT_SUMMARY_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    tauri_resolved = os.environ.get("WECHAT_CHAT_SUMMARY_APP_LOCAL_DATA_DIR", "").strip()
    return Path(tauri_resolved).expanduser() if tauri_resolved else _fallback_app_local_data_dir()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_sqlite(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite 迁移副本完整性检查失败: {result}")
    finally:
        destination_connection.close()
        source_connection.close()


def migrate_legacy_desktop_data(
    target_dir: Path | None = None,
    legacy_dir: Path = LEGACY_DESKTOP_DATA_DIR,
) -> dict[str, Any]:
    """一次性安全复制旧桌面数据；保留旧目录，不覆盖任何新目录文件。"""

    target = (target_dir or desktop_data_dir()).expanduser()
    marker = target / LEGACY_MIGRATION_MARKER
    if marker.exists():
        return {"status": "already-migrated", "copied": []}
    if not legacy_dir.is_dir() or legacy_dir.resolve() == target.resolve():
        target.mkdir(parents=True, exist_ok=True)
        return {"status": "not-needed", "copied": []}

    source_files = [name for name in MIGRATED_DATA_FILES if (legacy_dir / name).is_file()]
    if not source_files:
        target.mkdir(parents=True, exist_ok=True)
        return {"status": "not-needed", "copied": []}

    target.mkdir(parents=True, exist_ok=True)
    existing = [name for name in MIGRATED_DATA_FILES if (target / name).exists()]
    if existing:
        return {"status": "target-in-use", "copied": [], "existing": existing}

    staging = target.parent / f".{target.name}.legacy-migration-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for name in source_files:
            source = legacy_dir / name
            destination = staging / name
            if name == "history.sqlite3":
                _backup_sqlite(source, destination)
            else:
                shutil.copy2(source, destination)
                if _sha256(source) != _sha256(destination):
                    raise RuntimeError(f"旧数据复制校验失败: {name}")

        if any((target / name).exists() for name in source_files):
            raise RuntimeError("AppData 目标文件在迁移期间发生变化，已停止以避免覆盖。")
        for name in source_files:
            (staging / name).replace(target / name)

        marker_payload = {
            "version": 1,
            "migrated_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(legacy_dir),
            "target": str(target),
            "copied": source_files,
            "source_retained": True,
        }
        marker.write_text(json.dumps(marker_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "migrated", "copied": source_files}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure_desktop_data_dir() -> Path:
    """建立标准数据目录；显式测试/开发覆盖路径不触发旧数据迁移。"""

    target = desktop_data_dir()
    if os.environ.get("WECHAT_CHAT_SUMMARY_DATA_DIR", "").strip():
        target.mkdir(parents=True, exist_ok=True)
    else:
        migrate_legacy_desktop_data(target)
    return target


def default_settings() -> dict[str, Any]:
    return {
        "wechat_api_url": WECHAT_DATA_API_URL,
        "provider": "deepseek",
        "api_url": DEFAULT_API_URL,
        "model": DEFAULT_DEEPSEEK_MODEL,
        "thinking": False,
        "export_root": str(DEFAULT_OUTPUT_ROOT or ""),
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
    return ensure_desktop_data_dir() / "config.json"


def _secret_path() -> Path:
    return ensure_desktop_data_dir() / "secrets.env"


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
    data_dir = ensure_desktop_data_dir()
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
