from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from trendgpt.benchmark import adjudicate_independence


class IndependenceAdjudicationTests(unittest.TestCase):
    def _evidence(self, root: Path, payload: bytes):
        path = root / "api-snapshot.json"
        path.write_bytes(payload)
        return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}

    def test_candidate_observed_before_api_snapshot_can_be_marked_relative_independent(self):
        candidate = {
            "candidate_id": "c1",
            "discovery_origin": "self_discovered",
            "first_self_discovered_at": "2026-10-22T00:10:00+08:00",
        }
        with tempfile.TemporaryDirectory() as temp:
            evidence = self._evidence(Path(temp), b"reviewed api snapshot")
            result = adjudicate_independence(
                candidate,
                first_api_observed_at="2026-10-22T08:05:00+08:00",
                evidence_ref=evidence,
                adjudicated_by="operator-review-01",
            )
        self.assertTrue(result["independent_eligibility"]["eligible"])
        self.assertEqual(result["independent_eligibility"]["reason"], "self_observed_before_local_api_observation")
        self.assertNotIn("independent_eligibility", candidate)

    def test_api_observed_first_is_not_counted_as_independent_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = self._evidence(Path(temp), b"reviewed api snapshot")
            result = adjudicate_independence(
                {"candidate_id": "c1", "first_self_discovered_at": "2026-10-22T09:00:00+08:00"},
                first_api_observed_at="2026-10-22T08:05:00+08:00",
                evidence_ref=evidence,
                adjudicated_by="operator-review-01",
            )
        self.assertFalse(result["independent_eligibility"]["eligible"])

    def test_bad_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = self._evidence(Path(temp), b"actual bytes")
            evidence["sha256"] = "a" * 64
            with self.assertRaises(ValueError):
                adjudicate_independence(
                    {"first_self_discovered_at": "2026-10-22T00:00:00Z"},
                    first_api_observed_at="2026-10-22T08:00:00Z",
                    evidence_ref=evidence,
                    adjudicated_by="review-01",
                )


if __name__ == "__main__":
    unittest.main()
