from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trendgpt.cli import _collect
from trendgpt.sources import SourceResult


class _PagedSteamAdapter:
    source_id = "steam"

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch(self, request):
        self.calls.append(request.cursor)
        key = request.cursor or "0"
        result = self.pages[key]
        return SourceResult(
            source_id=result["source_id"],
            status=result["status"],
            fetched_at=request.fetched_at,
            scope=request.scope,
            items=result["items"],
            cursor=key,
            next_cursor=result["next_cursor"],
            coverage=result["coverage"],
            evidence_refs=[],
            errors=result.get("errors", []),
        )


def _page(start, items, *, total=3, page_size=2, next_cursor=None, status="partial"):
    return {
        "source_id": "steam",
        "status": status,
        "items": items,
        "next_cursor": next_cursor,
        "coverage": {
            "page_start": start,
            "page_size": page_size,
            "total_results": total,
            "page_complete": True,
            "pagination_complete": next_cursor is None,
        },
    }


def _item(app_id, name, *, release_date="Nov 9, 2026"):
    return {
        "name": name,
        "platform": "steam",
        "platform_id": app_id,
        "source_record_id": app_id,
        "url": f"https://store.steampowered.com/app/{app_id}/game/",
        "list_type": "recentreleases",
        "release_date_text": release_date,
        "price_text": "US$ 4.99",
        "price_final_text": "US$ 4.99",
        "price_original_text": "US$ 5.99",
        "price_original": "US$ 5.99",
        "price_final_minor_units": "499",
        "price_currency_id": "1",
        "review_summary": "Very Positive",
        "review_tooltip_text": "Very Positive 94% of the 100 user reviews are positive.",
        "review_positive_pct": 94.0,
        "review_count": 100,
        "review_rating_class": "positive",
        "discount_text": "-20%",
        "discount_pct": "-20%",
        "discount_pct_numeric": 20,
        "steam_filter": "newreleases",
        "discovery_reason": "Appeared in Steam Recent Releases",
    }


def _args(root: Path, plan: Path, *, max_pages=3):
    return argparse.Namespace(
        network_enabled=True,
        output_root=str(root),
        max_pages_per_source=max_pages,
        source_plan=str(plan),
        run_id="steam-collect-test",
        date="2026-11-10",
        slot="00",
        timezone="Asia/Shanghai",
        started_at="2026-11-10T00:00:00+08:00",
    )


class SteamCollectPaginationTests(unittest.TestCase):
    def _plan(self, base: Path) -> Path:
        path = base / "steam-plan.json"
        path.write_text(json.dumps({
            "schema": "trendgpt-source-plan-v1",
            "sources": [{
                "source": "steam",
                "scope": {"list_type": "recentreleases"},
                "page_limit": 2,
                "max_pages": 3,
            }],
        }), encoding="utf-8")
        return path

    def test_collect_aggregates_complete_multi_page_steam_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            adapter = _PagedSteamAdapter({
                "0": _page(0, [_item("1", "Game A"), _item("2", "Game B")], next_cursor="2"),
                "2": _page(2, [_item("3", "Game C")], next_cursor=None, status="complete"),
            })
            with patch("trendgpt.cli._make_adapter", return_value=adapter):
                result = _collect(_args(root, self._plan(base)))

            self.assertEqual(adapter.calls, [None, "2"])
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["candidate_count"], 3)
            source = result["source_summary"][0]
            self.assertTrue(source["pagination_complete"])
            self.assertEqual(source["pages"], 2)
            self.assertEqual(source["total_results"], 3)
            self.assertEqual(source["unique_platform_ids"], 3)

            snapshot = json.loads(Path(result["candidate_path"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["collection_status"], "complete")
            self.assertEqual(snapshot["candidates"][0]["sources"][0]["position"], 1)
            self.assertEqual(snapshot["candidates"][0]["sources"][0]["release_date_text"], "Nov 9, 2026")
            metadata = snapshot["candidates"][0]["source_metadata"][0]
            source = snapshot["candidates"][0]["sources"][0]
            self.assertEqual(metadata["price_text"], "US$ 4.99")
            self.assertEqual(metadata["review_count"], 100)
            self.assertEqual(metadata["review_positive_pct"], 94.0)
            self.assertEqual(metadata["discount_pct"], "-20%")
            self.assertEqual(metadata["steam_filter"], "newreleases")
            self.assertEqual(source["price_original_text"], "US$ 5.99")
            self.assertEqual(source["review_summary"], "Very Positive")
            self.assertEqual(source["discount_pct_numeric"], 20)

    def test_max_page_limit_keeps_source_partial_and_reports_next_cursor(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            adapter = _PagedSteamAdapter({
                "0": _page(0, [_item("1", "Game A"), _item("2", "Game B")], total=5, next_cursor="2"),
                "2": _page(2, [_item("3", "Game C"), _item("4", "Game D")], total=5, next_cursor="4"),
            })
            with patch("trendgpt.cli._make_adapter", return_value=adapter):
                result = _collect(_args(root, self._plan(base), max_pages=2))

            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["candidate_count"], 4)
            source = result["source_summary"][0]
            self.assertFalse(source["pagination_complete"])
            self.assertEqual(source["next_cursor"], "4")
            self.assertEqual(source["stop_reason"], "max_pages_reached")

    def test_cursor_cycle_stops_without_repeating_a_page(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            adapter = _PagedSteamAdapter({
                "0": _page(0, [_item("1", "Game A"), _item("2", "Game B")], total=10, next_cursor="0"),
            })
            with patch("trendgpt.cli._make_adapter", return_value=adapter):
                result = _collect(_args(root, self._plan(base)))

            self.assertEqual(adapter.calls, [None])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["source_summary"][0]["stop_reason"], "pagination_cursor_cycle")


if __name__ == "__main__":
    unittest.main()
