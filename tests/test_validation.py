from __future__ import annotations

import unittest

from trendgpt.validation import validate_candidate


def candidate(identity_status="resolved"):
    return {
        "candidate_id": "c1", "entity_id": "e1", "canonical_name": "Test Game",
        "discovery_origin": "self_discovered",
        "entity_resolution": {"status": identity_status},
    }


class ValidationOrchestratorTests(unittest.TestCase):
    def test_provider_sequence_and_build_is_not_dispatch_authorization(self):
        calls = []
        providers = {
            "site_lookup": lambda c: calls.append("site") or {"status": "clear"},
            "kd": lambda c: calls.append("kd") or {"status": "success", "value": 29},
            "prefilter": lambda c: calls.append("prefilter") or {"status": "passed"},
            "google_trends": lambda c: calls.append("google_trends") or {"status": "passed"},
            "domain": lambda c: calls.append("domain") or {"status": "available", "domain": "testgame.example"},
        }
        result = validate_candidate(candidate(), providers=providers)
        self.assertEqual(calls, ["site", "kd", "prefilter", "google_trends", "domain"])
        self.assertEqual(result["final_decision"], "build")
        self.assertFalse(result["dispatch_authorized"])

    def test_kd_30_stops_before_paid_prefilter_and_browser(self):
        calls = []
        providers = {
            "site_lookup": lambda c: {"status": "clear"},
            "kd": lambda c: {"status": "success", "value": 30},
            "prefilter": lambda c: calls.append("prefilter") or {"status": "passed"},
            "google_trends": lambda c: calls.append("google_trends") or {"status": "passed"},
        }
        result = validate_candidate(candidate(), providers=providers)
        self.assertEqual(result["final_decision"], "drop")
        self.assertEqual(result["reason_codes"], ["kd_gte_30"])
        self.assertEqual(calls, [])

    def test_missing_prefilter_bypasses_to_final_browser(self):
        providers = {
            "site_lookup": lambda c: {"status": "clear"},
            "kd": lambda c: {"status": "success", "value": 10},
            "google_trends": lambda c: {"status": "passed"},
            "domain": lambda c: {"status": "available", "domain": "testgame.example"},
        }
        result = validate_candidate(candidate(), providers=providers)
        self.assertEqual(result["stages"]["prefilter"]["status"], "bypass_missing")
        self.assertEqual(result["final_decision"], "build")

    def test_provisional_identity_cannot_be_dispatched_as_build(self):
        providers = {
            "site_lookup": lambda c: {"status": "clear"},
            "kd": lambda c: {"status": "success", "value": 10},
            "prefilter": lambda c: {"status": "passed"},
            "google_trends": lambda c: {"status": "passed"},
            "domain": lambda c: {"status": "available", "domain": "testgame.example"},
        }
        result = validate_candidate(candidate("provisional"), providers=providers)
        self.assertEqual(result["final_decision"], "needs_review")
        self.assertIn("identity_requires_resolution_before_build", result["reason_codes"])

    def test_provider_exception_becomes_review_not_keyword_rejection(self):
        def broken(_candidate):
            raise RuntimeError("private provider error")
        result = validate_candidate(candidate(), providers={
            "site_lookup": lambda c: {"status": "clear"}, "kd": broken,
        })
        self.assertEqual(result["final_decision"], "needs_review")
        self.assertEqual(result["reason_codes"], ["kd_unavailable_or_invalid"])


if __name__ == "__main__":
    unittest.main()
