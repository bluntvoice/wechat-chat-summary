from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_config import load_desktop_settings, normalize_desktop_model, save_desktop_settings


class DesktopConfigTests(unittest.TestCase):
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
                    "schedule_chat_id": "room@chatroom",
                    "schedule_chat_name": "测试群",
                }
            )
            self.assertTrue(saved["schedule_enabled"])
            self.assertEqual(saved["schedule_time"], "21:45")
            save_desktop_settings({"schedule_enabled": False})
            loaded = load_desktop_settings()
            self.assertFalse(loaded["schedule_enabled"])
            self.assertEqual(loaded["schedule_chat_id"], "room@chatroom")


if __name__ == "__main__":
    unittest.main()
