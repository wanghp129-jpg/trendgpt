from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.chatgpt_coordination import ChatGPTLease, ChatGPTLockTimeout


class ChatGPTLeaseTests(unittest.TestCase):
    def test_lock_metadata_is_written_and_released(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shared" / "chatgpt.lock"
            with ChatGPTLease(path, owner="trends-cleaner", task_id="task-1", timeout_seconds=0):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["owner"], "trends-cleaner")
                self.assertEqual(data["state"], "held")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "released")

    def test_second_caller_cannot_acquire_held_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "chatgpt.lock"
            with ChatGPTLease(path, owner="one", task_id="1", timeout_seconds=0):
                with self.assertRaises(ChatGPTLockTimeout):
                    ChatGPTLease(path, owner="two", task_id="2", timeout_seconds=0).acquire()

    def test_empty_owner_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                ChatGPTLease(Path(temp) / "chatgpt.lock", owner="", task_id="1")

    def test_relative_lock_path_is_rejected(self):
        with self.assertRaises(ValueError):
            ChatGPTLease("relative/chatgpt.lock", owner="test", task_id="1")


if __name__ == "__main__":
    unittest.main()
