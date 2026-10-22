from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendgpt.dispatch_intent import DispatchIntentError, create_dispatch_intent


def verified():
    return {
        "candidate_id": "c1", "entity_id": "e1", "canonical_name": "Test Game",
        "chosen_domain": "testgame.example", "final_decision": "build",
        "domain_status": "available", "google_trends_status": "passed", "kd": 12,
        "code_version": "test",
    }


def receipt():
    return {"status": "confirmed", "readback_verified": True,
            "evidence_ref": {"path": "/evidence/report.png", "sha256": "a" * 64}}


def policy():
    return {"approved": True, "policy_id": "self-source-v1-approved"}


def dedupe():
    return {"status": "clear", "checked_at": "2026-10-22T10:00:00Z"}


def authorization():
    return {"approved": True, "authorization_id": "approval-001"}


class DispatchIntentTests(unittest.TestCase):
    def test_intent_only_is_written_after_every_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            intent = create_dispatch_intent(
                verified(), report_receipt=receipt(), source_policy=policy(),
                global_dedupe=dedupe(), authorization=authorization(),
                output_root=root, created_at="2026-10-22T10:00:00Z",
            )
            self.assertEqual(intent["dispatch_status"], "intent_only")
            self.assertFalse(intent["request_sent"])
            self.assertEqual(intent["delivery_status"], "not_started")
            self.assertTrue((root / "dispatch-intents" / f"{intent['intent_id']}.json").is_file())

    def test_missing_explicit_authorization_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=receipt(), source_policy=policy(),
                    global_dedupe=dedupe(), authorization={"approved": False},
                    output_root=Path(temp) / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_unverified_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            bad_receipt = {**receipt(), "readback_verified": False}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=bad_receipt, source_policy=policy(),
                    global_dedupe=dedupe(), authorization=authorization(),
                    output_root=Path(temp) / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_validation_build_without_kd_pass_does_not_create_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            invalid = {**verified(), "kd": 30}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    invalid, report_receipt=receipt(), source_policy=policy(),
                    global_dedupe=dedupe(), authorization=authorization(),
                    output_root=Path(temp) / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_production_output_root_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception):
                create_dispatch_intent(
                    verified(), report_receipt=receipt(), source_policy=policy(),
                    global_dedupe=dedupe(), authorization=authorization(),
                    output_root=Path(temp) / "production", created_at="2026-10-22T10:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
