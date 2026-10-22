from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from trendgpt.chatgpt_queue import ChatGPTTaskQueue, QueueConflict
from trendgpt.storage import evidence_ref


class ChatGPTQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "self-v1"
        self.root.mkdir()
        self.input_path = self.root / "candidate-input.json"
        self.input_path.write_text('{"candidates":["Game A"]}', encoding="utf-8")
        self.input_ref = evidence_ref(self.input_path, root=self.root)
        self.queue = ChatGPTTaskQueue(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self, key="clean-2026-10-23"):
        return self.queue.enqueue(
            task_type="keyword_cleaning",
            input_ref=self.input_ref,
            output_relative="cleaned/clean-1.json",
            idempotency_key=key,
            instance_role="trends_keyword_cleaning",
            max_attempts=2,
            created_at="2026-10-23T00:00:00Z",
        )

    def test_enqueue_is_idempotent(self):
        first = self.enqueue()
        second = self.enqueue()
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "reused")
        self.assertEqual(len(self.queue.list_tasks()["tasks"]), 1)

    def test_running_task_blocks_second_claim(self):
        self.enqueue()
        first = self.queue.claim_next(owner="worker-a", claimed_at="2026-10-23T00:01:00Z")
        self.assertEqual(first["task"]["status"], "running")
        self.assertIsNone(self.queue.claim_next(owner="worker-b", claimed_at="2026-10-23T00:02:00Z"))

    def test_complete_requires_matching_lease_and_real_output_hash(self):
        self.enqueue()
        claimed = self.queue.claim_next(owner="worker", claimed_at="2026-10-23T00:01:00Z")["task"]
        output = self.root / "cleaned" / "clean-1.json"
        output.parent.mkdir(parents=True)
        output.write_text('{"cleaned":["Game A"]}', encoding="utf-8")
        ref = evidence_ref(output, root=self.root)
        with self.assertRaises(QueueConflict):
            self.queue.complete(task_id=claimed["task_id"], lease_token="wrong", result_ref=ref)
        done = self.queue.complete(task_id=claimed["task_id"], lease_token=claimed["lease"]["token"], result_ref=ref)
        self.assertEqual(done["status"], "completed")

    def test_uncertain_failure_goes_to_review_not_auto_retry(self):
        self.enqueue()
        claimed = self.queue.claim_next(owner="worker", claimed_at="2026-10-23T00:01:00Z")["task"]
        result = self.queue.fail(
            task_id=claimed["task_id"], lease_token=claimed["lease"]["token"],
            disposition="needs_review", error_code="submission_result_uncertain",
            failed_at="2026-10-23T00:02:00Z",
        )
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(self.queue.claim_next(owner="worker-2"))

    def test_only_explicit_safe_retry_requeues(self):
        self.enqueue()
        claimed = self.queue.claim_next(owner="worker", claimed_at="2026-10-23T00:01:00Z")["task"]
        result = self.queue.fail(
            task_id=claimed["task_id"], lease_token=claimed["lease"]["token"],
            disposition="safe_retry", error_code="browser_failed_before_submit",
        )
        self.assertEqual(result["status"], "queued")

    def test_stale_running_task_moves_to_review(self):
        self.enqueue()
        self.queue.claim_next(owner="worker", claimed_at="2026-10-22T00:00:00Z")
        result = self.queue.reconcile_stale_running(now="2026-10-23T00:00:00Z", max_age_seconds=1800)
        self.assertEqual(len(result["moved_to_review"]), 1)
        self.assertEqual(self.queue.list_tasks()["tasks"][0]["status"], "needs_review")

    def test_input_outside_self_root_is_rejected(self):
        outside = self.base / "outside.json"
        outside.write_text('{"not":"isolated"}', encoding="utf-8")
        with self.assertRaises(Exception):
            self.queue.enqueue(
                task_type="keyword_cleaning",
                input_ref=evidence_ref(outside, root=self.base),
                output_relative="cleaned/out.json",
                idempotency_key="outside-input",
            )

    def test_output_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue(
                task_type="keyword_cleaning",
                input_ref=self.input_ref,
                output_relative="../production/out.json",
                idempotency_key="path-traversal",
            )

    def test_production_root_is_refused(self):
        with self.assertRaises(Exception):
            ChatGPTTaskQueue(self.base / "production")


if __name__ == "__main__":
    unittest.main()
