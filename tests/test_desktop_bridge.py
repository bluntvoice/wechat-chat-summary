from __future__ import annotations

import sys
import unittest

from group_insight.desktop_bridge import build_report_entrypoint, normalize_chat_completions_url


class DesktopBridgeTests(unittest.TestCase):
    def test_development_report_entrypoint_uses_module(self) -> None:
        self.assertEqual(
            build_report_entrypoint(frozen=False),
            [sys.executable, "-m", "group_insight"],
        )

    def test_frozen_report_entrypoint_reuses_sidecar(self) -> None:
        self.assertEqual(
            build_report_entrypoint(frozen=True),
            [sys.executable, "--run-report"],
        )

    def test_deepseek_base_url_gets_chat_completions_path(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("https://api.deepseek.com", "deepseek"),
            "https://api.deepseek.com/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
