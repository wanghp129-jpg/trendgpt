from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.cli import build_parser, _prepare_resolution, _resolve_candidates
from trendgpt.contracts import ContractError, validate_candidate_snapshot


def _snapshot(root: Path):
    evidence_path = root / "steam.html"
    evidence_path.write_text("<html>steam evidence</html>", encoding="utf-8")
    import hashlib
    evidence = {"path": str(evidence_path), "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()}
    return {
        "schema": "self-candidate-keywords-v1",
        "run_id": "cli-resolver-test",
        "date": "2026-11-10",
        "slot": "00",
        "timezone": "Asia/Shanghai",
        "started_at": "2026-11-10T00:00:00+08:00",
        "collected_at": "2026-11-10T00:03:00+08:00",
        "cutoff_at": "2026-11-10T00:04:00+08:00",
        "code_version": "test",
        "normalization_version": "test",
        "source_policy_version": "test",
        "collection_status": "partial",
        "completeness": "partial",
        "source_runs": [{"source_id": "steam", "status": "complete"}],
        "candidates": [{
            "candidate_id": "candidate-1",
            "entity_id": "provisional:candidate-1",
            "canonical_name": "Neon Drift",
            "aliases": [],
            "raw_titles": ["Neon Drift"],
            "entity_resolution": {"status": "provisional", "method": "source_record_identity", "confidence": None},
            "platforms": ["steam"],
            "platform_ids": {"steam": "123"},
            "discovery_origin": "self_discovered",
            "origin_events": [{"origin": "self_discovered", "source_id": "steam", "observed_at": "2026-11-10T00:01:00+08:00", "run_id": "cli-resolver-test"}],
            "first_discovered_at": "2026-11-10T00:01:00+08:00",
            "first_self_discovered_at": "2026-11-10T00:01:00+08:00",
            "independent_eligibility": {"eligible": None, "reason": "not adjudicated"},
            "sources": [{"source_id": "steam", "source_record_id": "123"}],
            "source_metadata": [],
            "platform_signals": [],
            "discovery_reasons": ["Steam discovery"],
            "raw_evidence_refs": [evidence],
            "missing_fields": [],
        }],
        "unparsed_items": [{
            "source_id": "youtube",
            "source_record_id": "abcdefghijk",
            "raw_evidence_refs": [evidence],
            "position": 0,
            "reason": "source record has no resolved game identity",
            "fetched_at": "2026-11-10T00:02:00+08:00",
            "raw_record": {
                "video_id": "abcdefghijk",
                "title": "Neon Drift Official Gameplay",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "query": "releasedategameplay",
                "query_role": "release_date_gameplay",
                "description_snippet": "Neon Drift gameplay",
            },
        }],
        "counts": {"raw_records": 2, "parsed_records": 1, "unparsed_records": 1, "entities": 1},
    }


class CandidateResolutionCliTests(unittest.TestCase):
    def test_parser_exposes_prepare_and_apply_commands(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args([
            "prepare-resolution", "--input", "/tmp/a.json", "--output-root", "/tmp/self-v1"
        ]).command, "prepare-resolution")
        self.assertEqual(parser.parse_args([
            "resolve-candidates", "--input", "/tmp/a.json", "--plan", "/tmp/p.json",
            "--output-root", "/tmp/self-v1",
        ]).command, "resolve-candidates")

    def test_prepare_and_apply_write_separate_artifacts_without_mutating_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            root.mkdir(parents=True)
            snapshot = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            original_bytes = input_path.read_bytes()
            prepare_args = argparse.Namespace(input=str(input_path), output_root=str(root), output_relative=None)
            prepared = _prepare_resolution(prepare_args)
            plan_path = Path(prepared["plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["decisions"][0].update({
                "action": "link_existing",
                "approval_status": "approved",
                "target_candidate_id": "candidate-1",
                "reason": "Title and description identify the same game.",
                "reviewed_by": "operator",
            })
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            apply_args = argparse.Namespace(
                input=str(input_path), plan=str(plan_path), output_root=str(root),
                output_relative=None, report_relative=None,
            )
            result = _resolve_candidates(apply_args)
            output_path = Path(result["output_path"])
            report_path = Path(result["report_path"])
            resolved = json.loads(output_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(prepared["status"], "plan_prepared")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["applied"]["linked"], 1)
        self.assertEqual(len(resolved["candidates"][0]["supplementary_evidence"]), 1)
        self.assertTrue(report["original_candidate_unchanged"])
        self.assertEqual(input_path.read_bytes(), original_bytes)
        validate_candidate_snapshot(resolved)

    def test_prepare_rejects_input_outside_self_v1(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "self-v1"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            args = argparse.Namespace(input=str(outside), output_root=str(root), output_relative=None)
            with self.assertRaises(ContractError):
                _prepare_resolution(args)


if __name__ == "__main__":
    unittest.main()
