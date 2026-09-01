from __future__ import annotations

import unittest
from unittest.mock import patch

from group_insight.llm import (
    DeepSeekClient,
    OpenAICompatibleClient,
    build_deepseek_balance_url,
    normalize_chat_completions_url,
)


class LLMProviderTests(unittest.TestCase):
    def test_generic_payload_contains_only_standard_fields(self):
        client = OpenAICompatibleClient(
            api_key="generic-secret",
            model="vendor-model",
            api_url="https://vendor.example/v1",
        )
        payload = client._build_payload("system", "user", 512, 0.1)
        self.assertEqual(client.api_url, "https://vendor.example/v1/chat/completions")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["max_tokens"], 512)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning_effort", payload)

    def test_deepseek_payload_adds_only_deepseek_capabilities(self):
        client = DeepSeekClient(
            api_key="deepseek-secret",
            model="deepseek-v4-pro",
            api_url="https://api.deepseek.com",
            thinking_enabled=True,
            reasoning_effort="max",
        )
        payload = client._build_payload("system", "user", None, 0.2)
        self.assertEqual(client.api_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertEqual(build_deepseek_balance_url(client.api_url), "https://api.deepseek.com/user/balance")

    def test_deepseek_model_validation_is_not_applied_to_generic_provider(self):
        with self.assertRaises(ValueError):
            DeepSeekClient(api_key="secret", model="vendor-model")
        client = OpenAICompatibleClient(
            api_key="secret", model="vendor-model", api_url="https://vendor.example/v1"
        )
        self.assertEqual(client.model, "vendor-model")

    def test_url_normalization_accepts_base_or_full_endpoint(self):
        self.assertEqual(
            normalize_chat_completions_url("https://vendor.example", "openai-compatible"),
            "https://vendor.example/v1/chat/completions",
        )
        self.assertEqual(
            normalize_chat_completions_url(
                "https://vendor.example/openai/v1/chat/completions/", "openai-compatible"
            ),
            "https://vendor.example/openai/v1/chat/completions",
        )
        with self.assertRaises(ValueError):
            normalize_chat_completions_url("https://user:password@vendor.example/v1", "openai-compatible")

    @patch("group_insight.llm.time.sleep", return_value=None)
    def test_json_parse_failure_retries_then_returns_object(self, _sleep):
        client = OpenAICompatibleClient(
            api_key="secret",
            model="vendor-model",
            api_url="https://vendor.example/v1",
            max_retries=2,
        )
        with patch.object(client, "_request_content", side_effect=["not-json", '{"ok": true}']) as request:
            self.assertEqual(client.chat_json("system", "user"), {"ok": True})
        self.assertEqual(request.call_count, 2)

    @patch("group_insight.llm.time.sleep", return_value=None)
    def test_final_error_redacts_api_key(self, _sleep):
        client = OpenAICompatibleClient(
            api_key="must-not-leak",
            model="vendor-model",
            api_url="https://vendor.example/v1",
            max_retries=2,
        )
        with patch.object(client, "_request_content", side_effect=RuntimeError("upstream must-not-leak")):
            with self.assertRaises(RuntimeError) as raised:
                client.chat_json("system", "user")
        self.assertNotIn("must-not-leak", str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
