from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.contracts import validate_candidate_snapshot, ContractError
from trendgpt.normalize import normalize_entity_key
from trendgpt.entity_ledger import EntityFirstSeenLedger
from trendgpt.identity_resolution import (
    PLAN_SCHEMA,
    file_sha256,
    prepare_resolution_plan,
    resolve_candidate_snapshot,
)


def _evidence(root: Path, name="youtube.html"):
    path = root / name
    path.write_text("<html>fixture evidence</html>", encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _candidate(candidate_id, name, platform, platform_id, evidence):
    return {
        "candidate_id": candidate_id,
        "entity_id": f"provisional:{candidate_id}",
        "canonical_name": name,
        "aliases": [],
        "raw_titles": [name],
        "entity_resolution": {"status": "provisional", "method": "source_record_identity", "confidence": None},
        "platforms": [platform],
        "platform_ids": {platform: str(platform_id)},
        "discovery_origin": "self_discovered",
        "origin_events": [{
            "origin": "self_discovered",
            "source_id": platform,
            "observed_at": "2026-11-10T00:01:00+08:00",
            "run_id": "resolver-test",
        }],
        "first_discovered_at": "2026-11-10T00:01:00+08:00",
        "first_self_discovered_at": "2026-11-10T00:01:00+08:00",
        "independent_eligibility": {"eligible": None, "reason": "not adjudicated"},
        "sources": [{"source_id": platform, "source_record_id": str(platform_id), "fetched_at": "2026-11-10T00:01:00+08:00"}],
        "source_metadata": [],
        "platform_signals": [],
        "discovery_reasons": [f"Observed in {platform}"],
        "raw_evidence_refs": [evidence],
        "missing_fields": [],
    }


def _snapshot(root: Path, *, include_clue=True, two_candidates=False):
    evidence = _evidence(root)
    candidates = [_candidate("candidate-steam-1", "Neon Drift", "steam", "12345", evidence)]
    if two_candidates:
        roblox_evidence = _evidence(root, "roblox.json")
        candidates.append(_candidate("candidate-roblox-1", "Neon Drift Mobile", "roblox", "98765", roblox_evidence))
    clue = {
        "source_id": "youtube",
        "source_record_id": "abcdefghijk",
        "raw_evidence_refs": [evidence],
        "position": 0,
        "reason": "source record has no resolved game identity",
        "fetched_at": "2026-11-10T00:02:00+08:00",
        "raw_record": {
            "video_id": "abcdefghijk",
            "title": "Neon Drift Official Gameplay Trailer",
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "channel_name": "Indie Studio",
            "channel_id": "UCabcdefghijk",
            "query": "releasedategameplay",
            "query_role": "release_date_gameplay",
            "published_time_text": "2 hours ago",
            "published_at": None,
            "description_snippet": "Official gameplay reveal for Neon Drift",
        },
    }
    snapshot = {
        "schema": "self-candidate-keywords-v1",
        "run_id": "resolver-test",
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
        "source_runs": [
            {"source_id": "steam", "status": "complete"},
            {"source_id": "youtube", "status": "partial"},
        ],
        "candidates": candidates,
        "unparsed_items": [clue] if include_clue else [],
        "counts": {"raw_records": 2 if include_clue else 1, "parsed_records": 1, "unparsed_records": 1 if include_clue else 0, "entities": len(candidates)},
    }
    validate_candidate_snapshot(snapshot)
    return snapshot, evidence


class CandidateResolutionTests(unittest.TestCase):
    def test_special_character_normalization_is_unicode_safe_and_conservative(self):
        self.assertEqual(normalize_entity_key("  Ｎｅｏｎ—Drift™  "), "neon drift")
        self.assertEqual(normalize_entity_key("NEON_DRIFT"), "neon drift")
        self.assertEqual(normalize_entity_key("星际 旅人"), "星际 旅人")

    def test_prepare_plan_is_review_only_and_suggests_exact_phrase_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)

        self.assertEqual(plan["schema"], PLAN_SCHEMA)
        self.assertEqual(len(plan["candidate_index"]), 1)
        self.assertEqual(plan["candidate_index"][0]["platform_ids"], {"steam": "12345"})
        self.assertEqual(len(plan["decisions"]), 1)
        decision = plan["decisions"][0]
        self.assertEqual(decision["action"], "unresolved")
        self.assertEqual(decision["approval_status"], "pending")
        self.assertEqual(decision["matching_suggestions"][0]["candidate_id"], "candidate-steam-1")
        self.assertTrue(plan["instructions"]["automatic_merging"] is False)

    def test_approved_youtube_clue_links_to_existing_game_without_using_video_id_as_game_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            snapshot["unparsed_items"][0]["fetched_at"] = "2026-11-10T00:00:30+08:00"
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            decision = plan["decisions"][0]
            decision.update({
                "action": "link_existing",
                "approval_status": "approved",
                "target_candidate_id": "candidate-steam-1",
                "reason": "Video title and description explicitly identify the same game.",
                "reviewed_by": "human-review",
                "aliases": ["Neon Drift Game"],
            })
            original = copy.deepcopy(snapshot)
            resolved, report = resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)

        candidate = resolved["candidates"][0]
        self.assertEqual(candidate["platform_ids"], {"steam": "12345"})
        self.assertEqual(candidate["supplementary_evidence"][0]["source_record_id"], "abcdefghijk")
        self.assertEqual(candidate["supplementary_evidence"][0]["published_at"], None)
        self.assertEqual(candidate["first_self_discovered_at"], "2026-11-10T00:00:30+08:00")
        self.assertIn("Neon Drift Game", candidate["aliases"])
        self.assertEqual(resolved["unparsed_items"][0]["resolution_status"], "linked_to_candidate")
        self.assertEqual(report["applied"]["linked"], 1)
        self.assertEqual(snapshot, original)

    def test_approved_new_game_candidate_has_no_fake_platform_id_and_is_review_tier(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["decisions"][0].update({
                "action": "create_candidate",
                "approval_status": "approved",
                "canonical_name": "New Indie Game",
                "reason": "Reviewer confirmed the video describes a distinct upcoming game.",
                "reviewed_by": "human-review",
            })
            resolved, report = resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)
            new_candidate = next(item for item in resolved["candidates"] if item["canonical_name"] == "New Indie Game")
            ledger_root = root / "ledger" / "self-v1"
            ledger_result = EntityFirstSeenLedger(ledger_root).record_snapshot(resolved)
            ledger = EntityFirstSeenLedger(ledger_root).read()

        self.assertEqual(new_candidate["platform_ids"], {})
        self.assertEqual(new_candidate["platforms"], [])
        self.assertNotIn("youtube_video", new_candidate["platform_ids"])
        self.assertEqual(new_candidate["candidate_quality"]["tier"], "C")
        self.assertTrue(new_candidate["candidate_quality"]["requires_review"])
        self.assertEqual(new_candidate["supplementary_evidence"][0]["source_record_id"], "abcdefghijk")
        self.assertEqual(report["applied"]["created"], 1)
        validate_candidate_snapshot(resolved)
        self.assertEqual(ledger_result["entities_confirmed"], 1)
        self.assertEqual(ledger_result["needs_review"], 1)
        self.assertNotIn("platform:youtube_video:abcdefghijk", ledger["entities"])
        self.assertEqual(ledger["review_queue"][0]["reason"], "missing_stable_platform_id")

    def test_approved_not_game_keeps_original_clue_for_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["decisions"][0].update({
                "action": "not_game",
                "approval_status": "approved",
                "reason": "This is a creator compilation, not a game reference.",
                "reviewed_by": "human-review",
            })
            resolved, report = resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)

        self.assertEqual(resolved["unparsed_items"][0]["resolution_status"], "excluded_not_game")
        self.assertEqual(resolved["unparsed_items"][0]["raw_record"]["video_id"], "abcdefghijk")
        self.assertEqual(report["applied"]["excluded_not_game"], 1)

    def test_pending_decision_is_not_applied(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["decisions"][0]["action"] = "create_candidate"
            plan["decisions"][0]["canonical_name"] = "Unapproved Game"
            resolved, report = resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)
            ledger_root = root / "ledger" / "self-v1"
            result = EntityFirstSeenLedger(ledger_root).record_snapshot(resolved)

        self.assertEqual(len(resolved["candidates"]), 1)
        self.assertEqual(report["applied"]["created"], 0)
        self.assertEqual(report["pending_clues"], 1)

    def test_cross_platform_merge_requires_approval_and_preserves_both_platform_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root, include_clue=False, two_candidates=True)
            snapshot["candidates"][1]["first_self_discovered_at"] = "2026-11-10T00:00:45+08:00"
            snapshot["candidates"][1]["first_discovered_at"] = "2026-11-10T00:00:45+08:00"
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["merges"] = [{
                "primary_candidate_id": "candidate-steam-1",
                "secondary_candidate_id": "candidate-roblox-1",
                "canonical_name": "Neon Drift",
                "approval_status": "approved",
                "reviewed_by": "human-review",
                "reason": "Official developer page explicitly links the Steam and Roblox releases.",
                "evidence_refs": [
                    snapshot["candidates"][0]["raw_evidence_refs"][0],
                    snapshot["candidates"][1]["raw_evidence_refs"][0],
                ],
            }]
            resolved, report = resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)
            ledger_root = root / "ledger" / "self-v1"
            result = EntityFirstSeenLedger(ledger_root).record_snapshot(resolved)

        self.assertEqual(len(resolved["candidates"]), 1)
        self.assertEqual(resolved["candidates"][0]["platform_ids"], {"steam": "12345", "roblox": "98765"})
        self.assertEqual(resolved["candidates"][0]["entity_resolution"]["status"], "human_adjudicated_cross_platform_merge")
        self.assertEqual(resolved["candidates"][0]["candidate_quality"]["tier"], "C")
        self.assertEqual(resolved["candidates"][0]["first_self_discovered_at"], "2026-11-10T00:00:45+08:00")
        self.assertEqual(report["applied"]["merged"], 1)
        self.assertEqual(result["entities_confirmed"], 0)
        self.assertEqual(result["needs_review"], 1)

    def test_conflicting_ids_on_same_platform_cannot_be_merged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root, include_clue=False, two_candidates=True)
            snapshot["candidates"][1]["platform_ids"] = {"steam": "different-app-id"}
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["merges"] = [{
                "primary_candidate_id": "candidate-steam-1",
                "secondary_candidate_id": "candidate-roblox-1",
                "approval_status": "approved",
                "reviewed_by": "human-review",
                "reason": "Test conflicting IDs",
                "evidence_refs": [
                    snapshot["candidates"][0]["raw_evidence_refs"][0],
                    snapshot["candidates"][1]["raw_evidence_refs"][0],
                ],
            }]
            with self.assertRaises(ContractError):
                resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)

    def test_plan_rejects_stale_input_hash_and_missing_clue_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            with self.assertRaises(ContractError):
                resolve_candidate_snapshot(snapshot, plan, input_sha256="0" * 64)
            plan["decisions"] = []
            with self.assertRaises(ContractError):
                resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)

    def test_approved_decision_rejects_tampered_source_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, evidence = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["decisions"][0].update({
                "action": "not_game", "approval_status": "approved",
                "reason": "Reviewed", "reviewed_by": "human-review",
            })
            Path(evidence["path"]).write_text("<html>tampered</html>", encoding="utf-8")
            with self.assertRaises(ContractError):
                resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)

    def test_approved_decision_cannot_invent_evidence_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot, _ = _snapshot(root)
            input_path = root / "candidate_keywords.json"
            input_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            digest = file_sha256(input_path)
            plan = prepare_resolution_plan(snapshot, input_path=str(input_path), input_sha256=digest)
            plan["decisions"][0].update({
                "action": "not_game",
                "approval_status": "approved",
                "reason": "Reviewed",
                "reviewed_by": "human-review",
                "evidence_refs": [{"path": "/tmp/fake.html", "sha256": "0" * 64}],
            })
            with self.assertRaises(ContractError):
                resolve_candidate_snapshot(snapshot, plan, input_sha256=digest)


if __name__ == "__main__":
    unittest.main()
