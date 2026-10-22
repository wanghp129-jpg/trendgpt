from __future__ import annotations

import unittest

from trendgpt.pipeline import (
    dispatch_allowed, gate_domain, gate_google_trends, gate_kd, gate_prefilter,
)
from trendgpt.rules import evaluate_feature_groups
from trendgpt.sources import SourceResult, merge_source_results


class PipelineGateTests(unittest.TestCase):
    def test_kd_boundary_is_strict(self):
        self.assertEqual(gate_kd("success", 29)["status"], "continue")
        self.assertEqual(gate_kd("success", 30)["status"], "drop")

    def test_missing_kd_is_review_not_drop(self):
        self.assertEqual(gate_kd("unavailable", None)["status"], "needs_review")
        self.assertEqual(gate_kd("success", "unknown")["status"], "needs_review")

    def test_missing_prefilter_bypasses_to_final_browser(self):
        self.assertEqual(gate_prefilter("bypass_missing")["next"], "google_trends")

    def test_domain_unavailable_does_not_reject_game(self):
        self.assertEqual(gate_domain("all_registered")["status"], "needs_review")

    def test_dispatch_defaults_to_deny(self):
        self.assertFalse(dispatch_allowed(
            decision="build", report_confirmed=True, source_policy_approved=False,
            global_dedupe_clear=True, authorization_ref_present=True,
        ))
        self.assertTrue(dispatch_allowed(
            decision="build", report_confirmed=True, source_policy_approved=True,
            global_dedupe_clear=True, authorization_ref_present=True,
        ))

    def test_google_browser_is_final_gate(self):
        self.assertEqual(gate_google_trends("insufficient_data")["status"], "needs_review")
        self.assertEqual(gate_google_trends("passed")["next"], "domain")


class SourceMergeTests(unittest.TestCase):
    def test_failed_source_is_not_reported_as_complete_empty_source(self):
        result = SourceResult(
            source_id="steam", status="failed", fetched_at="2026-10-22T00:00:00Z",
            scope={"list_type": "recentreleases"}, items=[],
            errors=[{"code": "network_error"}],
        )
        snapshot = merge_source_results(
            [result], run_id="r1", run_date="2026-10-22", slot="00",
            timezone="Asia/Shanghai", started_at="2026-10-22T00:00:00+08:00",
            collected_at="2026-10-22T00:01:00+08:00", cutoff_at="2026-10-22T00:01:00+08:00",
            code_version="test", normalization_version="v1", source_policy_version="v1",
        )
        self.assertEqual(snapshot["collection_status"], "failed")
        self.assertEqual(snapshot["completeness"], "unknown")

    def test_same_platform_stable_id_merges_but_keeps_provenance(self):
        one = SourceResult(
            source_id="roblox-upcoming", status="complete", fetched_at="2026-10-22T00:00:00Z",
            scope={"list_type": "upcoming"},
            items=[{"name": "Game A", "platform": "roblox", "platform_id": "123", "url": "https://example.test/a"}],
        )
        two = SourceResult(
            source_id="roblox-popular", status="complete", fetched_at="2026-10-22T00:02:00Z",
            scope={"list_type": "popular"},
            items=[{"name": "Game A", "platform": "roblox", "platform_id": "123", "url": "https://example.test/a"}],
        )
        snapshot = merge_source_results(
            [one, two], run_id="r1", run_date="2026-10-22", slot="00",
            timezone="Asia/Shanghai", started_at="2026-10-22T00:00:00+08:00",
            collected_at="2026-10-22T00:03:00+08:00", cutoff_at="2026-10-22T00:03:00+08:00",
            code_version="test", normalization_version="v1", source_policy_version="v1",
        )
        self.assertEqual(len(snapshot["candidates"]), 1)
        self.assertEqual(len(snapshot["candidates"][0]["sources"]), 2)

    def test_revenue_rules_exclude_missing_currency_or_window(self):
        data = [{
            "maturity": "eligible", "revenue_status": "complete",
            "revenue": 3.2, "features": {"platform": "steam"},
        }]
        result = evaluate_feature_groups(data, minimum_samples=2)
        self.assertEqual(result["eligible_observations"], 0)
        self.assertEqual(result["excluded"]["missing_currency_or_window"], 1)
        self.assertFalse(result["production_rules_changed"])


if __name__ == "__main__":
    unittest.main()
