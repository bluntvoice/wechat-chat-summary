from __future__ import annotations

import os
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_config import (
    load_desktop_api_key,
    load_desktop_settings,
    normalize_desktop_model,
    remember_desktop_model,
    save_desktop_settings,
)


class DesktopConfigTests(unittest.TestCase):
    def test_mcp_is_disabled_and_loopback_only_by_default(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            loaded = load_desktop_settings()
            self.assertFalse(loaded["mcp_enabled"])
            self.assertEqual(loaded["mcp_host"], "127.0.0.1")
            self.assertEqual(loaded["mcp_endpoint"], "http://127.0.0.1:8765/mcp")
            self.assertEqual(loaded["wechat_local_source_dir"], "")
            self.assertEqual(loaded["wechat_local_source_port"], 10393)

    def test_local_upstream_source_settings_are_saved_and_port_is_validated(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            saved = save_desktop_settings(
                {
                    "wechat_local_source_dir": "D:/tools/WeChatDataAnalysis-source",
                    "wechat_local_source_port": 10493,
                }
            )
            self.assertEqual(
                saved["wechat_local_source_dir"],
                "D:/tools/WeChatDataAnalysis-source",
            )
            self.assertEqual(saved["wechat_local_source_port"], 10493)
            with self.assertRaises(ValueError):
                save_desktop_settings({"wechat_local_source_port": 80})

    def test_provider_keys_are_private_and_stored_separately(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            save_desktop_settings(
                {
                    "provider": "deepseek",
                    "api_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash",
                    "api_key": "deepseek-private",
                }
            )
            saved = save_desktop_settings(
                {
                    "provider": "openai-compatible",
                    "api_url": "https://vendor.example/v1",
                    "model": "vendor-model",
                    "api_key": "generic-private",
                }
            )
            self.assertNotIn("api_key", saved)
            self.assertTrue(saved["deepseek_api_key_configured"])
            self.assertTrue(saved["openai_compatible_api_key_configured"])
            self.assertEqual(load_desktop_api_key("deepseek"), "deepseek-private")
            self.assertEqual(load_desktop_api_key("openai-compatible"), "generic-private")
            public_config = (Path(temp_dir) / "config.json").read_text(encoding="utf-8")
            self.assertNotIn("deepseek-private", public_config)
            self.assertNotIn("generic-private", public_config)

    def test_legacy_single_key_follows_the_previously_saved_provider(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            Path(temp_dir, "config.json").write_text(
                '{"provider":"openai-compatible","api_url":"https://vendor.example/v1",'
                '"model":"vendor-model"}',
                encoding="utf-8",
            )
            Path(temp_dir, "secrets.env").write_text("AI_API_KEY=legacy-generic\n", encoding="utf-8")
            loaded = load_desktop_settings()
            self.assertTrue(loaded["openai_compatible_api_key_configured"])
            self.assertFalse(loaded["deepseek_api_key_configured"])
            self.assertEqual(load_desktop_api_key("openai-compatible"), "legacy-generic")

    def test_api_key_rejects_multiline_secret_injection(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            with self.assertRaises(ValueError):
                save_desktop_settings({"api_key": "first-line\nOPENAI_COMPATIBLE_API_KEY=injected"})

    def test_model_names_accept_new_provider_values_and_reject_blank_values(self):
        self.assertEqual(normalize_desktop_model("deepseek", " DeepSeek-V4-Flash "), "deepseek-v4-flash")
        self.assertEqual(normalize_desktop_model("deepseek", "deepseek-chat"), "deepseek-v4-flash")
        self.assertEqual(normalize_desktop_model("deepseek", " DeepSeek-V5-Preview "), "DeepSeek-V5-Preview")
        self.assertEqual(normalize_desktop_model("openai-compatible", " vendor/model-new "), "vendor/model-new")
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            saved = save_desktop_settings(
                {"provider": "deepseek", "model": " DeepSeek-V5-Preview "}
            )
            self.assertEqual(saved["model"], "DeepSeek-V5-Preview")
            self.assertEqual(load_desktop_settings()["model"], "DeepSeek-V5-Preview")
        with self.assertRaises(ValueError):
            normalize_desktop_model("deepseek", "  ")
        with self.assertRaises(ValueError):
            normalize_desktop_model("openai-compatible", "")

    def test_verified_models_are_remembered_per_provider_and_persisted(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            remember_desktop_model("openai-compatible", " vendor/model-new ")
            remember_desktop_model("deepseek", "deepseek-v4-pro")
            remember_desktop_model("openai-compatible", "vendor/model-new")
            loaded = load_desktop_settings()
            self.assertEqual(loaded["remembered_models"]["deepseek"], ["deepseek-v4-pro"])
            self.assertEqual(
                loaded["remembered_models"]["openai-compatible"],
                ["vendor/model-new"],
            )
            persisted = json.loads(Path(temp_dir, "config.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["remembered_models"], loaded["remembered_models"])

    def test_schedule_can_be_enabled_and_disabled(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            saved = save_desktop_settings(
                {
                    "schedule_enabled": True,
                    "schedule_time": "21:45",
                    "schedule_date_mode": "yesterday",
                    "schedule_chat_id": "room@chatroom",
                    "schedule_chat_name": "测试群",
                }
            )
            self.assertTrue(saved["schedule_enabled"])
            self.assertEqual(saved["schedule_time"], "21:45")
            self.assertEqual(saved["schedule_date_mode"], "yesterday")
            save_desktop_settings({"schedule_enabled": False})
            loaded = load_desktop_settings()
            self.assertFalse(loaded["schedule_enabled"])
            self.assertEqual(loaded["schedule_chat_id"], "room@chatroom")

    def test_schedule_date_mode_defaults_to_today_and_rejects_invalid_value(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            self.assertEqual(load_desktop_settings()["schedule_date_mode"], "today")
            with self.assertRaises(ValueError):
                save_desktop_settings({"schedule_date_mode": "two-days-ago"})

    def test_custom_range_defaults_to_daily_and_rejects_invalid_output_mode(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            self.assertEqual(load_desktop_settings()["range_output_mode"], "daily")
            self.assertEqual(
                save_desktop_settings({"range_output_mode": "combined"})["range_output_mode"],
                "combined",
            )
            with self.assertRaises(ValueError):
                save_desktop_settings({"range_output_mode": "weekly"})

    def test_legacy_single_schedule_is_migrated_once_and_persisted(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            config_path = Path(temp_dir, "config.json")
            config_path.write_text(
                json.dumps(
                    {
                        "schedule_enabled": True,
                        "schedule_time": "21:45",
                        "schedule_date_mode": "yesterday",
                        "schedule_chat_id": "room@chatroom",
                        "schedule_chat_name": "迁移测试群",
                        "schedule_last_attempt_date": "2026-09-07",
                        "schedule_last_run_date": "2026-09-06",
                        "schedule_last_status": "success",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            first = load_desktop_settings()
            second = load_desktop_settings()
            self.assertEqual(first["schedule_config_version"], 2)
            self.assertEqual(len(first["schedule_tasks"]), 1)
            self.assertEqual(second["schedule_tasks"], first["schedule_tasks"])
            task = first["schedule_tasks"][0]
            self.assertEqual(task["chat_id"], "room@chatroom")
            self.assertEqual(task["chat_name"], "迁移测试群")
            self.assertEqual(task["time"], "21:45")
            self.assertEqual(task["date_mode"], "yesterday")
            self.assertTrue(task["enabled"])
            self.assertEqual(task["last_report_date"], "2026-09-06")
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["schedule_tasks"], first["schedule_tasks"])

    def test_multiple_schedule_tasks_persist_by_stable_chat_id(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            tasks = [
                {
                    "task_id": "task-a", "chat_id": "a@chatroom", "chat_name": "A群",
                    "time": "22:30", "date_mode": "today", "enabled": True,
                    "created_at": "2026-09-08T10:00:00", "last_attempt_date": "",
                    "last_run_at": "", "last_report_date": "", "last_run_status": "",
                },
                {
                    "task_id": "task-b", "chat_id": "b@chatroom", "chat_name": "B群",
                    "time": "23:00", "date_mode": "yesterday", "enabled": False,
                    "created_at": "2026-09-08T10:01:00", "last_attempt_date": "",
                    "last_run_at": "", "last_report_date": "", "last_run_status": "",
                },
            ]
            saved = save_desktop_settings({"schedule_tasks": tasks})
            loaded = load_desktop_settings()
            self.assertEqual(saved["schedule_tasks"], loaded["schedule_tasks"])
            self.assertEqual([item["chat_id"] for item in loaded["schedule_tasks"]], ["a@chatroom", "b@chatroom"])
            self.assertFalse(loaded["schedule_tasks"][1]["enabled"])

            renamed = [{**loaded["schedule_tasks"][0], "chat_name": "A群新名称"}, loaded["schedule_tasks"][1]]
            refreshed = save_desktop_settings({"schedule_tasks": renamed})
            self.assertEqual(refreshed["schedule_tasks"][0]["chat_id"], "a@chatroom")
            self.assertEqual(refreshed["schedule_tasks"][0]["chat_name"], "A群新名称")

    def test_schedule_tasks_reject_duplicate_or_missing_chat_ids(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            base = {
                "task_id": "task-a", "chat_id": "a@chatroom", "chat_name": "A群",
                "time": "22:30", "date_mode": "today", "enabled": True,
            }
            with self.assertRaisesRegex(ValueError, "同一群聊"):
                save_desktop_settings({"schedule_tasks": [base, {**base, "task_id": "task-b"}]})
            with self.assertRaisesRegex(ValueError, "缺少群聊 ID"):
                save_desktop_settings({"schedule_tasks": [{**base, "chat_id": ""}]})


if __name__ == "__main__":
    unittest.main()
