from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.benchmark import compare_snapshots
from trendgpt.contracts import ContractError, load_json, validate_benchmark_snapshot, validate_verified_snapshot
from trendgpt.normalize import normalize_name, resolve_exact
from trendgpt.state import SelfStateStore, StateConflict


def benchmark(status="ready"):
    return {
        "schema": "api-benchmark-snapshot-v1",
        "snapshot_id": "snapshot-1",
        "acquired_at": "2026-10-22T08:00:00+08:00",
        "evaluation_status": status,
        "usable_for_evaluation": status == "ready",
        "completeness": {"status": "complete" if status == "ready" else "unknown"},
        "update_confirmation": {"confirmed": status == "ready"},
        "normalized_records": [{"keyword": "New Game"}],
    }


def self_snapshot(origin="self_discovered", eligible=True):
    return {
        "schema": "self-candidate-keywords-v1",
        "candidates": [{
            "candidate_id": "c-1",
            "entity_id": "e-1",
            "canonical_name": " new   game ",
            "aliases": [],
            "discovery_origin": origin,
            "first_self_discovered_at": "2026-10-22T00:01:00+08:00",
            "independent_eligibility": {"eligible": eligible},
        }],
    }


class ContractTests(unittest.TestCase):
    def test_strict_loader_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(ContractError):
                load_json(path)

    def test_strict_loader_rejects_nan(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"a":NaN}', encoding="utf-8")
            with self.assertRaises(ContractError):
                load_json(path)

    def test_ready_benchmark_requires_update_confirmation(self):
        data = benchmark()
        data["update_confirmation"]["confirmed"] = False
        with self.assertRaises(ContractError):
            validate_benchmark_snapshot(data)

    def test_build_decision_requires_all_gates(self):
        data = {
            "schema": "self-verified-keywords-v1", "run_id": "r1",
            "date": "2026-10-22", "slot": "00", "timezone": "Asia/Shanghai",
            "code_version": "test", "started_at": "2026-10-22T00:00:00+08:00",
            "results": [{
                "final_decision": "build", "discovery_origin": "self_discovered",
                "kd": 29, "google_trends_status": "passed", "domain_status": "unknown",
            }],
        }
        with self.assertRaises(ContractError):
            validate_verified_snapshot(data)


class NormalizeAndBenchmarkTests(unittest.TestCase):
    def test_normalization_is_unicode_and_whitespace_stable(self):
        self.assertEqual(normalize_name("  ＮＥＷ   GAME "), "new game")

    def test_exact_match(self):
        result = resolve_exact("New Game", [{"canonical_name": "new game", "aliases": []}])
        self.assertEqual(result["status"], "matched")

    def test_ambiguous_match_requires_review(self):
        candidates = [
            {"canonical_name": "New Game", "aliases": []},
            {"canonical_name": "Other", "aliases": ["new game"]},
        ]
        self.assertEqual(resolve_exact("new game", candidates)["status"], "ambiguous")

    def test_unready_benchmark_coverage_is_null(self):
        result = compare_snapshots(
            benchmark("benchmark_not_ready"), [self_snapshot()],
            cutoff="2026-10-22T08:00:00+08:00",
        )
        self.assertEqual(result["status"], "benchmark_not_ready")
        self.assertIsNone(result["independent_coverage"])

    def test_api_origin_does_not_count_as_self_discovery(self):
        result = compare_snapshots(
            benchmark(), [self_snapshot(origin="api_benchmark")],
            cutoff="2026-10-22T08:00:00+08:00",
        )
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["missed"], 1)

    def test_independent_candidate_counts(self):
        result = compare_snapshots(
            benchmark(), [self_snapshot()],
            cutoff="2026-10-22T08:00:00+08:00",
        )
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["independent_coverage"], 1.0)


class StateTests(unittest.TestCase):
    def test_state_is_idempotent_and_conflict_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            store = SelfStateStore(root)
            first = store.record_run(
                run_date="2026-10-22", timezone="Asia/Shanghai", slot="00",
                run_id="run-1", input_sha256="a" * 64, result_ref=None,
                status="completed", seen_keywords=["A", "A"],
            )
            self.assertEqual(first["status"], "recorded")
            second = store.record_run(
                run_date="2026-10-22", timezone="Asia/Shanghai", slot="00",
                run_id="run-1", input_sha256="a" * 64, result_ref=None,
                status="completed",
            )
            self.assertEqual(second["status"], "reused")
            with self.assertRaises(StateConflict):
                store.record_run(
                    run_date="2026-10-22", timezone="Asia/Shanghai", slot="00",
                    run_id="run-2", input_sha256="b" * 64, result_ref=None,
                    status="completed",
                )
            state = store.read("2026-10-22", "Asia/Shanghai")
            self.assertEqual(state["seen_keywords"], ["A"])
            self.assertEqual(state["revision"], 1)

    def test_shared_production_root_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception):
                SelfStateStore(Path(temp) / "output")


if __name__ == "__main__":
    unittest.main()
