from __future__ import annotations

import unittest

from trendgpt.benchmark import adjudicate_independence


class IndependenceAdjudicationTests(unittest.TestCase):
    def test_candidate_observed_before_api_snapshot_can_be_marked_relative_independent(self):
        candidate = {
            "candidate_id": "c1",
            "discovery_origin": "self_discovered",
            "first_self_discovered_at": "2026-10-22T00:10:00+08:00",
        }
        result = adjudicate_independence(
            candidate,
            first_api_observed_at="2026-10-22T08:05:00+08:00",
            evidence_ref={"path": "/evidence/api-snapshot.json", "sha256": "a" * 64},
            adjudicated_by="operator-review-01",
        )
        self.assertTrue(result["independent_eligibility"]["eligible"])
        self.assertEqual(result["independent_eligibility"]["reason"], "self_observed_before_local_api_observation")
        self.assertNotIn("independent_eligibility", candidate)

    def test_api_observed_first_is_not_counted_as_independent_discovery(self):
        result = adjudicate_independence(
            {"candidate_id": "c1", "first_self_discovered_at": "2026-10-22T09:00:00+08:00"},
            first_api_observed_at="2026-10-22T08:05:00+08:00",
            evidence_ref={"path": "/evidence/api-snapshot.json", "sha256": "b" * 64},
            adjudicated_by="operator-review-01",
        )
        self.assertFalse(result["independent_eligibility"]["eligible"])


if __name__ == "__main__":
    unittest.main()
