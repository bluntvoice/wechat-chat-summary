from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.desktop_bridge import _redact_report
from group_insight.history_store import HistoryStore
from group_insight.redaction import REDACTION_NOTICE, delete_report_content, list_redaction_targets, redact_report_document
from group_insight.rendering import render_html_report
from tests.test_history_center import history_document


class SummaryRedactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = history_document(self.root)
        self.document["content"].update(
            one_line_summary="开头保留😀私密片段甲，中间保留，私密片段乙结尾保留。",
            conclusion="公开结尾，结尾私密信息，保留提醒。",
        )
        self.document["content"]["lead_summary"] = self.document["content"]["one_line_summary"]
        self.document["stats"]["word_cloud"] = [{"word": f"独立词条{i:02}", "count": i + 1} for i in range(30)]

    def edit(self, key, text):
        source = next(target["text"] for target in list_redaction_targets(self.document) if target["id"] == key)
        start = source.index(text)
        return {"target_id": key, "start": start, "end": start + len(text), "text": text}

    def redact(self, ids=None, edits=None, document=None, version=2):
        return redact_report_document(document or self.document, ids or [], version=version,
                                      exports={}, text_redactions=edits)

    def test_targets_include_full_text_and_every_keyword_beyond_visible_limit(self):
        targets = {target["id"]: target for target in list_redaction_targets(self.document)}
        self.assertEqual(targets["one_line_summary"]["text"], self.document["content"]["one_line_summary"])
        self.assertIn("conclusion", targets)
        self.assertIn("word_cloud", targets)
        self.assertIn("word_cloud:29", targets)

    def test_multiple_substrings_preserve_context_and_original_without_leaking_metadata(self):
        before = copy.deepcopy(self.document)
        edits = [self.edit("one_line_summary", text) for text in ("私密片段甲", "私密片段乙")]
        edits.append(self.edit("conclusion", "结尾私密信息"))
        result = self.redact(["word_cloud:0", "word_cloud:29"], edits)
        serialized = json.dumps(result, ensure_ascii=False)
        html = render_html_report(result)
        for secret in ("私密片段甲", "私密片段乙", "结尾私密信息", "独立词条00", "独立词条29"):
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, html)
        for retained in ("开头保留😀", "中间保留", "结尾保留", "保留提醒", "独立词条01"):
            self.assertIn(retained, serialized)
            self.assertIn(retained, html)
        self.assertEqual(result["content"]["lead_summary"], result["content"]["one_line_summary"])
        self.assertEqual(self.document, before)
        with HistoryStore(self.root / "history.sqlite3") as history:
            report_id = history.upsert_report(result)
            indexed = " ".join(row[0] for row in history.connection.execute(
                "SELECT body FROM report_search_fts WHERE report_id=?", (report_id,)))
            for secret in ("私密片段甲", "结尾私密信息", "独立词条00", "独立词条29"):
                self.assertNotIn(secret, indexed)

    def test_whole_summaries_and_all_keywords_are_removed(self):
        result = self.redact(["one_line_summary", "conclusion", "word_cloud", "word_cloud:0"])
        self.assertEqual(result["content"]["one_line_summary"], REDACTION_NOTICE)
        self.assertEqual(result["content"]["conclusion"], REDACTION_NOTICE)
        self.assertTrue(all(item["redacted"] for item in result["stats"]["word_cloud"]))
        self.assertNotIn("独立词条", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("群关键词", render_html_report(result))

    def test_overlapping_duplicate_ranges_merge_and_whole_selection_wins(self):
        edit = self.edit("one_line_summary", "私密片段甲")
        overlap = {**edit, "end": edit["end"] + 1, "text": "私密片段甲，"}
        result = self.redact(edits=[overlap, edit, edit])
        self.assertEqual(result["content"]["one_line_summary"], "开头保留😀■■■■■■中间保留，私密片段乙结尾保留。")
        self.assertEqual(self.redact(["one_line_summary"], [edit])["content"]["one_line_summary"], REDACTION_NOTICE)

    def test_displayed_nickname_partial_selection_masks_whole_token_preserves_other_tokens(self):
        self.document["stats"]["member_aliases"] = [
            {"sender_id": "a", "sender_name": "小明同学"}, {"sender_id": "b", "sender_name": "小红同学"}]
        self.document["content"]["one_line_summary"] = "😀[[user:a]]讨论，[[user:b]]补充。\r\n保留下一行"
        edit = self.edit("one_line_summary", "明同")
        result = self.redact(edits=[edit])
        self.assertEqual(result["content"]["one_line_summary"], "😀■■■■讨论，[[user:b]]补充。\r\n保留下一行")
        self.assertIn("小红同学", render_html_report(result))

    def test_two_chinese_characters_become_two_black_squares_in_json_and_html(self):
        self.document["content"]["one_line_summary"] = "下午聊翻墙隐私"
        result = self.redact(edits=[self.edit("one_line_summary", "翻墙")])
        self.assertEqual(result["content"]["one_line_summary"], "下午聊■■隐私")
        self.assertIn('下午聊<span class="redaction-mask">■■</span>隐私', render_html_report(result))
        self.assertNotIn(REDACTION_NOTICE, result["content"]["one_line_summary"])

    def test_unicode_mask_count_and_partial_version_keep_original_character_length(self):
        self.document["content"]["conclusion"] = "保留A😀，结尾"
        first = self.redact(edits=[self.edit("conclusion", "A😀，")])
        self.assertEqual(first["content"]["conclusion"], "保留■■■结尾")
        second = self.redact(document=first, edits=[{
            "target_id": "conclusion", "start": 5, "end": 7, "text": "结尾"}], version=3)
        self.assertEqual(second["content"]["conclusion"], "保留■■■■■")

    def test_invalid_unknown_stale_and_out_of_bounds_ranges_are_rejected(self):
        good = self.edit("one_line_summary", "私密片段甲")
        for changes in ({"target_id": "topics:0"}, {"target_id": []}, {"text": "旧文字"}, {"start": -1},
                        {"start": True}, {"end": 99999}, {"end": good["start"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.redact(edits=[{**good, **changes}])
        with self.assertRaises(ValueError):
            self.redact(["word_cloud:99"])

    def test_legacy_without_optional_fields_and_repeated_partial_versions(self):
        first = self.redact(edits=[self.edit("one_line_summary", "私密片段甲")])
        text = first["content"]["one_line_summary"]
        start = text.index("私密片段乙")
        second = self.redact(document=first, edits=[{"target_id": "one_line_summary", "start": start,
            "end": start + 5, "text": "私密片段乙"}], version=3)
        self.assertNotIn("私密片段", json.dumps(second, ensure_ascii=False))
        self.assertEqual(second["metadata"]["parent_report_id"], first["metadata"]["report_id"])
        self.document["content"].pop("conclusion")
        self.document["stats"].pop("word_cloud")
        self.assertNotIn("conclusion", {target["id"] for target in list_redaction_targets(self.document)})
        self.assertTrue(self.redact(["topics:0"])["content"]["topics"][0]["redacted"])

    def test_bridge_accepts_partial_only_and_mixed_keyword_edits_offline(self):
        source = self.root / "source.json"
        source.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
        source_bytes = source.read_bytes()
        def fake_export(_html, png, **_kwargs):
            png.write_bytes(b"test-png")
            return ""
        with patch.dict(os.environ, {"WECHAT_CHAT_SUMMARY_DATA_DIR": str(self.root / "app")}), \
             patch("group_insight.desktop_bridge.export_report_image", side_effect=fake_export), \
             patch("group_insight.desktop_bridge.fetch_structured_messages", side_effect=AssertionError("source called")), \
             patch("group_insight.desktop_bridge._generate", side_effect=AssertionError("AI called")):
            for ids in ([], ["word_cloud:29"]):
                result = _redact_report({"export_root": str(self.root / "exports")}, {
                    "json_path": str(source), "target_ids": ids,
                    "text_redactions": [self.edit("one_line_summary", "私密片段甲")],
                })
                document = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
                self.assertNotIn("私密片段甲", json.dumps(document, ensure_ascii=False))
                self.assertTrue(Path(result["png_path"]).is_file())
                with HistoryStore() as history:
                    self.assertIsNotNone(history.get_report_detail(result["report_id"]))
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_member_card_redaction_and_deletion_keep_names_in_visible_topics_and_quotes(self):
        self.document["stats"]["member_aliases"] = [{"sender_id": "alice", "sender_name": "小明同学"}]
        self.document["stats"]["top_speakers"] = [{"name": "小明同学", "message_count": 10}]
        self.document["content"]["members"] = [{"name": "[[user:alice]]", "insight": "私密成员观察"}]
        first = self.document["content"]["topics"][0]
        first["discussion_flow"] = "[[user:alice]]讨论敏感话题。"
        second = copy.deepcopy(first)
        second.update(id="visible-topic", title="公开话题", discussion_flow="[[user:alice]]分享公开资料。",
                      quotes=[{"speaker": "[[user:alice]]", "quote": "公开原话"}])
        self.document["content"]["topics"].append(second)
        for operation in (redact_report_document, delete_report_content):
            with self.subTest(operation=operation.__name__):
                result = operation(self.document, ["members:0", "topics:0"], version=2, exports={})
                self.assertEqual(result["stats"]["member_aliases"], self.document["stats"]["member_aliases"])
                self.assertEqual(result["stats"]["top_speakers"], [])
                html = render_html_report(result)
                self.assertIn('class="topic-member">小明同学</strong>', html)
                self.assertNotIn("群成员", html)
                self.assertNotIn("私密成员观察", json.dumps(result, ensure_ascii=False))

    def test_member_alias_is_removed_only_when_no_visible_reference_needs_it(self):
        self.document["stats"]["member_aliases"] = [{"sender_id": "alice", "sender_name": "独有成员名"}]
        self.document["content"]["members"] = [{"name": "[[user:alice]]", "insight": "私密观察"}]
        self.document["content"]["topics"][0]["discussion_flow"] = "[[user:alice]]讨论私密内容。"
        result = self.redact(["members:0", "topics:0"])
        self.assertEqual(result["stats"]["member_aliases"], [])
        self.assertNotIn("独有成员名", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
