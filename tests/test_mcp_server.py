from __future__ import annotations

import asyncio
import http.client
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from mcp import Client

from group_insight.desktop_config import load_desktop_settings, save_desktop_settings
from group_insight.history_store import HistoryStore
from group_insight.mcp_server import create_mcp_server, run_server
from group_insight.mcp_service import MAX_ANALYSIS_TEXT_CHARS, MCPService, validate_analysis_range
from group_insight.models import StructuredMessage
from group_insight.report_schema import build_report_document
from group_insight.stats import build_local_stats


CHAT = {"username": "room@chatroom", "display_name": "测试群"}
START = "2026-08-31 00:00:00"
END = "2026-08-31 23:59:59"


def sample_messages() -> list[StructuredMessage]:
    return [
        StructuredMessage(
            id="m1",
            local_id=1,
            timestamp=1788134400,
            time="2026-08-31 08:00:00",
            sender_username="wxid_a",
            sender="小甲",
            text="[[user:wxid_b]] 请确认项目清单。",
            msg_type="文本",
            chat_id=CHAT["username"],
            chat_name=CHAT["display_name"],
            table_name="api",
            metadata={},
        ),
        StructuredMessage(
            id="m2",
            local_id=2,
            timestamp=1788138000,
            time="2026-08-31 09:00:00",
            sender_username="wxid_b",
            sender="小乙",
            text="今天完成清单复核。",
            msg_type="文本",
            chat_id=CHAT["username"],
            chat_name=CHAT["display_name"],
            table_name="api",
            metadata={},
        ),
    ]


def valid_external_document() -> dict:
    stats = build_local_stats(sample_messages())
    return build_report_document(
        ctx=CHAT,
        start_time=START,
        end_time=END,
        version=1,
        stats=stats,
        report={
            "one_line_summary": "今天完成项目清单复核。",
            "lead_summary": "群成员明确了清单复核安排。",
            "theme_cards": [],
            "sections": [
                {
                    "id": "topic-checklist",
                    "title": "项目清单复核",
                    "start_time": "08:00",
                    "end_time": "09:00",
                    "time_ranges": [{"start": "08:00", "end": "09:00"}],
                    "discussion_flow": "[[user:wxid_a]] 发起确认，[[user:wxid_b]] 明确当天完成。",
                    "outcome": {"content": "当天完成复核。", "tone": "formal", "confidence": 0.95},
                    "action_items": [],
                    "open_questions": [],
                    "risk_flags": [],
                    "quotes": [],
                    "resource_ids": [],
                }
            ],
            "ai_observations": [],
            "participant_insights": [],
            "mood": {},
            "conclusion": "已形成明确安排。",
        },
        resources={"count": 0, "groups": []},
        exports={},
        provider="external-host",
        model="external-model",
        dry_run=False,
        chunk_count=0,
        chunk_plan={"strategy": "external-mcp-host"},
    )


def fake_png_export(_html_path: Path, image_path: Path, **_kwargs):
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return None


