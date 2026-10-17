from __future__ import annotations

import unittest

from group_insight.report_model import dedupe_sections, repair_final_report
from group_insight.report_schema import build_report_document, validate_report_schema_2_2
from group_insight.rendering import render_html_report


class FullReportTextTests(unittest.TestCase):
    def test_full_text_survives_cleaning_merge_document_schema_and_html(self):
        first = "起因与主要观点。" * 100 + "第一段完整收尾。"
        second = "不同成员的补充说明。" * 400 + "第二段完整收尾。"
        summary = "完整主题摘要。" * 70 + "摘要收尾。"
        observation = "观察与解释。" * 100 + "观察收尾。"
        quote = "成员的原始表达。" * 60 + "原话收尾。"
        question = "尚待确认的问题。" * 60 + "问题收尾。"
        sections = [
            {"id": "topic-a", "title": "完整话题", "discussion_flow": first,
             "quotes": [{"quote": quote}], "open_questions": [{"question": question}]},
            {"id": "topic-a", "title": "完整话题", "discussion_flow": second},
        ]
        expected = first + "\n" + second
        self.assertEqual(dedupe_sections(sections)[0]["discussion_flow"], expected)
        report = repair_final_report({
            "sections": sections, "theme_cards": [{"title": "主题", "summary": summary}],
            "one_line_summary": "完整的一句话。", "lead_summary": observation * 8,
            "ai_observations": [{"title": "今日观察", "content": observation}],
            "conclusion": observation,
        }, chat_name="测试群", start_time="2026-10-17 00:00:00", end_time="2026-10-17 23:59:59",
            stats={"message_count": 100}, bundles=[])
        self.assertEqual(report["sections"][0]["discussion_flow"], expected)
        self.assertEqual(report["sections"][0]["quotes"][0]["quote"], quote)
        self.assertEqual(report["sections"][0]["open_questions"][0]["question"], question)
        self.assertEqual(report["theme_cards"][0]["summary"], summary)
        self.assertEqual(report["ai_observations"][0]["content"], observation)
        document = build_report_document(
            ctx={"username": "test@chatroom", "display_name": "测试群"},
            start_time="2026-10-17 00:00:00", end_time="2026-10-17 23:59:59", version=1,
            stats={}, report=report, resources={"count": 0, "groups": []}, exports={},
            provider="test", model="test", dry_run=True, chunk_count=1, chunk_plan={},
        )
        self.assertEqual(document["content"]["topics"][0]["discussion_flow"], expected)
        self.assertEqual(document["content"]["lead_summary"], observation * 8)
        self.assertEqual(document["content"]["conclusion"], observation)
        validate_report_schema_2_2(document)
        html = render_html_report(document)
        for ending in ["第一段完整收尾。", "第二段完整收尾。", "摘要收尾。", "观察收尾。", "原话收尾。", "问题收尾。"]:
            self.assertIn(ending, html)


if __name__ == "__main__":
    unittest.main()
