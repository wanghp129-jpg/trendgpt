from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from trendgpt.chatgpt_coordination import ChatGPTLease
from trendgpt.chatgpt_queue import ChatGPTTaskQueue
from trendgpt.chatgpt_queue_cli import main
from trendgpt.storage import evidence_ref


class ChatGPTQueueCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "self-v1"
        self.root.mkdir()
        self.input = self.root / "input.json"
        self.input.write_text('{"candidate_names":["Example Game"]}', encoding="utf-8")
        self.queue = ChatGPTTaskQueue(self.root)
        self.queue.enqueue(
            task_type="keyword_cleaning",
            input_ref=evidence_ref(self.input, root=self.root),
            output_relative="results/cleaned.json",
            idempotency_key="cli-test-1",
            created_at="2026-10-23T00:00:00Z",
        )
        self.lock_path = self.base / "shared-locks" / "chatgpt-global.lock"

    def tearDown(self):
        self.temp.cleanup()

    def test_run_next_holds_shared_lock_and_completes_json_output(self):
        code = (
            "import json,os,pathlib; "
            "p=pathlib.Path(os.environ['TRENDGPT_OUTPUT_PATH']); "
            "p.parent.mkdir(parents=True,exist_ok=True); "
            "p.write_text(json.dumps({'cleaned_names':['Example Game']}),encoding='utf-8')"
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([
                "run-next", "--output-root", str(self.root),
                "--lock-path", str(self.lock_path), "--owner", "test-worker",
                "--timeout-seconds", "2", "--", sys.executable, "-c", code,
            ])
        self.assertEqual(result, 0, output.getvalue())
        task = self.queue.list_tasks()["tasks"][0]
        self.assertEqual(task["status"], "completed")
        self.assertTrue(Path(task["result_ref"]["path"]).is_file())
        lock_data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(lock_data["state"], "released")

    def test_run_next_does_not_claim_when_shared_lock_is_held(self):
        output = io.StringIO()
        with ChatGPTLease(self.lock_path, owner="code_before", task_id="existing-task", timeout_seconds=0):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                result = main([
                    "run-next", "--output-root", str(self.root),
                    "--lock-path", str(self.lock_path), "--owner", "trendgpt",
                    "--timeout-seconds", "0", "--", sys.executable, "-c", "pass",
                ])
        self.assertEqual(result, 75)
        self.assertEqual(self.queue.list_tasks()["tasks"][0]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
