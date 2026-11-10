from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trendgpt.cli import _collect
from trendgpt.entity_ledger import EntityFirstSeenLedger
from trendgpt.sources import SourceResult


class _PagedRobloxAdapter:
    source_id = "roblox"

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch(self, request):
        list_type = request.scope["list_type"]
        self.calls.append((list_type, request.cursor))
        key = request.cursor or "first"
        page = self.pages[list_type][key]
        return SourceResult(
            source_id="roblox",
            status=page["status"],
            fetched_at=page["fetched_at"],
            scope={
                **request.scope,
                "sort_id": list_type,
                "url": f"https://apis.roblox.com/explore-api/v1/get-sort-content?sortId={list_type}",
                "pagination_mode": "opaque_page_token",
            },
            items=page["items"],
            cursor=request.cursor,
            next_cursor=page["next_cursor"],
            coverage=page["coverage"],
            evidence_refs=[],
            errors=page.get("errors", []),
        )


def _game(universe_id, name, *, local_rank=1, players=100):
    return {
        "name": name,
        "platform": "roblox",
        "platform_id": str(universe_id),
        "source_record_id": str(universe_id),
        "universe_id": str(universe_id),
        "root_place_id": str(universe_id + 1000),
        "url": f"https://www.roblox.com/games/{universe_id + 1000}",
        "list_type": "up-and-coming",
        "sort_id": "up-and-coming",
        "source_rank": local_rank,
        "player_count": players,
        "total_up_votes": 90,
        "total_down_votes": 10,
        "is_sponsored": False,
        "genre_l1": "Simulation",
        "discovery_reason": "Appeared in Roblox Up-and-Coming",
        "signals": [{"type": "roblox_concurrent_players", "value": players}],
    }


def _page(items, *, fetched_at, next_cursor=None, status="complete"):
    return {
        "status": status,
        "fetched_at": fetched_at,
        "items": items,
        "next_cursor": next_cursor,
        "coverage": {
            "raw_rows": len(items),
            "parsed_items": len(items),
            "page_complete": True,
            "pagination_mode": "opaque_page_token",
            "pagination_complete": next_cursor is None,
        },
    }


def _plan(base: Path) -> Path:
    path = base / "roblox-plan.json"
    path.write_text(json.dumps({
        "schema": "trendgpt-source-plan-v1",
        "sources": [
            {
                "source": "roblox",
                "scope": {"list_type": "up-and-coming", "country": "us", "device": "computer"},
                "page_limit": 2,
                "max_pages": 2,
            },
            {
                "source": "roblox",
                "scope": {"list_type": "top-playing-now", "country": "us", "device": "computer"},
                "page_limit": 2,
                "max_pages": 2,
            },
        ],
    }), encoding="utf-8")
    return path


def _args(root: Path, plan: Path, *, max_pages=2):
    return argparse.Namespace(
        network_enabled=True,
        output_root=str(root),
        max_pages_per_source=max_pages,
        source_plan=str(plan),
        run_id="roblox-dual-board-test",
        date="2026-11-10",
        slot="00",
        timezone="Asia/Shanghai",
        started_at="2026-11-10T00:00:00+08:00",
    )


