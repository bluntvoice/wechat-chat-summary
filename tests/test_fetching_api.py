from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from group_insight.fetching import (
    fetch_structured_messages,
    get_group_nickname_map,
    require_resolved_report_member_names,
)
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


class FakeCollidingMemberNameClient(FakeMessageClient):
    def list_contact_profiles(self):
        return {
            "wxid_a": {"nickname": "微信网名甲", "remark": "qq465237125", "displayName": "qq465237125"},
            "wxid_b": {"nickname": "微信网名乙", "remark": "私人备注乙", "displayName": "私人备注乙"},
        }

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        base = int(datetime(2026, 8, 28, 9, 0, 0).timestamp())
        rows = (
            ("a", "wxid_a", "qq465237125"),
            ("b", "wxid_b", "qq465237125"),
            ("c", "wxid_c", "chenqianmax"),
            ("d", "wxid_d", "chenqianmax"),
            ("e", "wxid_e", "正常群昵称"),
        )
        for index, (message_id, sender_username, sender_display) in enumerate(rows, 1):
            yield {
                "id": message_id,
                "localId": index,
                "type": 1,
                "createTime": base + index,
                "senderUsername": sender_username,
                "senderDisplayName": sender_display,
                "renderType": "text",
                "content": f"第 {index} 条",
                "isSent": False,
            }


class FakeDelPrefixedMemberNameClient(FakeMessageClient):
    def list_contact_profiles(self):
        return {
            "wxid_del": {
                "nickname": "\x7f\x7f\x7f\x7f",
                "remark": "",
                "displayName": "\x7f\x7f\x7f\x7f",
            }
        }

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        yield {
            "id": "del-name",
            "localId": 1,
            "type": 1,
            "createTime": int(datetime(2026, 9, 2, 9, 0, 0).timestamp()),
            "senderUsername": "wxid_del",
            "senderDisplayName": "\x7f\x7f\x7f\x7f上海-咨询-jenny",
            "renderType": "text",
            "content": "测试",
            "isSent": False,
        }


class FakeCrossMemberBindingClient(FakeMessageClient):
    def list_contact_profiles(self):
        return {
            "wxid_o2thxlr2a2vz12": {
                "nickname": "海那",
                "remark": "",
                "displayName": "海那",
            },
            "zhaozhong8061": {
                "nickname": "赵中",
                "remark": "",
                "displayName": "赵中",
            },
            "wxid_ascii": {
                "nickname": "英文昵称的微信网名",
                "remark": "",
                "displayName": "英文昵称的微信网名",
            },
        }

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        base = int(datetime(2026, 9, 2, 13, 0, 0).timestamp())
        rows = (
            ("a", "wxid_o2thxlr2a2vz12", "zhaozhong8061"),
            ("b", "zhaozhong8061", "赵中"),
            ("c", "wxid_ascii", "hjlbingo"),
        )
        for index, (message_id, sender_username, sender_display) in enumerate(rows, 1):
            yield {
                "id": message_id,
                "localId": index,
                "type": 1,
                "createTime": base + index,
                "senderUsername": sender_username,
                "senderDisplayName": sender_display,
                "renderType": "text",
                "content": f"第 {index} 条",
                "isSent": False,
            }


class FakeLocalSourceRetryClient(FakeCrossMemberBindingClient):
    def __init__(self, base_url="", *args, **kwargs):
        self.base_url = base_url

    def list_accounts(self):
        return {
            "default_account": "account-a",
            "accountInfos": [
                {"account": "account-a", "accountDir": "D:/wcda/output/databases/account-a"}
            ],
        }

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        if self.base_url == "http://127.0.0.1:10493":
            base = int(datetime(2026, 9, 2, 13, 0, 0).timestamp())
            for index, (message_id, sender_username, sender_display) in enumerate(
                (
                    ("a", "wxid_o2thxlr2a2vz12", "海的那边"),
                    ("b", "zhaozhong8061", "赵中"),
                    ("c", "wxid_ascii", "hjlbingo"),
                ),
                1,
            ):
                yield {
                    "id": message_id,
                    "localId": index,
                    "type": 1,
                    "createTime": base + index,
                    "senderUsername": sender_username,
                    "senderDisplayName": sender_display,
                    "renderType": "text",
                    "content": f"第 {index} 条",
                    "isSent": False,
                }
            return
        yield from super().iter_messages(
            username,
            start_ts=start_ts,
            end_ts=end_ts,
            batch_size=batch_size,
        )


