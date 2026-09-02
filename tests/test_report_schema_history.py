from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.history_store import HistoryStore
from group_insight.llm import build_final_prompts
from group_insight.models import StructuredMessage
from group_insight.report_model import dedupe_sections, repair_final_report
from group_insight.report_schema import build_report_document, upgrade_legacy_report
from group_insight.redaction import REDACTION_NOTICE, list_redaction_targets, redact_report_document
from group_insight.rendering import render_html_report
from group_insight.resources import build_resource_catalog, extract_resources
from group_insight.stats import extract_word_cloud_terms


def message(message_id: str, text: str, metadata=None) -> StructuredMessage:
    return StructuredMessage(
        id=message_id, local_id=1, timestamp=1788134400, time="2026-08-31 08:00:00",
        sender_username="wxid_a", sender="小甲", text=text, msg_type="链接/文件" if metadata else "文本",
        chat_id="room@chatroom", chat_name="测试群", table_name="api", metadata=metadata or {},
    )


class ReportSchemaHistoryTests(unittest.TestCase):
    def test_redaction_targets_resolve_member_placeholders(self):
        document = {
            "metadata": {"period": {"report_date": "2026-08-31"}},
            "stats": {
                "member_aliases": [
                    {"sender_id": "wxid_a", "sender_name": "群昵称甲"},
                ]
            },
            "content": {
                "members": [
                    {"name": "[[user:wxid_a]]", "insight": "活跃成员"},
                    {"name": "[[user:unknown]]", "insight": "未知成员"},
                ]
            },
        }
        previews = [item["preview"] for item in list_redaction_targets(document)]
        self.assertEqual(previews, ["群昵称甲", "群成员"])
        self.assertNotIn("[[user:", " ".join(previews))

    def test_resources_merge_links_and_files_under_one_topic(self):
        messages = [
            message("m1", "资料 https://example.com/a"),
            message("m2", "[文件] 清单.xlsx", {"rich_kind": "file_card", "title": "清单.xlsx", "file_ext": "xlsx"}),
        ]
        resources = extract_resources(messages)
        catalog = build_resource_catalog(resources, [{"topic": "项目资料", "resource_ids": [item["id"] for item in resources]}], [])
        self.assertEqual(catalog["count"], 2)
        self.assertEqual({item["type"] for item in catalog["groups"][0]["items"]}, {"link", "file"})

    def test_resource_assignment_requires_semantic_match(self):
        resources = [
            {"id": "r1", "type": "file", "title": "清关资料清单.xlsx", "context_summary": "美国尾程报关材料"},
            {"id": "r2", "type": "link", "title": "周末徒步路线", "context_summary": "郊外爬山"},
        ]
        topics = [{
            "id": "topic-clearance", "title": "美国尾程清关",
            "discussion_flow": "讨论报关风险和资料准备。", "resource_ids": ["r1", "r2"],
        }]
        catalog = build_resource_catalog(resources, None, topics)
        assigned = {group["topic_id"]: [item["id"] for item in group["items"]] for group in catalog["groups"]}
        self.assertEqual(assigned["topic-clearance"], ["r1"])
        self.assertEqual(assigned["other"], ["r2"])
        document = build_report_document(
            ctx={"username": "room", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={}, report={"sections": topics}, resources=catalog,
            exports={"json": "a", "html": "b", "png": "c"}, provider="deepseek", model="test",
            dry_run=False, chunk_count=1, chunk_plan={},
        )
        self.assertEqual(document["content"]["topics"][0]["resource_ids"], ["r1"])

    def test_redpacket_links_are_not_extracted_as_resources(self):
        messages = [
            message("m1", "https://wxapp.tenpay.com/mmpayhb/wxhb_personalreceive?sendid=123"),
            message("m2", "https://wx.gtimg.com/hongbao/1800/hb.png"),
            message("m3", "资料 https://example.com/report"),
        ]
        resources = extract_resources(messages)
        self.assertEqual([item["url"] for item in resources], ["https://example.com/report"])

    @patch("group_insight.stats.jieba", None)
    def test_word_cloud_deduplicates_long_phrases_and_fragments(self):
        messages = [message(f"m{index}", "祝雯律案源滚滚") for index in range(12)]
        terms = extract_word_cloud_terms(messages)
        words = {item["word"] for item in terms}
        self.assertIn("祝雯律案源滚滚", words)
        self.assertTrue({"祝雯", "雯律", "律案", "案源", "源滚"}.isdisjoint(words))

    def test_rendering_deduplicates_members_after_alias_resolution(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={
                "message_count": 2, "effective_char_count": 10, "participant_count": 1,
                "top_speakers": [
                    {"rank": 1, "name": "发言第一", "message_count": 12},
                    {"rank": 2, "name": "发言第二", "message_count": 6},
                ],
                "member_aliases": [
                    {"sender_id": "wxid_a", "sender_name": "同一群昵称"},
                    {"sender_id": "wxid_b", "sender_name": "同一群昵称"},
                ],
            },
            report={
                "one_line_summary": "摘要", "theme_cards": [], "sections": [],
                "participant_insights": [
                    {"name": "[[user:wxid_a]]", "insight": "第一条观察"},
                    {"name": "[[user:wxid_b]]", "insight": "第二条观察"},
                ],
            },
            resources={"count": 0, "groups": []},
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False,
            chunk_count=1, chunk_plan={},
        )
        html = render_html_report(document)
        self.assertEqual(html.count("<strong>同一群昵称</strong>"), 1)
        self.assertIn("第一条观察", html)
        self.assertNotIn("第二条观察", html)
        self.assertIn(".member-list li{display:flex;align-items:center", html)
        self.assertIn(".rank{display:inline-flex;align-items:center;justify-content:center", html)
        self.assertIn("background:#dff0df", html)
        self.assertIn("<h2>今日活跃情况</h2>", html)
        self.assertIn("<h3>发言排行</h3>", html)
        self.assertIn("<strong>发言第一</strong>", html)
        self.assertIn("<span class=\"speaker-count\">12 条</span>", html)

    def test_png_export_keeps_the_same_complete_modules_as_html(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={"message_count": 2, "effective_char_count": 10, "participant_count": 1},
            report={
                "one_line_summary": "摘要", "theme_cards": [],
                "sections": [{
                    "title": "完整讨论", "discussion_flow": "PNG 也必须保留这段讨论脉络",
                    "quotes": [{
                        "speaker": "小甲", "time": "2026-08-31 09:30",
                        "quote": "PNG 也必须保留引用原话", "why_it_matters": "这是原话保留原因",
                    }],
                }],
            },
            resources={"count": 0, "groups": []},
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False,
            chunk_count=1, chunk_plan={},
        )
        html = render_html_report(document)
        self.assertIn("PNG 也必须保留这段讨论脉络", html)
        self.assertIn("PNG 也必须保留引用原话", html)
        self.assertIn("这是原话保留原因", html)
        self.assertNotIn("body.export-png .html-detail", html)
        self.assertNotIn("resource-group:nth-of-type", html)
        self.assertNotIn("new URLSearchParams", html)

    def test_topic_title_precedes_plain_time_and_member_names_are_highlighted(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={
                "message_count": 2,
                "effective_char_count": 10,
                "participant_count": 2,
                "member_aliases": [
                    {"sender_id": "wxid_a", "sender_name": "小甲"},
                    {"sender_id": "wxid_b", "sender_name": "小乙"},
                ],
            },
            report={
                "one_line_summary": "摘要",
                "theme_cards": [],
                "sections": [{
                    "id": "topic-project",
                    "title": "项目安排",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "time_ranges": [{"start": "09:00", "end": "10:00"}],
                    "discussion_flow": "[[user:wxid_a]] 请 [[user:wxid_b]] 确认安排，小甲随后补充说明。",
                    "resource_ids": ["r1"],
                }],
            },
            resources={
                "count": 1,
                "groups": [{
                    "topic_id": "topic-project",
                    "topic": "项目安排",
                    "summary": "相关资料",
                    "items": [{
                        "id": "r1", "type": "file", "title": "清单.xlsx",
                        "sender_id": "wxid_a", "sender": "小甲", "sent_at": "09:30",
                    }],
                }],
            },
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False,
            chunk_count=1, chunk_plan={},
        )
        html = render_html_report(document)
        self.assertLess(html.index("<h3>项目安排</h3>"), html.index('class="topic-time"'))
        self.assertIn('<p class="topic-time">09:00 — 10:00</p>', html)
        self.assertNotIn("time-chip", html)
        self.assertGreaterEqual(html.count('<strong class="topic-member">小甲</strong>'), 2)
        self.assertIn('<strong class="topic-member">小乙</strong>', html)
        self.assertIn('<strong class="topic-member">小甲</strong>随后补充说明', html)
        self.assertIn(".topic-member{color:#3478bd;font-weight:800}", html)

    def test_plain_duplicate_member_names_are_not_highlighted_ambiguously(self):
        document = {
            "schema_version": "2.2",
            "metadata": {
                "chat": {"id": "room@chatroom", "name": "测试群"},
                "period": {"report_date": "2026-08-31"},
            },
            "stats": {
                "member_aliases": [
                    {"sender_id": "wxid_a", "sender_name": "同名成员"},
                    {"sender_id": "wxid_b", "sender_name": "同名成员"},
                ]
            },
            "content": {
                "headline": "测试",
                "topics": [{"title": "讨论", "discussion_flow": "同名成员补充了意见。"}],
            },
        }
        html = render_html_report(document)
        self.assertIn("同名成员补充了意见", html)
        self.assertNotIn('<strong class="topic-member">同名成员</strong>', html)

    def test_jokes_do_not_become_serious_items(self):
        report = repair_final_report(
            {
                "lead_summary": "今天讨论项目安排。",
                "sections": [{
                    "id": "topic-project", "title": "项目安排", "discussion_flow": "讨论正式排期。",
                    "outcome": {"content": "明天收购月球", "tone": "joke", "confidence": 0.99},
                    "action_items": [{"task": "认真提交清单", "tone": "formal", "confidence": 0.9}],
                    "open_questions": [
                        {"question": "明天公司是不是要倒闭了哈哈哈", "tone": "teasing", "confidence": 0.95},
                        {"question": "正式排期是否确认", "tone": "formal", "confidence": 0.9},
                        {"question": "旧报告兼容问题"},
                    ],
                    "risk_flags": [{"content": "只是调侃", "tone": "sarcasm", "confidence": 0.8}],
                }],
                "light_moments": [{"content": "收购月球是群友玩笑", "tone": "joke"}],
            },
            "测试群", "2026-08-31 00:00:00", "2026-08-31 23:59:59",
            {"message_count": 2, "effective_message_count": 2, "participant_count": 1}, [],
        )
        topic = report["sections"][0]
        self.assertIsNone(topic["outcome"])
        self.assertEqual(topic["risk_flags"], [])
        self.assertEqual(len(topic["action_items"]), 1)
        self.assertEqual(
            [item["question"] for item in topic["open_questions"]],
            ["正式排期是否确认", "旧报告兼容问题"],
        )
        self.assertEqual(len(report["light_moments"]), 1)

    def test_empty_outcome_placeholders_are_not_rendered(self):
        topics = dedupe_sections([
            {
                "id": "topic-a", "title": "仅交换观点", "discussion_flow": "大家比较了不同做法。",
                "outcome": {"content": "暂无结论。", "tone": "formal", "confidence": 0.95},
            }
        ])
        self.assertIsNone(topics[0]["outcome"])
        document = {
            "schema_version": "2.2", "metadata": {"chat": {}, "period": {}}, "stats": {},
            "content": {"headline": "测试", "topics": topics},
        }
        html = render_html_report(document)
        self.assertNotIn("暂无结论", html)
        self.assertNotIn("讨论落点", html)

    def test_report_document_is_saved_to_sqlite_without_raw_messages(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={
                "message_count": 3, "effective_message_count": 2, "effective_char_count": 20, "participant_count": 1,
                "top_speakers": [{"rank": 1, "name": "小甲", "message_count": 3}],
                "known_speakers": ["小甲"],
                "member_aliases": [{"sender_id": "wxid_a", "sender_name": "小甲", "mention_token": "[[user:wxid_a]]"}],
            },
            report={"one_line_summary": "今天围绕项目清单展开讨论。", "theme_cards": [], "sections": []},
            resources={"count": 0, "groups": []}, exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={"strategy": "map-reduce"},
        )
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(path) as store:
                report_id = store.upsert_report(document)
                self.assertEqual(store.summarized_chat_ids(), ["room@chatroom"])
                row = store.connection.execute("SELECT schema_version, json_path FROM reports WHERE report_id=?", (report_id,)).fetchone()
                self.assertEqual(row["schema_version"], "2.2")
                self.assertEqual(row["json_path"], "a.json")
            self.assertNotIn("完整原始聊天", path.read_bytes().decode("utf-8", errors="ignore"))

    def test_redaction_creates_detail_free_new_version(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={"message_count": 3, "effective_message_count": 2, "effective_char_count": 20, "participant_count": 1},
            report={
                "one_line_summary": "当日摘要。",
                "theme_cards": [{"title": "敏感热点", "summary": "热点总结正文"}],
                "sections": [{"title": "敏感话题", "summary": "不能进入屏蔽版", "start_time": "09:00", "end_time": "09:30"}],
                "ai_observations": [{"title": "敏感观察", "content": "不能进入观察屏蔽版"}],
                "participant_insights": [{"name": "小甲", "insight": "参与人员观察"}],
                "light_moments": [{"content": "不会进入对外报告"}],
            },
            resources={
                "count": 1,
                "groups": [{"topic_id": "g1", "topic": "资料", "summary": "资料说明", "items": [{"id": "r1", "type": "link", "title": "私密链接", "url": "https://example.com", "sender": "小乙", "sent_at": "2026-08-31 10:00:00", "context_summary": "链接上下文"}]}],
            },
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={"strategy": "map-reduce"},
        )
        target_ids = {item["id"] for item in list_redaction_targets(document)}
        self.assertIn("topics:0", target_ids)
        self.assertIn("ai_observations:0", target_ids)
        self.assertIn("resources:0:0", target_ids)
        self.assertNotIn("light_moments", document["content"])
        redacted = redact_report_document(
            document,
            ["topics:0", "ai_observations:0", "members:0", "resources:0:0"],
            version=2,
            exports={"json": "b.json", "html": "b.html", "png": "b.png"},
        )
        serialized = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn("不能进入屏蔽版", serialized)
        self.assertNotIn("私密链接", serialized)
        self.assertNotIn("小乙", serialized)
        self.assertNotIn("参与人员观察", serialized)
        self.assertNotIn("不能进入观察屏蔽版", serialized)
        self.assertNotIn("小甲", serialized)
        self.assertIn(REDACTION_NOTICE, serialized)
        self.assertEqual(redacted["metadata"]["version"], 2)
        self.assertEqual(document["content"]["topics"][0]["title"], "敏感话题")
        html = render_html_report(redacted)
        self.assertIn(REDACTION_NOTICE, html)
        self.assertNotIn("不能进入屏蔽版", html)

        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as store:
                report_id = store.upsert_report(redacted)
                count = store.connection.execute(
                    "SELECT COUNT(*) FROM report_redactions WHERE report_id=?", (report_id,)
                ).fetchone()[0]
                self.assertEqual(count, 4)

    def test_nested_topic_detail_can_be_redacted_without_hiding_topic(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={"message_count": 3, "effective_char_count": 20, "participant_count": 1},
            report={
                "one_line_summary": "当日摘要。", "theme_cards": [],
                "sections": [{
                    "id": "topic-a", "title": "保留话题", "discussion_flow": "保留讨论脉络。",
                    "outcome": {"content": "敏感讨论落点", "tone": "formal", "confidence": 0.9},
                    "open_questions": [{"question": "敏感开放问题", "tone": "formal", "confidence": 0.9}],
                }],
            },
            resources={"count": 0, "groups": []}, exports={"json": "a", "html": "b", "png": "c"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={},
        )
        targets = {item["id"] for item in list_redaction_targets(document)}
        self.assertIn("topics:0:outcome", targets)
        self.assertIn("topics:0:open_questions:0", targets)
        redacted = redact_report_document(
            document, ["topics:0:outcome", "topics:0:open_questions:0"], version=2,
            exports={"json": "d", "html": "e", "png": "f"},
        )
        serialized = json.dumps(redacted, ensure_ascii=False)
        self.assertIn("保留话题", serialized)
        self.assertIn("保留讨论脉络", serialized)
        self.assertNotIn("敏感讨论落点", serialized)
        self.assertNotIn("敏感开放问题", serialized)
        self.assertGreaterEqual(render_html_report(redacted).count(REDACTION_NOTICE), 2)

    def test_cross_time_sections_with_same_topic_id_are_merged(self):
        topics = dedupe_sections(
            [
                {
                    "id": "topic-project",
                    "title": "项目安排",
                    "time_ranges": [{"start": "2026-08-31 09:00", "end": "2026-08-31 09:30"}],
                    "discussion_flow": "上午提出项目排期。",
                    "action_items": [{"task": "先确认清单", "tone": "formal", "confidence": 0.9}],
                },
                {
                    "id": "topic-project",
                    "title": "项目安排",
                    "time_ranges": [{"start": "2026-08-31 16:00", "end": "2026-08-31 16:20"}],
                    "discussion_flow": "下午补充了交付顺序。",
                    "outcome": {"content": "先完成清单，再分批交付。", "tone": "formal", "confidence": 0.9},
                },
            ]
        )
        self.assertEqual(len(topics), 1)
        self.assertEqual(len(topics[0]["time_ranges"]), 2)
        self.assertIn("上午提出项目排期", topics[0]["discussion_flow"])
        self.assertIn("下午补充了交付顺序", topics[0]["discussion_flow"])
        self.assertEqual(topics[0]["outcome"]["content"], "先完成清单，再分批交付。")
        self.assertEqual(len(topics[0]["action_items"]), 1)
        self.assertNotIn("key_points", topics[0])
        self.assertNotIn("turning_points", topics[0])

    def test_report_uses_content_first_order_and_embeds_related_details(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-08-31 00:00:00", end_time="2026-08-31 23:59:59", version=1,
            stats={
                "message_count": 8, "effective_char_count": 120, "participant_count": 2,
                "top_speakers": [{"name": "小甲", "message_count": 5}],
                "word_cloud": [{"word": "排期", "count": 5}],
                "time_segment_breakdown": [{"label": "上午", "count": 5}],
            },
            report={
                "one_line_summary": "今天确认项目排期。",
                "theme_cards": [{"title": "排期", "summary": "项目进入交付安排阶段。"}],
                "sections": [{
                    "id": "topic-project", "title": "项目排期",
                    "time_ranges": [{"start": "09:00", "end": "09:30"}, {"start": "16:00", "end": "16:20"}],
                    "discussion_flow": "先提出清单，再补充交付顺序。",
                    "outcome": {"content": "分批交付。", "tone": "formal", "confidence": 0.9},
                    "quotes": [{"speaker": "小甲", "quote": "先把清单定下来。"}],
                    "action_items": [{"task": "整理最终清单", "tone": "formal", "confidence": 0.9}],
                }],
                "ai_observations": [{"title": "讨论特点", "content": "讨论由问题确认逐步转向执行安排。"}],
                "conclusion": "项目安排已进入执行阶段。",
            },
            resources={
                "count": 1,
                "groups": [{
                    "topic_id": "topic-project", "topic": "项目排期", "summary": "相关资料",
                    "items": [{"id": "r1", "type": "link", "title": "项目清单", "url": "https://example.com/list"}],
                }],
            },
            exports={"json": "a.json", "html": "a.html", "png": "a.png"},
            provider="deepseek", model="deepseek-v4-flash", dry_run=False, chunk_count=1, chunk_plan={},
        )
        html = render_html_report(document)
        self.assertEqual(document["schema_version"], "2.2")
        self.assertNotIn("key_points", document["content"]["topics"][0])
        self.assertNotIn("turning_points", document["content"]["topics"][0])
        self.assertNotIn("decisions", document["content"])
        labels = ["今日速览", "今日主要话题", "AI 今日观察", "今日活跃情况", "报告结尾"]
        positions = [html.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("先提出清单，再补充交付顺序。", html)
        self.assertIn("先把清单定下来。", html)
        self.assertIn("整理最终清单", html)
        self.assertIn("项目清单", html)
        self.assertNotIn("详细讨论脉络", html)
        self.assertNotIn("今日有趣内容", html)
        self.assertNotIn("最早消息", html)
        self.assertNotIn("最晚消息", html)

    def test_schema_20_document_remains_readable_without_reinterpretation(self):
        payload = {
            "schema_version": "2.0",
            "metadata": {"chat": {"id": "room", "name": "旧报告"}, "period": {"report_date": "2026-08-30"}},
            "stats": {},
            "content": {"headline": "旧报告", "one_line_summary": "旧摘要", "themes": [], "topics": []},
        }
        self.assertIs(upgrade_legacy_report(payload), payload)
        self.assertIn("旧摘要", render_html_report(payload))

    def test_schema_21_document_remains_readable_without_reinterpretation(self):
        payload = {
            "schema_version": "2.1",
            "metadata": {"chat": {"id": "room", "name": "旧报告"}, "period": {"report_date": "2026-08-30"}},
            "stats": {},
            "content": {
                "headline": "旧报告", "one_line_summary": "2.1 旧摘要", "themes": [],
                "topics": [{
                    "id": "topic-old", "title": "旧话题", "discussion_flow": "旧版讨论仍可展示。",
                    "result": {"status": "concluded", "summary": "旧版结论仍可展示。"},
                }],
            },
        }
        self.assertIs(upgrade_legacy_report(payload), payload)
        html = render_html_report(payload)
        self.assertIn("旧版讨论仍可展示", html)
        self.assertIn("旧版结论仍可展示", html)

    def test_final_prompt_requires_semantic_topics_and_internal_only_light_moments(self):
        system_prompt, _ = build_final_prompts(
            "测试群", "2026-08-31 00:00:00", "2026-08-31 23:59:59", {}, [], []
        )
        self.assertIn("同一话题上午出现、下午继续时必须合并", system_prompt)
        self.assertIn("time_ranges", system_prompt)
        self.assertIn("discussion_flow", system_prompt)
        self.assertIn("light_moments 仅用于内部过滤", system_prompt)
        self.assertIn("ai_observations", system_prompt)
        self.assertIn("resource_ids", system_prompt)
        self.assertIn("时间相邻只是弱线索", system_prompt)
        self.assertIn("暂无结论", system_prompt)


if __name__ == "__main__":
    unittest.main()
