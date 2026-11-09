from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.ingest_reader import read_api_ingest_morning_batch


def _write_json(path: Path, value: dict) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _add_not_open_run(ingest_root: Path, run_id: str, batch_date: str) -> None:
    run_dir = ingest_root / "tmp" / run_id
    response = {
        "ok": False, "error": "not_open_yet", "available": False,
        "date": batch_date, "open_at": "08:00",
    }
    _write_json(run_dir / "response.json", response)
    _write_json(run_dir / "summary.json", {
        "run_id": run_id, "status": "unavailable", "exit_code": 0,
        "date": batch_date, "reason": "not_open_yet", "open_at": "08:00",
        "raw_response": str(run_dir / "response.json"),
    })


def _add_success_run(
    ingest_root: Path,
    run_id: str,
    batch_date: str,
    *,
    window: str = "morning",
    payload: dict | None = None,
    response_override: bytes | None = None,
) -> Path:
    if payload is None:
        payload = {
            "ok": True, "available": True, "date": batch_date, "window": window,
            "identity": "private-api-identity",
            "words": [{"keyword": "Game A", "platform": "steam"}],
            "bonus_words": [{"keyword": "Game B"}],
        }
    raw_bytes = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    raw_path = ingest_root / "data" / "raw" / batch_date / window / f"{digest}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    run_dir = ingest_root / "tmp" / run_id
    response_path = run_dir / "response.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_bytes(response_override if response_override is not None else raw_bytes)
    bucket_words = payload.get("words")
    bucket_bonus = payload.get("bonus_words")
    summary = {
        "run_id": run_id, "status": "success", "exit_code": 0,
        "date": batch_date, "window": window,
        "words_count": len(bucket_words) if isinstance(bucket_words, list) else 0,
        "bonus_words_count": len(bucket_bonus) if isinstance(bucket_bonus, list) else 0,
        "unparsed_items": 0, "unparsed_buckets": 0,
        "raw_response": str(response_path), "raw_snapshot": str(raw_path),
        "latest_snapshot": str(ingest_root / "data" / "latest.json"),
    }
    _write_json(run_dir / "summary.json", summary)
    return raw_path


class ApiIngestMorningReaderTests(unittest.TestCase):
    def test_selects_first_successful_morning_after_not_open_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ingest = base / "trendoracle-ingest"
            _add_not_open_run(ingest, "fetch-20261109T000500Z-346372", "2026-11-09")
            _add_not_open_run(ingest, "fetch-20261109T001900Z-111111", "2026-11-09")
            _add_success_run(ingest, "fetch-20261109T014437Z-715650", "2026-11-09")
            _add_success_run(ingest, "fetch-20261109T020000Z-222222", "2026-11-09")
            _add_success_run(ingest, "fetch-20261109T120501Z-151424", "2026-11-09", window="evening")

            result = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )

            self.assertEqual(result["local_fetch_run_id"], "fetch-20261109T014437Z-715650")
            self.assertEqual(result["batch_date"], "2026-11-09")
            self.assertEqual(result["timezone"], "Asia/Shanghai")
            self.assertEqual(result["scheduled_mining_time"], "00:00:00")
            self.assertEqual(result["expected_publication_time"], "2026-11-09T08:00:00+08:00")
            self.assertEqual(result["batch_alignment_status"], "operator_declared_unverified")
            self.assertEqual(result["evaluation_status"], "benchmark_not_ready")
            self.assertEqual(result["completeness"]["status"], "unknown")
            self.assertFalse(result["usable_for_evaluation"])
            self.assertEqual(len(result["other_successful_morning_runs"]), 1)
            self.assertTrue(Path(result["manifest_path"]).is_file())
            self.assertTrue(Path(result["read_report_path"]).is_file())
            self.assertEqual(len(result["normalized_records"]), 2)

            persisted = Path(result["output_path"]).read_text(encoding="utf-8")
            self.assertNotIn("private-api-identity", persisted)
            self.assertIn("operator_declared_unverified", persisted)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["status"] for item in manifest["prepublication_attempts"]],
                ["not_open_yet", "not_open_yet"],
            )
            self.assertEqual(manifest["network_requests"], 0)

            repeated = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )
            self.assertEqual(repeated["snapshot_id"], result["snapshot_id"])
            self.assertEqual(Path(repeated["output_path"]).read_text(encoding="utf-8"), persisted)

    def test_not_open_yet_without_success_is_not_an_empty_benchmark(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ingest = base / "trendoracle-ingest"
            _add_not_open_run(ingest, "fetch-20261109T000500Z-346372", "2026-11-09")
            result = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )
            self.assertEqual(result["status"], "benchmark_not_ready")
            self.assertEqual(result["reason"], "no_valid_successful_morning_snapshot")
            self.assertEqual(result["attempts"][0]["status"], "not_open_yet")
            self.assertEqual(result["network_requests"], 0)
            self.assertNotIn("normalized_records", result)

    def test_missing_bucket_is_partial_not_silently_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ingest = base / "trendoracle-ingest"
            payload = {
                "ok": True, "available": True, "date": "2026-11-09", "window": "morning",
                "words": [{"keyword": "Game A"}],
            }
            _add_success_run(ingest, "fetch-20261109T014437Z-715650", "2026-11-09", payload=payload)
            result = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )
            self.assertEqual(result["completeness"]["status"], "partial")
            self.assertEqual(result["completeness"]["invalid_or_missing_buckets"], ["bonus_words"])
            self.assertEqual(result["evaluation_status"], "benchmark_not_ready")

    def test_response_and_raw_must_be_identical_and_hash_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ingest = base / "trendoracle-ingest"
            _add_success_run(
                ingest, "fetch-20261109T014437Z-715650", "2026-11-09",
                response_override=b'{"ok":true,"available":true}',
            )
            result = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )
            self.assertEqual(result["status"], "benchmark_not_ready")
            self.assertEqual(result["attempts"][0]["status"], "invalid_evidence")
            self.assertIn("response.json and immutable raw snapshot do not match", result["attempts"][0]["reason"])

    def test_rejects_output_root_that_is_not_self_v1(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with self.assertRaises(Exception):
                read_api_ingest_morning_batch(
                    base / "ingest", batch_date="2026-11-09", output_root=base / "production",
                )

    def test_rejects_evening_only_data_for_morning_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ingest = base / "trendoracle-ingest"
            _add_success_run(ingest, "fetch-20261109T120501Z-151424", "2026-11-09", window="evening")
            result = read_api_ingest_morning_batch(
                ingest, batch_date="2026-11-09", output_root=base / "feedback" / "self-v1",
            )
            self.assertEqual(result["status"], "benchmark_not_ready")
            self.assertNotIn("normalized_records", result)


if __name__ == "__main__":
    unittest.main()