class FakeLocalUpstreamService:
    def __init__(self, source_dir, *, output_dir, port):
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.base_url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeEmptyLocalSourceRetryClient(FakeLocalSourceRetryClient):
    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        if self.base_url == "http://127.0.0.1:10493":
            return
        yield from super().iter_messages(
            username,
            start_ts=start_ts,
            end_ts=end_ts,
            batch_size=batch_size,
        )


class FakeRealtimeProfileRepairClient(FakeEmptyLocalSourceRetryClient):
    def list_contact_profiles(self):
        profiles = super().list_contact_profiles()
        profiles.pop("wxid_o2thxlr2a2vz12", None)
        return profiles

    def get_contact_profile(self, username):
        names = {
            "wxid_o2thxlr2a2vz12": "海的那边",
        }
        nickname = names.get(username, "")
        return {"username": username, "nickname": nickname, "displayName": nickname, "remark": ""}


class FakeTrueDuplicateClient(FakeMessageClient):
    def list_contact_profiles(self):
        return {
            "wxid_a": {"nickname": "同名", "displayName": "同名", "remark": ""},
            "wxid_b": {"nickname": "同名", "displayName": "同名", "remark": ""},
        }

    def get_contact_profile(self, username):
        return self.list_contact_profiles().get(username, {})

    def iter_messages(self, username, *, start_ts, end_ts, batch_size):
        base = int(datetime(2026, 9, 2, 13, 0, 0).timestamp())
        for index, account in enumerate(("wxid_b", "wxid_a"), 1):
            yield {
                "id": str(index), "localId": index, "type": 1, "createTime": base + index,
                "senderUsername": account, "senderDisplayName": "同名",
                "renderType": "text", "content": "测试", "isSent": False,
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

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeCollidingMemberNameClient)
    def test_duplicate_display_name_for_two_accounts_falls_back_without_using_remarks(self):
        ctx, messages = fetch_structured_messages("测试群", "2026-08-28", "2026-08-28")
        self.assertEqual(
            [message.sender for message in messages],
            ["微信网名甲", "微信网名乙", "wxid_c", "wxid_d", "正常群昵称"],
        )
        aliases = get_group_nickname_map("room@chatroom")
        self.assertEqual(aliases["wxid_a"], "微信网名甲")
        self.assertEqual(aliases["wxid_b"], "微信网名乙")
        self.assertNotIn("私人备注乙", aliases.values())
        self.assertNotIn("qq465237125", aliases.values())
        self.assertNotIn("chenqianmax", aliases.values())
        self.assertEqual(ctx["unresolved_member_usernames"], ["wxid_c", "wxid_d"])
        with self.assertRaisesRegex(ValueError, "停止生成报告"):
            require_resolved_report_member_names(ctx)

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeDelPrefixedMemberNameClient)
    def test_del_characters_are_removed_from_member_names(self):
        ctx, messages = fetch_structured_messages("测试群", "2026-09-02", "2026-09-02")
        self.assertEqual([message.sender for message in messages], ["上海-咨询-jenny"])
        self.assertNotIn("\x7f", messages[0].sender)
        self.assertEqual(
            get_group_nickname_map("room@chatroom")["wxid_del"],
            "上海-咨询-jenny",
        )
        require_resolved_report_member_names(ctx)

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeCrossMemberBindingClient)
    def test_other_member_account_id_is_not_used_as_group_nickname(self):
        _, messages = fetch_structured_messages("测试群", "2026-09-02", "2026-09-02")
        self.assertEqual([message.sender for message in messages], ["海那", "赵中", "hjlbingo"])
        aliases = get_group_nickname_map("room@chatroom")
        self.assertEqual(aliases["wxid_o2thxlr2a2vz12"], "海那")
        self.assertEqual(aliases["zhaozhong8061"], "赵中")
        self.assertEqual(aliases["wxid_ascii"], "hjlbingo")
        self.assertNotIn("zhaozhong8061", aliases.values())

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeLocalSourceRetryClient)
    @patch("group_insight.local_upstream_service.LocalUpstreamService", FakeLocalUpstreamService)
    def test_nickname_anomaly_retries_with_local_upstream_source_service(self):
        ctx, messages = fetch_structured_messages(
            "测试群",
            "2026-09-02",
            "2026-09-02",
            local_source_dir="D:/wcda-source",
            local_source_port=10493,
        )
        self.assertEqual(ctx["nickname_source"], "local_upstream_branch")
        self.assertTrue(ctx["nickname_anomaly_detected"])
        self.assertTrue(ctx["local_upstream_attempted"])
        self.assertEqual([message.sender for message in messages], ["海的那边", "赵中", "hjlbingo"])

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeLocalSourceRetryClient)
    @patch("group_insight.local_upstream_service.LocalUpstreamService", side_effect=RuntimeError("boom"))
    def test_local_source_failure_keeps_contact_nickname_fallback(self, _service):
        ctx, messages = fetch_structured_messages(
            "测试群",
            "2026-09-02",
            "2026-09-02",
            local_source_dir="D:/wcda-source",
            local_source_port=10493,
        )
        self.assertEqual(ctx["nickname_source"], "local_contact_fallback")
        self.assertTrue(ctx["local_upstream_attempted"])
        self.assertIn("boom", ctx["local_upstream_error"])
        self.assertEqual([message.sender for message in messages], ["海那", "赵中", "hjlbingo"])

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeEmptyLocalSourceRetryClient)
    @patch("group_insight.local_upstream_service.LocalUpstreamService", FakeLocalUpstreamService)
    def test_empty_local_snapshot_never_replaces_primary_messages(self):
        ctx, messages = fetch_structured_messages(
            "测试群",
            "2026-09-02",
            "2026-09-02",
            local_source_dir="D:/wcda-source",
            local_source_port=10493,
        )
        self.assertEqual(ctx["nickname_source"], "local_contact_fallback")
        self.assertIn("未覆盖", ctx["local_upstream_error"])
        self.assertEqual(len(messages), 3)

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeRealtimeProfileRepairClient)
    @patch("group_insight.local_upstream_service.LocalUpstreamService", FakeLocalUpstreamService)
    def test_realtime_profile_repairs_member_after_local_source_cannot_cover_messages(self):
        ctx, messages = fetch_structured_messages(
            "测试群", "2026-09-02", "2026-09-02",
            local_source_dir="D:/wcda-source", local_source_port=10493,
        )
        self.assertEqual(ctx["nickname_source"], "realtime_contact_repair")
        self.assertEqual(ctx["unresolved_member_usernames"], [])
        self.assertEqual(messages[0].sender, "海的那边")

    @patch("group_insight.fetching.WeChatDataAPIClient", FakeTrueDuplicateClient)
    def test_verified_duplicate_nicknames_use_per_report_sequence_numbers(self):
        ctx, messages = fetch_structured_messages("测试群", "2026-09-02", "2026-09-02")
        self.assertEqual(ctx["unresolved_member_usernames"], [])
        self.assertEqual([message.sender for message in messages], ["同名（02）", "同名（01）"])


if __name__ == "__main__":
    unittest.main()
