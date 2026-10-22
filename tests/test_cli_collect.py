from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trendgpt.cli import _collect
from trendgpt.sources import SourceResult


class _FakeAdapter:
    source_id = "fixture"

    def fetch(self, request):
        return SourceResult(
            source_id="fixture", status="complete", fetched_at=request.fetched_at,
            scope=request.scope,
            items=[{"name": "Fixture Game", "platform": "fixture-platform", "platform_id": "id-1"}],
            coverage={"fixture": True},
        )


class CollectCommandTests(unittest.TestCase):
    def test_collect_writes_isolated_candidate_snapshot_without_real_network(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            plan = base / "source-plan.json"
            plan.write_text(json.dumps({
                "schema": "trendgpt-source-plan-v1",
                "sources": [{"source": "steam", "scope": {"list_type": "recentreleases"}, "page_limit": 10, "max_pages": 1}],
            }), encoding="utf-8")
            args = argparse.Namespace(
                network_enabled=True, output_root=str(root), max_pages_per_source=1,
                source_plan=str(plan), run_id="test-run", date="2026-10-22", slot="00",
                timezone="Asia/Shanghai", started_at="2026-10-22T00:00:00+08:00",
            )
            with patch("trendgpt.cli._make_adapter", return_value=_FakeAdapter()):
                result = _collect(args)
            self.assertEqual(result["status"], "complete")
            snapshot = json.loads(Path(result["candidate_path"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["candidates"][0]["canonical_name"], "Fixture Game")
            self.assertIsNone(snapshot["candidates"][0]["independent_eligibility"]["eligible"])
            self.assertTrue(Path(result["candidate_path"]).is_relative_to(root))


if __name__ == "__main__":
    unittest.main()
