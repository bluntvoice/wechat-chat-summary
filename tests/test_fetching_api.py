from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from group_insight.fetching import fetch_structured_messages, get_group_nickname_map
from group_insight.wechat_data_api import ChatReference


class FakeMessageClient:
    def __init__(self, *args, **kwargs):
        pass

    def resolve_chat(self, chat_ref):
        return ChatReference(
            username="room@chatroom",
            display_name=chat_ref,
            is_group=True,
            account="account-a",
            source="native",
        )

    def list_contact_profiles(self):
        return {}

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        base = int(datetime(2026, 8, 28, 9, 0, 0).timestamp())
        yield {
            "id": "message-2",
            "localId": 2,
            "type": 1,
            "createTime": base + 60,
            "senderUsername": "wxid_b",
            "senderDisplayName": "小乙",
            "renderType": "text",
            "content": "第二条",
            "isSent": False,
        }
        yield {
            "id": "message-1",
            "localId": 1,
            "type": 1,
            "createTime": base,
            "senderUsername": "wxid_a",
            "senderDisplayName": "小甲",
            "renderType": "text",
            "content": "第一条",
            "isSent": False,
        }


class FakeLinkClient(FakeMessageClient):
    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        yield {
            "id": "link-1", "localId": 3, "type": 21474836529,
            "createTime": int(datetime(2026, 8, 28, 10, 0, 0).timestamp()),
            "senderUsername": "wxid_a", "senderDisplayName": "小甲",
            "renderType": "link", "content": "链接摘要", "title": "示例资料",
            "url": "https://example.com/document", "isSent": False,
        }


class FakeMemberNameClient(FakeMessageClient):
    def list_contact_profiles(self):
        return {
            "wxid_remarked": {"nickname": "微信网名", "remark": "我的私人备注", "displayName": "我的私人备注"},
            "wxid_group": {"nickname": "微信网名二", "remark": "另一条私人备注", "displayName": "另一条私人备注"},
        }

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        base = int(datetime(2026, 8, 28, 9, 0, 0).timestamp())
        yield {
            "id": "remarked", "localId": 1, "type": 1, "createTime": base,
            "senderUsername": "wxid_remarked", "senderDisplayName": "我的私人备注",
            "renderType": "text", "content": "第一条", "isSent": False,
        }
        yield {
            "id": "group", "localId": 2, "type": 1, "createTime": base + 1,
            "senderUsername": "wxid_group", "senderDisplayName": "群内昵称",
            "renderType": "text", "content": "第二条", "isSent": False,
        }


class FetchingAPITests(unittest.TestCase):
    @patch("group_insight.fetching.WeChatDataAPIClient", FakeMessageClient)
    def test_api_messages_are_normalized_and_sorted(self):
        ctx, messages = fetch_structured_messages(
            "测试群",
            "2026-08-28 00:00:00",
            "2026-08-28 23:59:59",
        )
        self.assertEqual(ctx["data_source"], "wechat_data_analysis_api")
        self.assertEqual([item.id for item in messages], ["message-1", "message-2"])
        self.assertEqual(messages[0].sender, "小甲")
        self.assertEqual(messages[0].msg_type, "文本")
        self.assertEqual(get_group_nickname_map("room@chatroom")["wxid_a"], "小甲")

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeLinkClient)
    def test_high_bit_wechat_type_uses_rendered_link_fields(self):
        _, messages = fetch_structured_messages("测试群", "2026-08-28", "2026-08-28")
        self.assertEqual(messages[0].metadata["rich_kind"], "link_card")
        self.assertEqual(messages[0].metadata["url"], "https://example.com/document")
        self.assertIn("示例资料", messages[0].text)

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeMemberNameClient)
    def test_member_name_prefers_group_nickname_then_wechat_nickname_without_remark(self):
        _, messages = fetch_structured_messages("测试群", "2026-08-28", "2026-08-28")
        self.assertEqual([message.sender for message in messages], ["微信网名", "群内昵称"])
        self.assertNotIn("我的私人备注", get_group_nickname_map("room@chatroom").values())


if __name__ == "__main__":
    unittest.main()