class MCPServiceTests(unittest.TestCase):
    def test_range_validation_rejects_reverse_invalid_and_oversized_ranges(self):
        with self.assertRaises(ValueError):
            validate_analysis_range("2026-08-02", "2026-08-01")
        with self.assertRaises(ValueError):
            validate_analysis_range("not-a-date", "2026-08-01")
        with self.assertRaises(ValueError):
            validate_analysis_range("2026-01-01", "2026-03-01")

    def test_list_chats_filters_non_groups_and_invalid_chat_is_rejected(self):
        client = MagicMock()
        client.list_sessions.return_value = {
            "sessions": [
                {"username": "room@chatroom", "name": "测试群", "isGroup": True},
                {"username": "wxid_person", "name": "个人", "isGroup": False},
            ]
        }
        service = MCPService()
        with patch.object(service, "_wechat", return_value=client):
            self.assertEqual(service.list_chats()["items"], [{"chat_id": "room@chatroom", "name": "测试群"}])
            with self.assertRaises(ValueError):
                service._require_current_chat("missing@chatroom")

    def test_stats_and_analysis_context_are_controlled_and_not_persisted(self):
        service = MCPService()
        messages = sample_messages()
        with patch.object(service, "_messages", return_value=(CHAT, messages, START, END)):
            stats = service.get_chat_stats(CHAT["username"], START, END)
            context = service.get_chat_analysis_context(CHAT["username"], START, END)
        self.assertEqual(stats["stats"]["message_count"], 2)
        self.assertEqual(context["messages"][0]["sender_ref"], "[[user:wxid_a]]")
        self.assertEqual(context["privacy"], {"persisted_raw_messages": False})
        self.assertNotIn("metadata", context["messages"][0])

    def test_analysis_context_rejects_an_abnormally_large_text_payload(self):
        service = MCPService()
        messages = sample_messages()
        messages[0].text = "x" * (MAX_ANALYSIS_TEXT_CHARS + 1)
        with (
            patch.object(
                service,
                "list_chats",
                return_value={"items": [{"chat_id": CHAT["username"], "name": CHAT["display_name"]}]},
            ),
            patch("group_insight.mcp_service.fetch_structured_messages", return_value=(CHAT, messages)),
        ):
            with self.assertRaisesRegex(ValueError, "消息字符"):
                service.get_chat_analysis_context(CHAT["username"], START, END)

    def test_invalid_schema_is_rejected_before_chat_or_storage_access(self):
        service = MCPService()
        document = valid_external_document()
        document["content"]["action_items"] = []
        with patch.object(service, "_messages") as messages:
            with self.assertRaisesRegex(ValueError, "Report Schema 2.2"):
                service.submit_report(document)
        messages.assert_not_called()

    def test_new_schema_rejects_nonempty_action_items(self):
        service = MCPService()
        document = valid_external_document()
        document["content"]["topics"][0]["action_items"] = [{"task": "不应进入新报告"}]
        with patch.object(service, "_messages") as messages:
            with self.assertRaisesRegex(ValueError, "Report Schema 2.2"):
                service.submit_report(document)
        messages.assert_not_called()

    def test_submit_report_rejects_unresolved_member_names(self):
        service = MCPService()
        document = valid_external_document()
        unresolved_ctx = {**CHAT, "unresolved_member_usernames": ["wxid_unknown"]}
        with patch.object(
            service,
            "_messages",
            return_value=(unresolved_ctx, sample_messages(), START, END),
        ):
            with self.assertRaisesRegex(ValueError, "停止生成报告"):
                service.submit_report(document)

    def test_submit_versions_renders_and_updates_history_and_summary_cache(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            export_root = Path(temp_dir) / "reports"
            save_desktop_settings({"export_root": str(export_root)})
            service = MCPService()
            document = valid_external_document()
            messages = sample_messages()
            with (
                patch.object(service, "_messages", return_value=(CHAT, messages, START, END)),
                patch("group_insight.mcp_service.export_report_image", side_effect=fake_png_export),
            ):
                first = service.submit_report(document)
                second = service.submit_report(document)
            self.assertEqual(first["version"], 1)
            self.assertEqual(second["version"], 2)
            self.assertNotEqual(first["report_id"], second["report_id"])
            with HistoryStore() as history:
                self.assertEqual(history.summarized_chat_ids(), [CHAT["username"]])
                self.assertEqual(history.list_reports()["total"], 1)
                detail = history.get_report_detail(second["report_id"])
                self.assertEqual(detail["provider"], "mcp-host")
                self.assertNotIn("messages", detail["content"])
                html_path = Path(detail["exports"]["html"]["path"])
                png_path = Path(detail["exports"]["png"]["path"])
            self.assertEqual(load_desktop_settings()["summarized_chat_ids"], [CHAT["username"]])
            self.assertTrue(html_path.is_file())
            self.assertTrue(png_path.is_file())
            html_path.unlink()
            png_path.unlink()
            with patch("group_insight.mcp_service.export_report_image", side_effect=fake_png_export):
                rendered = service.render_report(second["report_id"])
            self.assertEqual(set(rendered["restored"]), {"html", "png"})
            self.assertTrue(html_path.is_file())
            self.assertTrue(png_path.is_file())

    def test_history_list_search_report_and_daily_stats_do_not_expose_paths(self):
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir}
        ):
            save_desktop_settings({"export_root": str(Path(temp_dir) / "reports")})
            service = MCPService()
            with (
                patch.object(service, "_messages", return_value=(CHAT, sample_messages(), START, END)),
                patch("group_insight.mcp_service.export_report_image", side_effect=fake_png_export),
            ):
                submitted = service.submit_report(valid_external_document())
            listed = service.list_history()
            searched = service.search_history("项目清单")
            report = service.get_report(submitted["report_id"])
            daily = service.get_daily_stats(CHAT["username"], "2026-08-31", "2026-08-31")
            self.assertEqual(listed["total"], 1)
            self.assertGreaterEqual(searched["total"], 1)
            self.assertEqual(report["schema_version"], "2.2")
            self.assertEqual(len(daily["items"]), 1)
            combined = repr((listed, searched, report, daily))
            self.assertNotIn(str(Path(temp_dir)), combined)


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_exposes_the_expected_tools_in_process(self):
        service = MagicMock()
        service.list_chats.return_value = {"items": [], "count": 0}
        server = create_mcp_server(service)
        async with Client(server) as client:
            listed = await client.list_tools()
            called = await client.call_tool("list_chats")
        names = {tool.name for tool in listed.tools}
        self.assertEqual(
            names,
            {
                "list_chats",
                "get_chat_stats",
                "get_chat_analysis_context",
                "get_daily_stats",
                "list_history",
                "search_history",
                "get_report",
                "submit_report",
                "render_report",
            },
        )
        self.assertEqual(called.structured_content, {"items": [], "count": 0})

    async def test_real_streamable_http_process_completes_protocol_handshake(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        with TemporaryDirectory() as temp_dir:
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "WECHAT_CHAT_SUMMARY_DATA_DIR": temp_dir,
                }
            )
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "group_insight.desktop_bridge",
                    "--run-mcp-server",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            try:
                for _attempt in range(50):
                    if process.poll() is not None:
                        self.fail(f"MCP Server 提前退出，exit={process.returncode}")
                    try:
                        _reader, writer = await asyncio.wait_for(
                            asyncio.open_connection("127.0.0.1", port), timeout=0.2
                        )
                        writer.close()
                        await writer.wait_closed()
                        break
                    except (OSError, asyncio.TimeoutError):
                        await asyncio.sleep(0.1)
                else:
                    self.fail("MCP Server 未在 5 秒内监听端口。")
                async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                    listed = await client.list_tools()
                self.assertIn("submit_report", {tool.name for tool in listed.tools})

                def request_with_untrusted_host() -> int:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                    try:
                        connection.request("GET", "/mcp", headers={"Host": "attacker.example"})
                        return connection.getresponse().status
                    finally:
                        connection.close()

                rejected_status = await asyncio.to_thread(request_with_untrusted_host)
                self.assertIn(rejected_status, {400, 403, 421})
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


class MCPBindingTests(unittest.TestCase):
    def test_streamable_http_is_bound_to_loopback(self):
        server = MagicMock()
        with patch("group_insight.mcp_server.create_mcp_server", return_value=server):
            run_server(8765)
        server.run.assert_called_once_with(
            transport="streamable-http",
            host="127.0.0.1",
            port=8765,
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            max_request_body_size=4 * 1024 * 1024,
        )
        with self.assertRaises(ValueError):
            run_server(80)


if __name__ == "__main__":
    unittest.main()
