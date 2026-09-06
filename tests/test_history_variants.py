from __future__ import annotations

import copy
import json
import os
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.anonymization import anonymize_report, first_seen_members
from group_insight.desktop_bridge import _anonymous_report, _regenerate, _delete_report
from group_insight.history_store import HistoryStore
from group_insight.models import StructuredMessage
from group_insight.rendering import render_html_report
from group_insight.report_lock import report_lock
from group_insight.report_paths import allocate_report_paths
from tests.test_history_center import history_document


def message(sender, timestamp, kind="文本"):
    return StructuredMessage(str(timestamp), timestamp, timestamp, "2026-08-31 10:00:00",
        sender, sender, "讨论资料", kind, "room@chatroom", "测试群", "", {})


def normal(root, version=1):
    document = history_document(root, version=version)
    document["metadata"]["member_first_seen_order"] = ["wxid_bob", "wxid_alice"]
    document["stats"]["member_aliases"] = [
        {"sender_id": "wxid_alice", "sender_name": "很长的真实昵称-北京-律师"},
        {"sender_id": "wxid_bob", "sender_name": "苹果"},
    ]
    document["content"]["topics"][0]["discussion_flow"] = "[[user:wxid_alice]]认为苹果手机销量上涨。@[[user:wxid_bob]]补充资料。[[user:wxid_alice]]表示赞同。"
    document["content"]["topics"][0]["quotes"] = [{"speaker": "[[user:wxid_bob]]", "quote": "先核对资料"}]
    document["stats"]["interaction_rankings"] = {"reply_sender": [{"name": "苹果", "count": 387}]}
    document["stats"]["speaker_directory"] = [{"sender_id": "wxid_alice"}]
    document["stats"]["known_speakers"] = ["苹果"]
    return document


class AnonymizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = normal(self.root)

    def derive(self):
        return anonymize_report(self.document, ["wxid_bob", "wxid_alice"])

    def test_first_real_message_order_and_system_exclusion(self):
        self.assertEqual(first_seen_members([message("wxid_alice", 3), message("wxid_bob", 1),
            message("wxid_alice", 2), message("wxid_system", 0, "系统")]), ["wxid_bob", "wxid_alice"])

    def test_multi_day_and_repeated_member_number_stays_consistent(self):
        self.assertEqual(first_seen_members([message("wxid_bob", 1), message("wxid_alice", 86401),
            message("wxid_bob", 86402)]), ["wxid_bob", "wxid_alice"])
        text = self.derive()["content"]["topics"][0]["discussion_flow"]
        self.assertEqual(text.count("群友02"), 2)
        self.assertIn("@群友01", text)

    def test_json_contains_no_identity_or_reverse_mapping(self):
        text = json.dumps(self.derive(), ensure_ascii=False)
        for value in ("wxid_", "member_id", "nickname", "member_aliases", "speaker_directory", "很长的真实昵称"):
            self.assertNotIn(value, text)

    def test_html_anonymous_members_are_blue_bold(self):
        html = render_html_report(self.derive())
        self.assertIn('class="topic-member">群友02</strong>', html)
        self.assertNotIn("wxid_", html)
        self.assertNotIn("很长的真实昵称", html)

    def test_member_statistics_removed_group_statistics_retained(self):
        result = self.derive()
        self.assertEqual(result["content"]["members"], [])
        for key in ("top_speakers", "interaction_rankings", "known_speakers"):
            self.assertNotIn(key, result["stats"])
        for key in ("message_count", "participant_count", "effective_message_count"):
            self.assertEqual(result["stats"][key], self.document["stats"][key])

    def test_plain_word_not_replaced_and_normal_untouched(self):
        before = copy.deepcopy(self.document)
        self.assertIn("苹果手机销量上涨", self.derive()["content"]["topics"][0]["discussion_flow"])
        self.assertEqual(before, self.document)

    def test_same_name_distinct_id_and_long_names(self):
        for row in self.document["stats"]["member_aliases"]:
            row["sender_name"] = "同名成员"
        text = self.derive()["content"]["topics"][0]["discussion_flow"]
        self.assertIn("群友01", text)
        self.assertIn("群友02", text)
        self.assertNotIn("同名成员", text)

    def test_legacy_variant_defaults_normal(self):
        self.document["metadata"].pop("report_variant", None)
        self.assertEqual(self.derive()["metadata"]["report_variant"], "anonymous")

    def test_legacy_outcome_moves_into_discussion_and_schema_field_is_normalized(self):
        result = self.derive()
        topic = result["content"]["topics"][0]
        self.assertIsNone(topic["outcome"])
        self.assertIn("采用新清关渠道", topic["discussion_flow"])

    def test_unknown_token_and_unsafe_plain_identity_block_export(self):
        for text in ("[[user:wxid_missing]]表示", "wxid_alice表示", "苹果认为价格会上涨"):
            with self.subTest(text=text):
                self.document["content"]["topics"][0]["discussion_flow"] = text
                with self.assertRaises(ValueError):
                    self.derive()

    def test_resource_metadata_and_unreliable_signature_removed(self):
        item = self.document["content"]["resources"]["groups"][0]["items"][0]
        item.update(sender_id="wxid_alice", sender="很长的真实昵称-北京-律师",
            metadata={"nickname": "苹果"}, real_name="不能导出的名字", uploader_nickname="苹果")
        result = self.derive()["content"]["resources"]["groups"][0]["items"][0]
        self.assertEqual(result["sender"], "群友02")
        for key in ("metadata", "sender_id", "real_name", "uploader_nickname"):
            self.assertNotIn(key, result)

    def test_member_observations_removed(self):
        self.document["content"]["ai_observations"] = [{"content": "[[user:wxid_bob]]发言最多"}, {"content": "全群围绕资料进行讨论"}]
        self.assertEqual(len(self.derive()["content"]["ai_observations"]), 1)


class HistoryVariantIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(self.root / "app")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.document = normal(self.root)
        self.save(self.document)

    def save(self, document):
        for kind, value in document["metadata"]["exports"].items():
            Path(value).write_text(json.dumps(document, ensure_ascii=False) if kind == "json" else kind, encoding="utf-8")
        with HistoryStore() as history:
            history.upsert_report(document)

    @staticmethod
    def image(_html, target, **_kwargs):
        target.write_bytes(b"test-png")
        return ""

    def anonymous(self):
        with patch("group_insight.desktop_bridge.export_report_image", side_effect=self.image):
            return _anonymous_report({}, {"report_id": self.document["metadata"]["report_id"]})

    def test_offline_anonymous_never_calls_ai_or_source_and_reuses_id(self):
        with patch("group_insight.desktop_bridge.fetch_structured_messages", side_effect=AssertionError("source called")), patch("group_insight.desktop_bridge._generate", side_effect=AssertionError("AI called")):
            result = self.anonymous()
            again = self.anonymous()
        self.assertEqual(result["report_id"], again["report_id"])
        self.assertFalse(result["ai_called"])
        for kind in ("html", "json", "png"):
            self.assertIn("-匿名版.", result[kind + "_path"])
            self.assertTrue(Path(result[kind + "_path"]).is_file())

    def test_legacy_missing_order_source_unavailable_preserves_normal(self):
        self.document["metadata"].pop("member_first_seen_order")
        self.save(self.document)
        with patch("group_insight.desktop_bridge.fetch_structured_messages", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(ValueError, "请先启动 WeChatDataAnalysis"):
                self.anonymous()
        self.assertTrue(Path(self.document["metadata"]["exports"]["json"]).is_file())

    def test_anonymous_png_failure_preserves_existing_derived_files(self):
        result = self.anonymous()
        before = {kind: Path(result[kind + "_path"]).read_bytes() for kind in ("json", "html", "png")}
        with patch("group_insight.desktop_bridge.export_report_image", return_value="failed"):
            with self.assertRaises(RuntimeError):
                _anonymous_report({}, {"report_id": self.document["metadata"]["report_id"]})
        for kind, content in before.items():
            self.assertEqual(Path(result[kind + "_path"]).read_bytes(), content)

    def test_search_and_heatmap_no_identity_no_double_count(self):
        result = self.anonymous()
        with HistoryStore() as history:
            links = history.get_report_links_by_date(self.document["metadata"]["chat"]["id"], start_date="2026-08-31", end_date="2026-08-31")
            self.assertEqual(len(links), 1)
            self.assertEqual(links["2026-08-31"]["report_id"], self.document["metadata"]["report_id"])
            self.assertEqual(history.list_history_chats()[0]["report_count"], 1)
            self.assertEqual(len(history.summarized_chat_ids()), 1)
            matches = history.search_reports("群友02")
            anonymous_match = next(row for row in matches if row["report_id"] == result["report_id"])
            self.assertEqual(anonymous_match["report_variant"], "anonymous")
            self.assertFalse(any(row["report_id"] == result["report_id"] for row in history.search_reports("很长的真实昵称")))

    def test_middle_list_only_shows_latest_normal_while_versions_include_anonymous(self):
        result = self.anonymous()
        with HistoryStore() as history:
            middle = history.list_reports(chat_id=self.document["metadata"]["chat"]["id"])
            versions = history.list_report_versions(self.document["metadata"]["report_id"])
        self.assertEqual([item["report_id"] for item in middle["items"]], [self.document["metadata"]["report_id"]])
        self.assertEqual([item["report_id"] for item in versions], [self.document["metadata"]["report_id"], result["report_id"]])

    def test_delete_anonymous_preserves_normal(self):
        result = self.anonymous()
        _delete_report({"report_id": result["report_id"]})
        with HistoryStore() as history:
            self.assertEqual(len(history.list_report_versions(self.document["metadata"]["report_id"])), 1)
        self.assertTrue(Path(self.document["metadata"]["exports"]["json"]).is_file())

    def test_delete_normal_cascades_derived(self):
        result = self.anonymous()
        _delete_report({"report_id": self.document["metadata"]["report_id"]})
        with HistoryStore() as history:
            self.assertEqual(history.connection.execute("SELECT count(*) FROM reports").fetchone()[0], 0)
            self.assertEqual(history.connection.execute("SELECT count(*) FROM report_search_fts").fetchone()[0], 0)
        self.assertFalse(Path(result["json_path"]).exists())

    def test_regenerate_uses_history_parameters_current_settings_and_main_pipeline(self):
        current = {"provider": "openai_compatible", "model": "current-model", "api_key": "test"}
        with patch("group_insight.desktop_bridge._generate", return_value={"completed": True}) as generate:
            _regenerate(current, {"report_id": self.document["metadata"]["report_id"], "start": "2099-01-01", "chat": "wrong"})
        settings, arguments = generate.call_args.args
        self.assertIs(settings, current)
        self.assertEqual(arguments["chat"], self.document["metadata"]["chat"]["id"])
        self.assertEqual(arguments["start"], "2026-08-31 00:00:00")
        self.assertEqual(arguments["end"], "2026-08-31 23:59:59")

    def test_regenerate_rejects_anonymous_and_multiday(self):
        result = self.anonymous()
        with patch("group_insight.desktop_bridge._generate") as generate:
            with self.assertRaises(ValueError):
                _regenerate({}, {"report_id": result["report_id"]})
            with HistoryStore() as history:
                history.connection.execute("UPDATE reports SET period_end='2026-09-01 23:59:59' WHERE report_variant='normal'")
                history.connection.commit()
            with self.assertRaises(ValueError):
                _regenerate({}, {"report_id": self.document["metadata"]["report_id"]})
            generate.assert_not_called()

    def test_failures_leave_old_revision_and_anonymous(self):
        result = self.anonymous()
        for error in ("AI failed", "指定时间范围内没有消息", "WeChatDataAnalysis offline"):
            with patch("group_insight.desktop_bridge._generate", side_effect=RuntimeError(error)):
                with self.assertRaises(RuntimeError):
                    _regenerate({}, {"report_id": self.document["metadata"]["report_id"]})
        with HistoryStore() as history:
            self.assertEqual(len(history.list_report_versions(result["report_id"])), 2)

    def test_lock_prevents_duplicate_ai_calls(self):
        metadata = self.document["metadata"]
        with report_lock(f"generate:{metadata['chat']['id']}:2026-08-31:2026-08-31"), patch("group_insight.desktop_bridge._generate") as generate:
            with self.assertRaisesRegex(ValueError, "已有任务"):
                _regenerate({}, {"report_id": metadata["report_id"]})
            generate.assert_not_called()

    def test_highest_revision_allocation_and_old_anonymous_retained(self):
        result = self.anonymous()
        for version in (2, 3):
            self.save(normal(self.root, version))
        with HistoryStore() as history:
            highest = history.connection.execute("SELECT max(version) FROM reports WHERE report_variant='normal'").fetchone()[0]
            self.assertEqual(len(history.list_report_versions(result["report_id"])), 4)
        paths = allocate_report_paths(self.root / "exports", "测试群", "2026-08-31", "2026-08-31", min_version=highest + 1)
        self.assertEqual(paths.version, 4)


class MainPipelineAtomicityTests(unittest.TestCase):
    def test_stage_failures_never_publish_partial_revision(self):
        from group_insight import cli
        for failing_stage in ("run_map_stage", "render_html_report", "export_report_image", "validate_report_schema_2_2", "upsert_report"):
            with self.subTest(stage=failing_stage), TemporaryDirectory() as temp:
                root = Path(temp)
                with patch.dict(os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(root / "app")}), patch.object(sys, "argv", [
                    "group_insight", "--chat", "room@chatroom", "--start", "2026-08-31 00:00:00", "--end", "2026-08-31 23:59:59",
                    "--output-root", str(root / "reports"), "--dry-run", "--no-send-after-run",
                ]), patch.object(cli, "fetch_structured_messages", return_value=({"username": "room@chatroom", "display_name": "测试群"}, [message("wxid_bob", 1788141600)])), redirect_stdout(io.StringIO()):
                    with HistoryStore() as history:
                        history.upsert_report(normal(root))
                    target = "group_insight.report_schema.validate_report_schema_2_2" if failing_stage == "validate_report_schema_2_2" else "group_insight.history_store.HistoryStore.upsert_report" if failing_stage == "upsert_report" else "group_insight.cli." + failing_stage
                    def export(_html, image_path, **_kwargs):
                        image_path.write_bytes(b"test-png")
                        return ""
                    with patch.object(cli, "export_report_image", side_effect=export), patch(target, side_effect=RuntimeError("injected stage failure")):
                        with self.assertRaisesRegex(RuntimeError, "injected stage failure"):
                            cli.main()
                    with HistoryStore() as history:
                        self.assertEqual(history.connection.execute("SELECT count(*) FROM reports").fetchone()[0], 1)
                    self.assertEqual(list((root / "reports").glob("*/报告数据/*")), [])


if __name__ == "__main__":
    unittest.main()
