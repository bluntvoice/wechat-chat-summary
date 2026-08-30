from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from group_insight.models import MessageChunk, StructuredMessage
from group_insight.pipeline import run_map_stage


class PipelinePrivacyTests(unittest.TestCase):
    def test_map_stage_does_not_persist_raw_message_input(self) -> None:
        message = StructuredMessage(
            id="m1",
            local_id=1,
            timestamp=1_787_859_600,
            time="2026-08-30 12:00:00",
            sender_username="wxid_sender",
            sender="群成员",
            text="这是一段不应写入 map input 文件的聊天正文。",
            msg_type="text",
            chat_id="group@chatroom",
            chat_name="测试群",
            table_name="message",
            metadata={},
        )
        chunk = MessageChunk(
            id="shard-001",
            index=1,
            start_ts=message.timestamp,
            end_ts=message.timestamp,
            start_time=message.time,
            end_time=message.time,
            message_count=1,
            char_count=len(message.text),
            messages=[message],
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            run_map_stage([chunk], output_dir, dry_run=True, client=None, max_workers=1)
            self.assertFalse((output_dir / "map" / "shard-001.input.json").exists())
            self.assertTrue((output_dir / "map" / "shard-001.output.json").exists())


if __name__ == "__main__":
    unittest.main()
