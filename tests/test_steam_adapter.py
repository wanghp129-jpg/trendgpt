from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from trendgpt.adapters.steam import SteamSearchAdapter, _SteamResults
from trendgpt.sources import SourceRequest


def _card(app_id: str, name: str, release_date: str) -> str:
    return f"""
    <a class="search_result_row ds_collapse_flag"
       data-ds-appid="{app_id}"
       data-ds-itemkey="App_{app_id}"
       href="/app/{app_id}/game-slug/">
      <div class="responsive_search_name_combined">
        <div class="search_name ellipsis"><span class="title">{name}</span></div>
        <div class="search_released">{release_date}</div>
        <div class="search_price">US$ 4.99</div>
      </div>
    </a>
    """


def _request(root: Path, *, cursor=None, page_size=2, scope=None) -> SourceRequest:
    return SourceRequest(
        run_id="steam-validation-run",
        source_id="steam",
        fetched_at="2026-11-10T00:01:00+08:00",
        scope={"list_type": "recentreleases", **(scope or {})},
        evidence_root=str(root),
        cursor=cursor,
        page_limit=page_size,
    )


class SteamParserTests(unittest.TestCase):
    def test_parses_real_search_result_row_markup_and_total_count(self):
        html = (
            '<div id="search_results" data-total-count="2">'
            + _card("12345", "Deep Rock Galactic", "Nov 9, 2026")
            + _card("67890", "Small Studio Game", "Nov 8, 2026")
            + "</div>"
        )
        parser = _SteamResults()
        parser.feed(html)
        parser.close()

        self.assertEqual(parser.total_results, 2)
        self.assertEqual([item["platform_id"] for item in parser.items], ["12345", "67890"])
        self.assertEqual(parser.items[0]["name"], "Deep Rock Galactic")
        self.assertEqual(parser.items[0]["release_date_text"], "Nov 9, 2026")
        self.assertEqual(parser.items[0]["price_text"], "US$ 4.99")
        self.assertEqual(parser.items[0]["steam_item_key"], "App_12345")
        self.assertEqual(parser.items[0]["result_kind"], "steam_app")

    def test_excludes_package_paths_and_rejects_app_id_mismatch(self):
        html = """
        <a class="search_result_row" href="/sub/111/collection/">
          <span class="title">Package</span>
        </a>
        <a class="search_result_row" data-ds-appid="999"
           href="/app/12345/game/">
          <span class="title">Mismatched App</span>
        </a>
        """
        parser = _SteamResults()
        parser.feed(html)
        parser.close()

        self.assertEqual(parser.items, [])
        self.assertEqual(parser.excluded_non_app_results, 1)
        self.assertEqual(parser.invalid_rows, 1)

    def test_duplicate_app_id_within_page_is_not_emitted_twice(self):
        html = (
            '<div id="search_results" data-total-count="2">'
            + _card("12345", "Game A", "Nov 9, 2026")
            + _card("12345", "Game A", "Nov 9, 2026")
            + "</div>"
        )
        parser = _SteamResults()
        parser.feed(html)
        parser.close()

        self.assertEqual(len(parser.items), 1)
        self.assertEqual(parser.duplicate_app_ids, 1)


class SteamAdapterTests(unittest.TestCase):
    def test_builds_games_filtered_url_and_exposes_next_page_cursor(self):
        html = (
            '<div id="search_results" data-total-count="3">'
            + _card("12345", "Game A", "Nov 9, 2026")
            + _card("67890", "Game B", "Nov 8, 2026")
            + "</div>"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html) as fetch:
                result = SteamSearchAdapter().fetch(
                    _request(root, page_size=2, scope={"country_code": "us", "language": "english"})
                )

            result.validate()
            self.assertEqual(result.status, "partial")
            self.assertEqual(result.next_cursor, "2")
            self.assertTrue(result.coverage["page_complete"])
            self.assertFalse(result.coverage["pagination_complete"])
            self.assertEqual(len(result.items), 2)
            self.assertTrue(Path(result.evidence_refs[0]["path"]).is_file())

            query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
            self.assertEqual(query["filter"], ["recentreleases"])
            self.assertEqual(query["count"], ["2"])
            self.assertEqual(query["start"], ["0"])
            self.assertEqual(query["category1"], ["998"])
            self.assertEqual(query["cc"], ["us"])
            self.assertEqual(query["l"], ["english"])

    def test_final_page_is_complete_only_when_declared_total_matches(self):
        html = (
            '<div id="search_results" data-total-count="3">'
            + _card("33333", "Game C", "Nov 7, 2026")
            + "</div>"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            result = SteamSearchAdapter().fetch(_request(root, cursor="2", page_size=2))
        self.assertEqual(result.status, "complete", msg=f"coverage={result.coverage!r}; errors={result.errors!r}; items={len(result.items)}")
        self.assertIsNone(result.next_cursor)
        self.assertTrue(result.coverage["page_complete"])
        self.assertTrue(result.coverage["pagination_complete"])

    def test_missing_total_never_claims_complete_even_when_page_looks_short(self):
        html = _card("12345", "Game A", "Nov 9, 2026")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            result = SteamSearchAdapter().fetch(_request(root, page_size=2))
        self.assertEqual(result.status, "partial")
        self.assertIsNone(result.next_cursor)
        self.assertIsNone(result.coverage["total_results"])
        self.assertFalse(result.coverage["page_complete"])
        self.assertFalse(result.coverage["pagination_complete"])

    def test_rejects_invalid_page_size_and_country_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            invalid_size = SteamSearchAdapter().fetch(_request(root, page_size=0))
            invalid_country = SteamSearchAdapter().fetch(
                _request(root, scope={"country_code": "USA"})
            )
        self.assertEqual(invalid_size.status, "blocked")
        self.assertEqual(invalid_size.errors[0]["code"], "invalid_pagination")
        self.assertEqual(invalid_country.status, "blocked")
        self.assertEqual(invalid_country.errors[0]["code"], "invalid_country_code")

    def test_zero_parse_is_blocked_not_reported_as_empty_complete_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value="<html>changed page</html>"):
                result = SteamSearchAdapter().fetch(_request(root))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.errors[0]["code"], "parse_no_results")


if __name__ == "__main__":
    unittest.main()