class RobloxCollectPaginationTests(unittest.TestCase):
    def test_collect_merges_both_boards_and_follows_opaque_page_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            adapter = _PagedRobloxAdapter({
                "up-and-coming": {
                    "first": _page(
                        [_game(101, "Shared Game", local_rank=1), _game(102, "Up Only", local_rank=2)],
                        fetched_at="2026-11-10T00:01:00+00:00",
                        next_cursor="up-page-2",
                        status="partial",
                    ),
                    "up-page-2": _page(
                        [_game(103, "Up Page Two", local_rank=1)],
                        fetched_at="2026-11-10T00:02:00+00:00",
                    ),
                },
                "top-playing-now": {
                    "first": _page(
                        [_game(101, "Shared Game", local_rank=1, players=500), _game(104, "Top Only", local_rank=2)],
                        fetched_at="2026-11-10T00:03:00+00:00",
                        next_cursor="top-page-2",
                        status="partial",
                    ),
                    "top-page-2": _page(
                        [_game(105, "Top Page Two", local_rank=1, players=300)],
                        fetched_at="2026-11-10T00:04:00+00:00",
                    ),
                },
            })
            with patch("trendgpt.cli._make_adapter", return_value=adapter):
                result = _collect(_args(root, _plan(base)))

            self.assertEqual(adapter.calls, [
                ("up-and-coming", None), ("up-and-coming", "up-page-2"),
                ("top-playing-now", None), ("top-playing-now", "top-page-2"),
            ])
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["candidate_count"], 5)
            self.assertEqual(result["source_fetch_calls"], 4)
            for source in result["source_summary"]:
                self.assertTrue(source["pagination_complete"])
                self.assertEqual(source["pages"], 2)
                self.assertEqual(source["pagination_mode"], "opaque_page_token")
                self.assertEqual(source["country"], "us")
                self.assertEqual(source["device"], "computer")

            snapshot = json.loads(Path(result["candidate_path"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["counts"]["raw_records"], 6)
            self.assertEqual(snapshot["counts"]["entities"], 5)
            shared = next(item for item in snapshot["candidates"] if item["canonical_name"] == "Shared Game")
            self.assertEqual(len(shared["sources"]), 2)
            self.assertEqual(
                {item["list_type"] for item in shared["sources"]},
                {"up-and-coming", "top-playing-now"},
            )
            self.assertEqual(
                {item["fetched_at"] for item in shared["sources"]},
                {"2026-11-10T00:01:00+00:00", "2026-11-10T00:03:00+00:00"},
            )
            self.assertEqual(
                {item["sort_id"] for item in shared["source_metadata"]},
                {"up-and-coming", "top-playing-now"},
            )
            self.assertEqual(
                {item["country"] for item in shared["source_metadata"]}, {"us"}
            )
            self.assertEqual(
                {item["device"] for item in shared["source_metadata"]}, {"computer"}
            )
            up_page_two = next(item for item in snapshot["candidates"] if item["canonical_name"] == "Up Page Two")
            self.assertEqual(up_page_two["sources"][0]["position"], 3)
            self.assertEqual(up_page_two["first_self_discovered_at"], "2026-11-10T00:02:00+00:00")
            self.assertEqual(up_page_two["platform_ids"], {"roblox": "103"})

            ledger = EntityFirstSeenLedger(root)
            first_ledger_run = ledger.record_snapshot(snapshot)
            self.assertEqual(first_ledger_run["entities_confirmed"], 5)
            self.assertEqual(first_ledger_run["needs_review"], 0)
            second_ledger_run = ledger.record_snapshot(snapshot)
            self.assertEqual(second_ledger_run["status"], "reused")
            self.assertEqual(ledger.read()["entities"]["platform:roblox:101"]["observation_count"], 1)

    def test_page_cap_keeps_opaque_pagination_partial_and_returns_token(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "output" / "self-v1"
            adapter = _PagedRobloxAdapter({
                "up-and-coming": {
                    "first": _page(
                        [_game(101, "Game A"), _game(102, "Game B")],
                        fetched_at="2026-11-10T00:01:00+00:00",
                        next_cursor="up-page-2",
                        status="partial",
                    ),
                },
                "top-playing-now": {
                    "first": _page(
                        [_game(201, "Game C"), _game(202, "Game D")],
                        fetched_at="2026-11-10T00:02:00+00:00",
                    ),
                },
            })
            with patch("trendgpt.cli._make_adapter", return_value=adapter):
                result = _collect(_args(root, _plan(base), max_pages=1))
        self.assertEqual(result["status"], "partial")
        up_source = next(item for item in result["source_summary"] if item["list_type"] == "up-and-coming")
        self.assertFalse(up_source["pagination_complete"])
        self.assertEqual(up_source["next_cursor"], "up-page-2")
        self.assertEqual(up_source["stop_reason"], "max_pages_reached")


if __name__ == "__main__":
    unittest.main()
