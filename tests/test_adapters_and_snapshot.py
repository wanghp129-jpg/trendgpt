from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.adapters.roblox import _RobloxCards
from trendgpt.adapters.steam import _SteamResults
from trendgpt.benchmark_snapshot import read_archived_api_snapshot
from trendgpt.sources import SourceResult, merge_source_results


class AdapterParserTests(unittest.TestCase):
    def test_steam_search_result_extracts_app_id_and_name(self):
        html = """
        <a class="search_result" href="https://store.steampowered.com/app/12345/Game_A/">
          <div><span class="title">Game A</span></div>
          <div class="search_released">Oct 20, 2026</div>
        </a>
        """
        parser = _SteamResults()
        parser.feed(html)
        self.assertEqual(len(parser.items), 1)
        self.assertEqual(parser.items[0]["name"], "Game A")
        self.assertEqual(parser.items[0]["platform_id"], "12345")

    def test_roblox_parser_extracts_stable_game_id(self):
        parser = _RobloxCards()
        parser.feed('<a href="/games/98765/Some-Game" title="Some Game">Some Game</a>')
        self.assertEqual(len(parser.items), 1)
        self.assertEqual(parser.items[0]["platform_id"], "98765")
        self.assertEqual(parser.items[0]["name"], "Some Game")


class CandidateMergeTests(unittest.TestCase):
    def test_video_title_is_preserved_as_unparsed_not_mistaken_for_game_name(self):
        result = SourceResult(
            source_id="youtube", status="partial", fetched_at="2026-10-22T00:00:00Z",
            scope={"query": "new game trailer"},
            items=[{"title": "Official Trailer - A Game", "source_record_id": "video1", "platform": "youtube_video"}],
        )
        snapshot = merge_source_results(
            [result], run_id="r1", run_date="2026-10-22", slot="00",
            timezone="Asia/Shanghai", started_at="2026-10-22T00:00:00+08:00",
            collected_at="2026-10-22T00:01:00+08:00", cutoff_at="2026-10-22T00:01:00+08:00",
            code_version="test", normalization_version="v1", source_policy_version="v1",
        )
        self.assertEqual(snapshot["candidates"], [])
        self.assertEqual(snapshot["counts"]["unparsed_records"], 1)
        self.assertIn("Official Trailer", snapshot["unparsed_items"][0]["raw_record"]["title"])

    def test_independence_is_not_assumed_by_source_collector(self):
        result = SourceResult(
            source_id="steam", status="complete", fetched_at="2026-10-22T00:00:00Z",
            scope={"list_type": "recentreleases"},
            items=[{"name": "Game A", "platform": "steam", "platform_id": "123"}],
        )
        snapshot = merge_source_results(
            [result], run_id="r1", run_date="2026-10-22", slot="00",
            timezone="Asia/Shanghai", started_at="2026-10-22T00:00:00+08:00",
            collected_at="2026-10-22T00:01:00+08:00", cutoff_at="2026-10-22T00:01:00+08:00",
            code_version="test", normalization_version="v1", source_policy_version="v1",
        )
        self.assertIsNone(snapshot["candidates"][0]["independent_eligibility"]["eligible"])


class ArchivedBenchmarkTests(unittest.TestCase):
    def test_snapshot_never_marks_unknown_provider_timing_ready_or_copies_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            raw = base / "raw.json"
            raw.write_text(json.dumps({
                "ok": True, "available": True, "identity": "private-secret",
                "date": "2026-10-22", "window": "morning",
                "words": [{"keyword": "Game A", "platform": "steam"}],
                "bonus_words": [],
            }), encoding="utf-8")
            root = base / "output" / "self-v1"
            result = read_archived_api_snapshot(
                raw, acquired_at="2026-10-22T08:10:00+08:00", output_root=root,
            )
            self.assertEqual(result["evaluation_status"], "benchmark_not_ready")
            self.assertFalse(result["usable_for_evaluation"])
            persisted = Path(result["output_path"]).read_text(encoding="utf-8")
            self.assertNotIn("private-secret", persisted)
            self.assertIsNone(result["provider_updated_at"])

    def test_snapshot_refuses_non_self_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            raw = base / "raw.json"
            raw.write_text(json.dumps({"words": [], "bonus_words": []}), encoding="utf-8")
            with self.assertRaises(Exception):
                read_archived_api_snapshot(raw, acquired_at="2026-10-22T08:00:00Z", output_root=base / "production")


if __name__ == "__main__":
    unittest.main()
