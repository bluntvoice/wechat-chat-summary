from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_config import (
    load_desktop_api_key,
    load_desktop_settings,
    normalize_desktop_model,
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

    def test_deepseek_model_is_normalized_and_invalid_values_are_rejected(self):
        self.assertEqual(normalize_desktop_model("deepseek", " DeepSeek-V4-Flash "), "deepseek-v4-flash")
        self.assertEqual(normalize_desktop_model("deepseek", "deepseek-chat"), "deepseek-v4-flash")
        with self.assertRaises(ValueError):
            normalize_desktop_model("deepseek", "deepseek-v4-flahs")

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


if __name__ == "__main__":
    unittest.main()
