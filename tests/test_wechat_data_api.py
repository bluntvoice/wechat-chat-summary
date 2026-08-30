from __future__ import annotations

import unittest

from group_insight.wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError


class FakeClient(WeChatDataAPIClient):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = []

    def _request(self, path, params=None):
        self.calls.append((path, params or {}))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


class WeChatDataAPIClientTests(unittest.TestCase):
    def test_resolve_chat_by_exact_name(self):
        client = FakeClient(
            [
                {
                    "account": "account-a",
                    "source": "native",
                    "sessions": [
                        {"username": "room@chatroom", "name": "测试群", "isGroup": True},
                        {"username": "wxid_friend", "name": "测试群", "isGroup": False},
                    ],
                }
            ]
        )
        chat = client.resolve_chat("测试群")
        self.assertEqual(chat.username, "room@chatroom")
        self.assertEqual(chat.display_name, "测试群")
        self.assertTrue(chat.is_group)

    def test_message_pages_are_filtered_and_stop_after_start(self):
        client = FakeClient(
            [
                {
                    "hasMore": True,
                    "messages": [
                        {"id": "m3", "createTime": 300},
                        {"id": "m2", "createTime": 250},
                    ],
                },
                {
                    "hasMore": True,
                    "messages": [
                        {"id": "m1", "createTime": 200},
                        {"id": "m0", "createTime": 100},
                    ],
                },
            ]
        )
        rows = list(client.iter_messages("room@chatroom", start_ts=150, end_ts=260, batch_size=2))
        self.assertEqual([row["id"] for row in rows], ["m2", "m1"])
        self.assertEqual(client.calls[1][1]["offset"], 2)

    def test_resolve_chat_falls_back_to_group_contacts(self):
        client = FakeClient(
            [
                {"account": "account-a", "source": "native", "sessions": []},
                {
                    "account": "account-a",
                    "source": "native",
                    "contacts": [
                        {
                            "username": "room@chatroom",
                            "nickname": "不在最近会话的群",
                            "displayName": "不在最近会话的群",
                            "type": "group",
                        }
                    ],
                },
            ]
        )
        chat = client.resolve_chat("不在最近会话的群")
        self.assertEqual(chat.username, "room@chatroom")
        self.assertEqual(chat.display_name, "不在最近会话的群")
        self.assertEqual(client.calls[1][0], "/api/chat/contacts")

    def test_repeated_page_is_rejected(self):
        page = {"hasMore": True, "messages": [{"id": "same", "createTime": 300}]}
        client = FakeClient([page, page])
        with self.assertRaises(WeChatDataAPIError):
            list(client.iter_messages("room@chatroom", start_ts=100, end_ts=400, batch_size=1))


if __name__ == "__main__":
    unittest.main()
