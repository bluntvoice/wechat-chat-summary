import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from group_insight.chunking import chunk_payload
from group_insight.history_store import HistoryStore
from group_insight.llm import build_final_prompts
from group_insight.member_references import (
    member_names_from_stats,
    normalize_member_reference_text,
    resolve_member_reference_text,
)
from group_insight.models import MessageChunk, StructuredMessage
from group_insight.rendering import render_html_report
from group_insight.report_model import repair_final_report
from group_insight.report_schema import build_report_document


class MemberReferenceTests(unittest.TestCase):
    @staticmethod
    def document(member_aliases, text):
        return {
            "schema_version": "2.2",
            "metadata": {
                "chat": {"id": "room@chatroom", "name": "测试群"},
                "period": {"report_date": "2026-09-05"},
            },
            "stats": {"member_aliases": member_aliases},
            "content": {
                "headline": "测试",
                "themes": [{"title": "成员讨论", "summary": text}],
                "topics": [{"title": "详细讨论", "discussion_flow": text}],
            },
        }

    def test_placeholder_renders_full_group_nickname_with_member_style(self):
        full_name = "昵称前半段昵称后半段"
        html = render_html_report(self.document(
            [{"sender_id": "member-a", "sender_name": full_name}],
            "[[user:member-a]]提出建议。",
        ))
        self.assertIn(f'<strong class="topic-member">{full_name}</strong>提出建议', html)

    def test_long_member_name_is_complete_and_never_ellipsized(self):
        full_name = "这是一个需要自然换行但绝对不能被截断或省略的完整群昵称"
        html = render_html_report(self.document(
            [{"sender_id": "member-long", "sender_name": full_name}],
            "[[user:member-long]]补充说明。",
        ))
        self.assertIn(f'<strong class="topic-member">{full_name}</strong>', html)
        self.assertNotIn(f"{full_name[:10]}…", html)

    def test_member_style_is_consistent_across_report_body_sections(self):
        full_name = "城市-行业-Alice"
        token = "[[user:member-a]]"
        document = self.document(
            [{"sender_id": "member-a", "sender_name": full_name}],
            f"{token}分享了方案。",
        )
        document["content"].update({
            "ai_observations": [{"title": "今日观察", "content": f"{token}持续跟进。"}],
            "decisions": [{"content": f"{token}确认结论。"}],
            "open_questions": [{"question": f"{token}提出待确认问题。"}],
            "risk_flags": [{"content": f"{token}提醒注意风险。"}],
            "quotes": [{"speaker": token, "quote": "原话内容"}],
            "conclusion": f"{token}完成收尾。",
        })
        html = render_html_report(document)
        styled = f'<strong class="topic-member">{full_name}</strong>'
        self.assertGreaterEqual(html.count(styled), 8)

    def test_similar_names_prefer_the_longest_exact_member(self):
        names = {"member-short": "小王", "member-long": "小王同学"}
        normalized = normalize_member_reference_text("小王同学提出建议。", names)
        self.assertEqual(normalized, "[[user:member-long]]提出建议。")
        self.assertEqual(resolve_member_reference_text(normalized, names), "小王同学提出建议。")

    def test_common_word_prefix_is_not_treated_as_member(self):
        names = {"member-apple": "苹果"}
        texts = ["今天苹果价格上涨。", "今天苹果手机价格上涨。"]
        for text in texts:
            self.assertEqual(normalize_member_reference_text(text, names), text)
        text = texts[-1]
        html = render_html_report(self.document(
            [{"sender_id": "member-apple", "sender_name": "苹果"}], text
        ))
        self.assertNotIn('<strong class="topic-member">苹果</strong>手机', html)

    def test_chatroom_stat_entry_is_not_treated_as_a_member(self):
        names = member_names_from_stats({
            "member_aliases": [
                {"sender_id": "room@chatroom", "sender_name": "测试群"},
                {"sender_id": "member-a", "sender_name": "城市-行业-Alice"},
            ]
        })
        self.assertNotIn("room@chatroom", names)
        self.assertEqual(normalize_member_reference_text("测试群：今日总结", names), "测试群：今日总结")

    def test_generic_middle_role_is_not_used_as_a_short_member_alias(self):
        names = {"member-a": "深圳-律师-Ellen"}
        self.assertEqual(normalize_member_reference_text("律师表示需要复核。", names), "律师表示需要复核。")

    def test_safe_legacy_suffix_restores_full_group_nickname(self):
        names = {"member-c": "南京-药用耗材-C律师"}
        self.assertEqual(
            resolve_member_reference_text("C律师在凌晨补充。", names),
            "南京-药用耗材-C律师在凌晨补充。",
        )

    def test_duplicate_suffixes_remain_distinct_via_placeholders(self):
        names = {"member-1": "昵称（01）", "member-2": "昵称（02）"}
        text = "[[user:member-1]]与[[user:member-2]]分别补充。"
        html = render_html_report(self.document(
            [{"sender_id": sender_id, "sender_name": name} for sender_id, name in names.items()], text
        ))
        self.assertIn('<strong class="topic-member">昵称（01）</strong>', html)
        self.assertIn('<strong class="topic-member">昵称（02）</strong>', html)

    def test_whitespace_normalized_match_restores_original_full_name(self):
        names = {"member-space": "测试 昵称 ABC"}
        text = "测试昵称ABC分享了方案。"
        normalized = normalize_member_reference_text(text, names)
        self.assertEqual(normalized, "[[user:member-space]]分享了方案。")
        self.assertEqual(resolve_member_reference_text(text, names), "测试 昵称 ABC分享了方案。")

    def test_unique_contextual_short_name_restores_canonical_name(self):
        names = {
            "member-venti": "深圳-港股信披-Venti",
            "member-samantha": "深圳-机器人-涉外法务-Samantha",
        }
        text = "Venti认为需要调整，Samantha老师随后补充。"
        resolved = resolve_member_reference_text(text, names)
        self.assertEqual(
            resolved,
            "深圳-港股信披-Venti认为需要调整，深圳-机器人-涉外法务-Samantha老师随后补充。",
        )

    def test_report_repair_persists_stable_member_reference(self):
        stats = {
            "message_count": 1,
            "participant_count": 1,
            "member_aliases": [{"sender_id": "member-a", "sender_name": "城市-行业-Alice"}],
        }
        report = repair_final_report(
            {"theme_cards": [{"title": "讨论", "summary": "Alice分享了方案。"}], "sections": []},
            "测试群", "2026-09-05 00:00:00", "2026-09-05 23:59:59", stats, [],
        )
        self.assertEqual(report["theme_cards"][0]["summary"], "[[user:member-a]]分享了方案。")

    def test_map_payload_exposes_sender_reference_not_display_name(self):
        message = StructuredMessage(
            id="m1", local_id=1, timestamp=1, time="2026-09-05 09:00",
            sender_username="member-a", sender="城市-行业-Alice", text="测试内容", msg_type="文本",
            chat_id="room@chatroom", chat_name="测试群", table_name="api", metadata={},
        )
        chunk = MessageChunk(
            id="shard-001", index=1, start_ts=1, end_ts=1,
            start_time=message.time, end_time=message.time,
            message_count=1, char_count=4, messages=[message],
        )
        payload = chunk_payload(chunk)
        self.assertEqual(payload["messages"][0]["sender_ref"], "[[user:member-a]]")
        self.assertNotIn("sender", payload["messages"][0])
        self.assertNotIn("sender_name", payload["member_directory"][0])

    def test_final_prompt_does_not_reintroduce_display_names(self):
        stats = {
            "message_count": 1,
            "participant_count": 1,
            "top_speakers": [{"name": "城市-行业-Alice", "message_count": 1}],
            "member_aliases": [{"sender_id": "member-a", "sender_name": "城市-行业-Alice"}],
        }
        _, user_prompt = build_final_prompts(
            "测试群", "2026-09-05 00:00:00", "2026-09-05 23:59:59", stats, [], []
        )
        self.assertNotIn("城市-行业-Alice", user_prompt)
        self.assertIn("[[user:member-a]]", user_prompt)

    def test_history_detail_upgrades_safe_old_plain_reference_in_memory(self):
        document = build_report_document(
            ctx={"username": "room@chatroom", "display_name": "测试群"},
            start_time="2026-09-05 00:00:00", end_time="2026-09-05 23:59:59", version=1,
            stats={
                "message_count": 1, "participant_count": 1,
                "member_aliases": [{"sender_id": "member-a", "sender_name": "城市-行业-Alice"}],
            },
            report={
                "theme_cards": [],
                "sections": [{"id": "topic-a", "title": "讨论", "discussion_flow": "Alice分享了方案。"}],
            },
            resources={"count": 0, "groups": []},
            exports={"json": "a", "html": "b", "png": "c"},
            provider="test", model="test", dry_run=False, chunk_count=1, chunk_plan={},
        )
        with TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "history.sqlite3") as store:
                report_id = store.upsert_report(document)
                detail = store.get_report_detail(report_id)
        topic = next(item for item in detail["modules"] if item["module_key"] == "topics")
        self.assertEqual(topic["content"]["discussion_flow"], "[[user:member-a]]分享了方案。")


if __name__ == "__main__":
    unittest.main()
