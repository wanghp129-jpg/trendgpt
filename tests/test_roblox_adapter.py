from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from trendgpt.adapters.http import SourceFetchError
from trendgpt.adapters.roblox import RobloxChartAdapter
from trendgpt.sources import SourceRequest


def _request(root: Path, *, list_type="up-and-coming", cursor=None, page_size=2, scope=None):
    return SourceRequest(
        run_id="roblox-test-run",
        source_id="roblox",
        fetched_at="2026-11-10T00:01:00+08:00",
        scope={
            "list_type": list_type,
            "country": "us",
            "device": "computer",
            **(scope or {}),
        },
        evidence_root=str(root),
        cursor=cursor,
        page_limit=page_size,
    )


def _game(universe_id, name, *, place_id=None, players=123, sponsored=False):
    return {
        "universeId": universe_id,
        "rootPlaceId": place_id or universe_id + 1000,
        "name": name,
        "playerCount": players,
        "totalUpVotes": 90,
        "totalDownVotes": 10,
        "isSponsored": sponsored,
        "genreL1": "Simulation",
        "genreL2": "Tycoon",
        "creatorName": "Studio",
    }


class RobloxChartAdapterTests(unittest.TestCase):
    def test_up_and_coming_uses_public_explore_api_and_extracts_universe_identity(self):
        body = {
            "games": [_game(101, "New Experience", place_id=201)],
            "nextPageToken": "opaque-next-token",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)) as fetch:
                result = RobloxChartAdapter().fetch(_request(root))

        result.validate()
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.next_cursor, "opaque-next-token")
        self.assertEqual(result.items[0]["platform"], "roblox")
        self.assertEqual(result.items[0]["platform_id"], "101")
        self.assertEqual(result.items[0]["source_record_id"], "101")
        self.assertEqual(result.items[0]["universe_id"], "101")
        self.assertEqual(result.items[0]["root_place_id"], "201")
        self.assertEqual(result.items[0]["url"], "https://www.roblox.com/games/201")
        self.assertEqual(result.items[0]["player_count"], 123)
        self.assertEqual(result.items[0]["total_up_votes"], 90)
        self.assertEqual(result.items[0]["total_down_votes"], 10)
        self.assertFalse(result.items[0]["is_sponsored"])
        self.assertEqual(result.items[0]["source_rank"], 1)
        self.assertEqual(result.scope["sort_id"], "up-and-coming")
        self.assertEqual(result.coverage["pagination_mode"], "opaque_page_token")
        self.assertTrue(Path(result.evidence_refs[0]["path"]).is_file())

        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["sortId"], ["up-and-coming"])
        self.assertEqual(query["device"], ["computer"])
        self.assertEqual(query["country"], ["us"])
        self.assertEqual(query["maxRows"], ["2"])
        self.assertEqual(len(query["sessionId"][0]), 36)
        self.assertNotIn("pageToken", query)

    def test_top_playing_now_uses_page_token_and_preserves_sponsored_flag(self):
        body = {"games": [_game(501, "Sponsored Experience", sponsored=True)]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)) as fetch:
                result = RobloxChartAdapter().fetch(
                    _request(root, list_type="top-playing-now", cursor="opaque-page-2", page_size=1)
                )
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["sortId"], ["top-playing-now"])
        self.assertEqual(query["pageToken"], ["opaque-page-2"])
        self.assertEqual(result.status, "complete")
        self.assertTrue(result.coverage["pagination_complete"])
        self.assertTrue(result.items[0]["is_sponsored"])
        self.assertEqual(result.items[0]["discovery_reason"], "Appeared in Roblox Top Playing Now")

    def test_same_run_uses_stable_session_id_across_pages(self):
        body = {"games": [_game(101, "Game")], "nextPageToken": "next"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)) as fetch:
                adapter = RobloxChartAdapter()
                adapter.fetch(_request(root))
                adapter.fetch(_request(root, cursor="next"))
        first = parse_qs(urlsplit(fetch.call_args_list[0].args[0]).query)["sessionId"]
        second = parse_qs(urlsplit(fetch.call_args_list[1].args[0]).query)["sessionId"]
        self.assertEqual(first, second)

    def test_invalid_rows_are_reported_and_not_silently_counted(self):
        body = {"games": [_game(101, "Valid Game"), {"universeId": "bad", "name": "Invalid"}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)):
                result = RobloxChartAdapter().fetch(_request(root))
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.coverage["raw_rows"], 2)
        self.assertEqual(result.coverage["invalid_rows"], 1)
        self.assertEqual(result.errors[0]["code"], "invalid_chart_rows")

    def test_duplicate_universe_ids_are_not_emitted_twice(self):
        body = {"games": [_game(101, "Game A"), _game(101, "Game A duplicate")]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)):
                result = RobloxChartAdapter().fetch(_request(root))
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.coverage["duplicate_universe_ids"], 1)
        self.assertEqual(result.status, "partial")

    def test_non_object_rows_are_counted_as_invalid(self):
        body = {"games": [_game(101, "Valid Game"), "unexpected-row"]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value=json.dumps(body)):
                result = RobloxChartAdapter().fetch(_request(root))
        self.assertEqual(result.coverage["raw_rows"], 2)
        self.assertEqual(result.coverage["invalid_rows"], 1)
        self.assertEqual(result.status, "partial")

    def test_retryable_http_failure_is_reported_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch(
                "trendgpt.adapters.roblox.get_public_text",
                side_effect=SourceFetchError("http_error", "HTTP status 429", retryable=True),
            ) as fetch:
                result = RobloxChartAdapter().fetch(_request(root))
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.errors[0]["retryable"])
        fetch.assert_called_once()

    def test_unknown_response_shape_and_empty_games_are_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            with patch("trendgpt.adapters.roblox.get_public_text", return_value='{"unexpected":[]}'):
                unknown = RobloxChartAdapter().fetch(_request(root))
            with patch("trendgpt.adapters.roblox.get_public_text", return_value='{"games":[]}'):
                empty = RobloxChartAdapter().fetch(_request(root))
        self.assertEqual(unknown.status, "blocked")
        self.assertEqual(unknown.errors[0]["code"], "unrecognized_chart_response_shape")
        self.assertEqual(empty.status, "blocked")
        self.assertEqual(empty.errors[0]["code"], "chart_returned_no_usable_games")

    def test_rejects_unknown_sort_and_invalid_scope_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "validation" / "self-v1"
            invalid_sort = RobloxChartAdapter().fetch(_request(root, list_type="top-trending"))
            invalid_sort_type = RobloxChartAdapter().fetch(_request(root, scope={"list_type": []}))
            invalid_country = RobloxChartAdapter().fetch(_request(root, scope={"country": "USA"}))
            invalid_device = RobloxChartAdapter().fetch(_request(root, scope={"device": "mobile"}))
            invalid_device_type = RobloxChartAdapter().fetch(_request(root, scope={"device": ["computer"]}))
            invalid_size = RobloxChartAdapter().fetch(_request(root, page_size=51))
            invalid_token = RobloxChartAdapter().fetch(_request(root, cursor="bad\n token"))
        self.assertEqual(invalid_sort.errors[0]["code"], "invalid_list_type")
        self.assertEqual(invalid_sort_type.errors[0]["code"], "invalid_list_type")
        self.assertEqual(invalid_country.errors[0]["code"], "invalid_country")
        self.assertEqual(invalid_device.errors[0]["code"], "invalid_device")
        self.assertEqual(invalid_device_type.errors[0]["code"], "invalid_device")
        self.assertEqual(invalid_size.errors[0]["code"], "invalid_pagination")
        self.assertEqual(invalid_token.errors[0]["code"], "invalid_page_token")


if __name__ == "__main__":
    unittest.main()
