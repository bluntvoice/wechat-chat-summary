from __future__ import annotations

import sys
import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_bridge import (
    _ensure_daily_stats,
    _list_chats,
    _redact_report,
    _refresh_history_state,
    _test_ai,
    _test_wechat,
    build_report_entrypoint,
    handle,
    normalize_chat_completions_url,
)
from group_insight.models import StructuredMessage
from group_insight.history_store import HistoryStore as ActualHistoryStore
from group_insight.report_paths import allocate_report_paths
from group_insight.report_schema import build_report_document
from group_insight.wechat_data_api import WeChatDataAPIError
from tests.test_history_center import history_document


class DesktopBridgeTests(unittest.TestCase):
    def test_heatmap_daily_stats_never_construct_an_ai_client(self) -> None:
        from group_insight.wechat_data_api import ChatReference

        class FakeAPI:
            def resolve_chat(self, _chat_id):
                return ChatReference(
                    username="room@chatroom",
                    display_name="统计群",
                    is_group=True,
                    account="account-a",
                    source="native",
                )

        timestamp = int(datetime(2026, 8, 31, 12, 0, 0).timestamp())
        messages = [StructuredMessage(
            id="message-1", local_id=1, timestamp=timestamp,
            time="2026-08-31 12:00:00", sender_username="wxid_a", sender="甲",
            text="本地统计", msg_type="文本", chat_id="room@chatroom", chat_name="统计群",
            table_name="test", metadata={},
        )]
        with TemporaryDirectory() as temp_dir:
            with (
                patch("group_insight.desktop_bridge._client", return_value=FakeAPI()),
                patch("group_insight.desktop_bridge.fetch_structured_messages", return_value=(
                    {"username": "room@chatroom", "display_name": "统计群"}, messages,
                )),
                patch("group_insight.desktop_bridge.HistoryStore", side_effect=lambda: ActualHistoryStore(Path(temp_dir) / "history.sqlite3")),
                patch("group_insight.desktop_bridge.DeepSeekClient") as ai_client,
            ):
                result = _ensure_daily_stats(
                    {"wechat_api_url": "http://127.0.0.1:10392"},
                    {"chat_id": "room@chatroom", "start_date": "2026-08-31", "end_date": "2026-08-31"},
                )
        self.assertFalse(ai_client.called)
        self.assertFalse(result["ai_called"])
        self.assertEqual(result["days"][0]["message_count"], 1)

    def test_ai_connection_reports_actual_response_model(self) -> None:
        class FakeClient:
            model = "deepseek-v4-flash"
            last_response_model = "deepseek-v4-flash"

            def chat_json(self, *_args, **_kwargs):
                return {"ok": True}

        with patch("group_insight.desktop_bridge.DeepSeekClient", return_value=FakeClient()):
            result = _test_ai({
                "api_key": "test-key", "provider": "deepseek",
                "api_url": "https://api.deepseek.com", "model": "deepseek-v4-flash",
                "thinking": False,
            })
        self.assertTrue(result["model_verified"])
        self.assertEqual(result["response_model"], "deepseek-v4-flash")

    def test_wechat_connection_reports_unreachable_without_claiming_not_installed(self) -> None:
        detail = (
            "无法连接 WeChatDataAnalysis 本地 API (http://127.0.0.1:10392)。"
            "请确认桌面工具已启动并完成微信数据加载。"
        )
        with patch("group_insight.desktop_bridge._list_chats", side_effect=WeChatDataAPIError(detail)):
            result = _test_wechat({"wechat_api_url": "http://127.0.0.1:10392"})
        self.assertEqual(result["status"], "unreachable")
        self.assertFalse(result["connected"])
        self.assertEqual(result["group_count"], 0)
        self.assertNotIn("未安装", result["detail"])

    def test_wechat_connection_distinguishes_invalid_response(self) -> None:
        with patch(
            "group_insight.desktop_bridge._list_chats",
            side_effect=WeChatDataAPIError("WeChatDataAnalysis API 返回了无效 JSON。"),
        ):
            result = _test_wechat({"wechat_api_url": "http://127.0.0.1:10392"})
        self.assertEqual(result["status"], "invalid_response")
        self.assertFalse(result["connected"])

    def test_ai_connection_rejects_unexpected_response_model(self) -> None:
        class FakeClient:
            model = "deepseek-v4-flash"
            last_response_model = "deepseek-v4-pro"

            def chat_json(self, *_args, **_kwargs):
                return {"ok": True}

        with patch("group_insight.desktop_bridge.DeepSeekClient", return_value=FakeClient()):
            with self.assertRaisesRegex(RuntimeError, "实际响应模型"):
                _test_ai({
                    "api_key": "test-key", "provider": "deepseek",
                    "api_url": "https://api.deepseek.com", "model": "deepseek-v4-flash",
                    "thinking": False,
                })

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

    def test_redaction_rerenders_locally_without_ai(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "reports"
            first_paths = allocate_report_paths(
                root, "测试群", "2026-08-31 00:00:00", "2026-08-31 23:59:59"
            )
            source_path = first_paths.data_dir / f"{first_paths.data_stem}.json"
            document = build_report_document(
                ctx={"username": "room@chatroom", "display_name": "测试群"},
                start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
                stats={"message_count": 2, "participant_count": 1},
                report={"one_line_summary": "摘要", "theme_cards": [{"title": "待屏蔽", "summary": "私密内容"}], "sections": []},
                resources={"count": 0, "groups": []},
                exports={"json": str(source_path), "html": "old.html", "png": "old.png"},
                provider="deepseek", model="model", dry_run=False, chunk_count=1, chunk_plan={},
            )
            source_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

            def fake_export(_html_path: Path, image_path: Path, **_kwargs: object) -> str:
                image_path.write_bytes(b"test-png")
                return ""

            history_path = Path(temp_dir) / "history.sqlite3"
            with (
                patch("group_insight.desktop_bridge.export_report_image", side_effect=fake_export),
                patch("group_insight.desktop_bridge.HistoryStore", side_effect=lambda: ActualHistoryStore(history_path)),
                patch("group_insight.desktop_bridge.DeepSeekClient") as ai_client,
            ):
                result = _redact_report(
                    {"export_root": str(root), "image_dpi": 300},
                    {"json_path": str(source_path), "target_ids": ["themes:0"]},
                )

            self.assertEqual(result["version"], 2)
            self.assertTrue(result["report_id"])
            self.assertFalse(ai_client.called)
            new_payload = Path(result["json_path"]).read_text(encoding="utf-8")
            self.assertNotIn("私密内容", new_payload)
            self.assertIn("已屏蔽，建议在群内查看", new_payload)
            with ActualHistoryStore(history_path) as history:
                stored = history.get_report_detail(result["report_id"])
            self.assertEqual(stored["version"], 2)
            self.assertEqual(stored["exports"]["json"]["path"], result["json_path"])

    def test_chat_list_pins_summarized_ids_and_never_injects_missing_wechat_groups(self) -> None:
        class FakeAPI:
            def list_sessions(self, *, limit: int):
                self.limit = limit
                return {
                    "account": "account-a",
                    "source": "realtime",
                    "sessions": [
                        {"username": "z@chatroom", "name": "Beta 群", "isGroup": True},
                        {"username": "history@chatroom", "name": "跨境项目讨论群", "isGroup": True},
                        {"username": "a@chatroom", "name": "Alpha 群", "isGroup": True},
                    ],
                }

        with TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(Path(temp_dir) / "data")}
        ):
            root = Path(temp_dir)
            with ActualHistoryStore() as history:
                history.upsert_report(history_document(root))
                missing = history_document(root, version=2)
                missing["metadata"]["chat"] = {"id": "missing@chatroom", "name": "已退出旧群"}
                missing["metadata"]["report_id"] = "report-missing-history"
                history.upsert_report(missing)
            with patch("group_insight.desktop_bridge._client", return_value=FakeAPI()):
                result = _list_chats({"wechat_api_url": "http://127.0.0.1:10392"})
            self.assertEqual(result["status"], "connected")
            self.assertEqual(
                [item["id"] for item in result["chats"]],
                ["history@chatroom", "a@chatroom", "z@chatroom"],
            )
            self.assertTrue(result["chats"][0]["summarized"])
            self.assertNotIn("missing@chatroom", {item["id"] for item in result["chats"]})

    def test_refresh_history_state_imports_new_export_root_and_bridge_queries_it(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(Path(temp_dir) / "data")}
        ):
            root = Path(temp_dir) / "reports"
            report_dir = root / "跨境项目讨论群" / "报告数据" / "2026-08-31报告数据"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "跨境项目讨论群_2026-08-31_群聊总结.json"
            report_path.write_text(
                json.dumps(history_document(root), ensure_ascii=False),
                encoding="utf-8",
            )
            state = _refresh_history_state({"export_root": str(root)}, import_reports=True)
            self.assertEqual(state["summarized_chat_ids"], ["history@chatroom"])
            self.assertEqual(state["history_import"]["imported"], 1)
            chats = handle("list_history_chats", {})["items"]
            self.assertEqual(chats[0]["chat_id"], "history@chatroom")
            reports = handle(
                "list_history_reports",
                {"chat_id": "history@chatroom", "version_strategy": "latest"},
            )
            self.assertEqual(reports["items"][0]["version"], 1)
            report_id = reports["items"][0]["report_id"]
            detail = handle("get_history_report", {"report_id": report_id})
            self.assertEqual(detail["chat_id"], "history@chatroom")
            self.assertNotIn("action_items", {item["module_key"] for item in detail["modules"]})
            versions = handle("get_report_versions", {"report_id": report_id})["items"]
            self.assertEqual([item["version"] for item in versions], [1])
            search = handle("search_history", {"keyword": "尾程清关"})
            self.assertGreater(search["total"], 0)
            resources = handle("list_history_resources", {"report_id": report_id})
            self.assertEqual(resources["total"], 2)


if __name__ == "__main__":
    unittest.main()
