from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.entity_ledger import EntityFirstSeenLedger, EntityLedgerConflict


def candidate_snapshot(
    run_id: str,
    run_date: str,
    observed_at: str,
    *,
    name: str = "Game A",
    platform_ids: dict | None = None,
    aliases: list[str] | None = None,
    origin: str = "self_discovered",
):
    candidate = {
        "candidate_id": f"candidate-{run_id}",
        "entity_id": "provisional:candidate",
        "canonical_name": name,
        "aliases": aliases or [],
        "raw_titles": [name],
        "platforms": ["steam"] if platform_ids else [],
        "platform_ids": platform_ids or {},
        "discovery_origin": origin,
        "origin_events": [{
            "origin": "self_discovered", "source_id": "steam",
            "observed_at": observed_at, "run_id": run_id,
        }],
        "first_discovered_at": observed_at,
        "first_self_discovered_at": observed_at,
        "sources": [{
            "source_id": "steam", "source_record_id": next(iter((platform_ids or {}).values()), None),
            "fetched_at": observed_at,
        }],
        "raw_evidence_refs": [],
        "missing_fields": [],
    }
    return {
        "schema": "self-candidate-keywords-v1",
        "run_id": run_id,
        "date": run_date,
        "slot": "00",
        "timezone": "Asia/Shanghai",
        "started_at": observed_at,
        "collected_at": observed_at,
        "cutoff_at": observed_at,
        "code_version": "test",
        "normalization_version": "candidate-normalizer-v1",
        "source_policy_version": "test-v1",
        "collection_status": "partial",
        "completeness": "partial",
        "source_runs": [{"source_id": "steam", "status": "partial"}],
        "candidates": [candidate],
    }


class EntityFirstSeenLedgerTests(unittest.TestCase):
    def test_stable_platform_id_preserves_first_seen_across_days(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            ledger = EntityFirstSeenLedger(root)
            first = candidate_snapshot(
                "run-20261109", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={"steam": "12345"},
            )
            first_result = ledger.record_snapshot(first)
            self.assertEqual(first_result["status"], "recorded")
            first_output = Path(first_result["output_path"])
            enriched_first = json.loads(first_output.read_text(encoding="utf-8"))
            item = enriched_first["candidates"][0]
            self.assertEqual(item["entity_id"], "platform:steam:12345")
            self.assertEqual(item["first_seen_status"], "confirmed_stable_platform_id")
            self.assertEqual(item["first_self_discovered_at"], "2026-11-08T16:02:00Z")

            second = candidate_snapshot(
                "run-20261110", "2026-11-10", "2026-11-10T00:03:00+08:00",
                name="Game A Updated", platform_ids={"steam": "12345"},
            )
            second_result = ledger.record_snapshot(second)
            enriched_second = __import__("json").loads(Path(second_result["output_path"]).read_text(encoding="utf-8"))
            item2 = enriched_second["candidates"][0]
            self.assertEqual(item2["first_self_discovered_at"], "2026-11-08T16:02:00Z")
            self.assertIn("Game A", item2["aliases"])
            self.assertEqual(second_result["entities_confirmed"], 1)

            stored = ledger.read()
            entity = stored["entities"]["platform:steam:12345"]
            self.assertEqual(entity["observation_count"], 2)
            self.assertEqual(entity["first_seen_at"], "2026-11-08T16:02:00Z")
            self.assertEqual(entity["last_seen_at"], "2026-11-09T16:03:00Z")

            # Replaying an older run after a newer alias update must reuse its frozen output.
            replayed = ledger.record_snapshot(first)
            self.assertEqual(replayed["status"], "reused")
            frozen_first = json.loads(first_output.read_text(encoding="utf-8"))
            self.assertEqual(frozen_first["candidates"][0]["canonical_name"], "Game A")

    def test_replaying_same_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            snapshot = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={"steam": "12345"},
            )
            first = ledger.record_snapshot(snapshot)
            second = ledger.record_snapshot(snapshot)
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "reused")
            self.assertEqual(ledger.read()["entities"]["platform:steam:12345"]["observation_count"], 1)

    def test_same_title_with_different_platform_ids_stays_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            one = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:02:00+08:00",
                name="Same Name", platform_ids={"steam": "111"},
            )
            two = candidate_snapshot(
                "run-2", "2026-11-10", "2026-11-10T00:02:00+08:00",
                name="Same Name", platform_ids={"steam": "222"},
            )
            ledger.record_snapshot(one)
            ledger.record_snapshot(two)
            self.assertEqual(set(ledger.read()["entities"]), {"platform:steam:111", "platform:steam:222"})

    def test_missing_platform_id_is_review_not_fuzzy_merged(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            snapshot = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={},
            )
            result = ledger.record_snapshot(snapshot)
            output = __import__("json").loads(Path(result["output_path"]).read_text(encoding="utf-8"))
            self.assertEqual(output["candidates"][0]["first_seen_status"], "needs_review")
            self.assertEqual(output["candidates"][0]["first_seen_reason"], "missing_stable_platform_id")
            self.assertEqual(ledger.read()["entities"], {})
            self.assertEqual(len(ledger.read()["review_queue"]), 1)

    def test_multiple_platform_ids_require_explicit_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            snapshot = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={"steam": "123", "roblox": "456"},
            )
            result = ledger.record_snapshot(snapshot)
            self.assertEqual(result["needs_review"], 1)
            self.assertEqual(ledger.read()["entities"], {})

    def test_same_run_id_with_different_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            first = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={"steam": "123"},
            )
            second = candidate_snapshot(
                "run-1", "2026-11-09", "2026-11-09T00:03:00+08:00",
                platform_ids={"steam": "123"},
            )
            ledger.record_snapshot(first)
            with self.assertRaises(EntityLedgerConflict):
                ledger.record_snapshot(second)

    def test_api_benchmark_candidates_cannot_enter_self_first_seen_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            snapshot = candidate_snapshot(
                "run-api", "2026-11-09", "2026-11-09T00:02:00+08:00",
                platform_ids={"steam": "123"}, origin="api_benchmark",
            )
            with self.assertRaises(Exception):
                ledger.record_snapshot(snapshot)
            self.assertFalse(ledger.ledger_path.exists())

    def test_run_id_accepts_timezone_offset_plus_sign(self):
        with tempfile.TemporaryDirectory() as temp:
            run_id = "roblox-pilot-20261110T120000+0800"
            snapshot = candidate_snapshot(
                run_id, "2026-11-10", "2026-11-10T12:00:00+08:00",
                platform_ids={"roblox": "987654"},
            )
            ledger = EntityFirstSeenLedger(Path(temp) / "self-v1")
            first = ledger.record_snapshot(snapshot)
            second = ledger.record_snapshot(snapshot)
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "reused")
            self.assertEqual(ledger.read()["entities"]["platform:roblox:987654"]["observation_count"], 1)

    def test_refuses_non_self_v1_root(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception):
                EntityFirstSeenLedger(Path(temp) / "production")


if __name__ == "__main__":
    unittest.main()
