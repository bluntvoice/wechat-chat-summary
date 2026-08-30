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


if __name__ == "__main__":
    unittest.main()
