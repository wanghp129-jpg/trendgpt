from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendgpt.registry import lookup_candidate, read_site_registry
from trendgpt.rule_replay import replay_rules, selected_ids


class RegistryTests(unittest.TestCase):
    def test_direct_game_name_match_blocks_duplicate_build(self):
        registry = {"sites": [{"domain": "example.wiki", "topic_name": "Test Game", "status": "online"}]}
        result = lookup_candidate({"canonical_name": " test game ", "aliases": []}, registry)
        self.assertEqual(result["status"], "already_built")

    def test_keyword_only_match_is_review_not_a_hard_duplicate(self):
        registry = {"sites": [{"domain": "example.wiki", "topic_name": "Another Game", "keywords": "test game, codes"}]}
        result = lookup_candidate({"canonical_name": "Test Game", "aliases": []}, registry)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["match_method"], "keyword_only")

    def test_registry_reader_rejects_duplicate_domains(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "site.json"
            path.write_text('{"sites":[{"domain":"example.wiki"},{"domain":"example.wiki"}]}', encoding="utf-8")
            with self.assertRaises(Exception):
                read_site_registry(path)


class RuleReplayTests(unittest.TestCase):
    def test_replay_reports_changes_without_mutating_rules(self):
        candidates = [
            {"candidate_id": "a", "features": {"platform": "steam", "early_signal": 3}},
            {"candidate_id": "b", "features": {"platform": "roblox", "early_signal": 1}},
        ]
        baseline = {"rule_id": "baseline", "conditions": [{"field": "features.early_signal", "operator": "gte", "value": 1}]}
        proposed = {"rule_id": "proposed", "conditions": [{"field": "features.early_signal", "operator": "gte", "value": 2}]}
        outcomes = [
            {"candidate_id": "a", "maturity": "eligible", "revenue_status": "complete", "revenue": 2.0, "currency": "USD", "window_id": "2026-10-01-full-day"},
            {"candidate_id": "b", "maturity": "eligible", "revenue_status": "complete", "revenue": 999.0, "currency": "EUR", "window_id": "2026-10-01-full-day"},
        ]
        result = replay_rules(candidates, baseline, proposed, outcomes)
        self.assertEqual(result["added_candidate_ids"], [])
        self.assertEqual(result["removed_candidate_ids"], ["b"])
        self.assertFalse(result["production_rules_changed"])
        self.assertEqual(result["baseline"]["revenue_summaries"][0]["currency_window"], "EUR|2026-10-01-full-day")

    def test_empty_ruleset_is_rejected(self):
        with self.assertRaises(ValueError):
            selected_ids([{"candidate_id": "a"}], {"conditions": []})


if __name__ == "__main__":
    unittest.main()
