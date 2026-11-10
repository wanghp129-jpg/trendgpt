from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from trendgpt.dispatch_intent import DispatchIntentError, create_dispatch_intent


def verified():
    return {
        "candidate_id": "c1", "entity_id": "e1", "canonical_name": "Test Game",
        "chosen_domain": "testgame.example", "final_decision": "build",
        "domain_status": "available", "google_trends_status": "passed", "kd": 12,
        "code_version": "test", "discovery_origin": "self_discovered",
    }


def make_ref(root: Path, filename: str):
    path = root / filename
    path.write_bytes(f"fixture evidence: {filename}".encode())
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def make_receipt(root: Path):
    return {"status": "confirmed", "readback_verified": True,
            "evidence_ref": make_ref(root, "report-evidence.png")}


def policy(root: Path):
    return {"approved": True, "policy_id": "self-source-v1-approved",
            "evidence_ref": make_ref(root, "source-policy.json")}


def dedupe(root: Path):
    return {"status": "clear", "checked_at": "2026-10-22T10:00:00Z",
            "evidence_ref": make_ref(root, "global-dedupe.json")}


def authorization(root: Path):
    return {"approved": True, "authorization_id": "approval-001",
            "evidence_ref": make_ref(root, "authorization.json")}


class DispatchIntentTests(unittest.TestCase):
    def test_intent_only_is_written_after_every_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "self-v1"
            intent = create_dispatch_intent(
                verified(), report_receipt=make_receipt(base), source_policy=policy(base),
                global_dedupe=dedupe(base), authorization=authorization(base),
                output_root=root, created_at="2026-10-22T10:00:00Z",
            )
            self.assertEqual(intent["dispatch_status"], "intent_only")
            self.assertFalse(intent["request_sent"])
            self.assertEqual(intent["delivery_status"], "not_started")
            self.assertTrue((root / "dispatch-intents" / f"{intent['intent_id']}.json").is_file())

    def test_missing_explicit_authorization_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=make_receipt(base), source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization={"approved": False},
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_unverified_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            bad_receipt = {**make_receipt(base), "readback_verified": False}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=bad_receipt, source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_modified_report_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            report = make_receipt(base)
            (base / "report-evidence.png").write_bytes(b"changed bytes")
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=report, source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_validation_build_without_kd_pass_does_not_create_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            invalid = {**verified(), "kd": 30}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    invalid, report_receipt=make_receipt(base), source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_existing_api_source_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            api_policy = {**policy(base), "policy_id": "trendoracle-ready"}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    verified(), report_receipt=make_receipt(base), source_policy=api_policy,
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_api_benchmark_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            api_candidate = {**verified(), "discovery_origin": "api_benchmark"}
            with self.assertRaises(DispatchIntentError):
                create_dispatch_intent(
                    api_candidate, report_receipt=make_receipt(base), source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "self-v1", created_at="2026-10-22T10:00:00Z",
                )

    def test_production_output_root_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with self.assertRaises(Exception):
                create_dispatch_intent(
                    verified(), report_receipt=make_receipt(base), source_policy=policy(base),
                    global_dedupe=dedupe(base), authorization=authorization(base),
                    output_root=base / "production", created_at="2026-10-22T10:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
