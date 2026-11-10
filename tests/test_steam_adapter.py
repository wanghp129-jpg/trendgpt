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
       data-ds-tagids="19,492"
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
        self.assertEqual(parser.row_count, 2)
        self.assertEqual([item["platform_id"] for item in parser.items], ["12345", "67890"])
        self.assertEqual(parser.items[0]["name"], "Deep Rock Galactic")
        self.assertEqual(parser.items[0]["release_date_text"], "Nov 9, 2026")
        self.assertEqual(parser.items[0]["price_text"], "US$ 4.99")
        self.assertEqual(parser.items[0]["steam_item_key"], "App_12345")
        self.assertEqual(parser.items[0]["steam_tag_ids"], "19,492")
        self.assertEqual(parser.items[0]["result_kind"], "steam_app")

    def test_extracts_nested_price_discount_and_review_tooltip_metadata(self):
        html = """
        <div id="search_results" data-total-count="1">
          <a class="search_result_row" data-ds-appid="12345"
             href="/app/12345/game/">
            <span class="title">Metadata Game</span>
            <div class="search_released">Nov 9, 2026</div>
            <span class="search_review_summary positive"
              data-tooltip-html="Very Positive&lt;br&gt;94% of the 427,532 user reviews for this game are positive.">Very Positive</span>
            <div class="discount_block" data-price-final="1599" data-currency="1" data-discount="20">
              <div class="discount_pct">-20%</div>
              <div class="discount_original_price">$19.99</div>
              <div class="discount_final_price">$15.99</div>
            </div>
          </a>
        </div>
        """
        parser = _SteamResults()
        parser.feed(html)
        parser.close()

        self.assertEqual(len(parser.items), 1)
        item = parser.items[0]
        self.assertEqual(item["price_text"], "$15.99")
        self.assertEqual(item["price_final_text"], "$15.99")
        self.assertEqual(item["price_original_text"], "$19.99")
        self.assertEqual(item["price_original"], "$19.99")
        self.assertEqual(item["discount_text"], "-20%")
        self.assertEqual(item["discount_pct"], "-20%")
        self.assertEqual(item["price_final_minor_units"], "1599")
        self.assertEqual(item["price_currency_id"], "1")
        self.assertEqual(item["discount_pct_numeric"], 20)
        self.assertEqual(item["review_summary"], "Very Positive")
        self.assertEqual(item["review_summary_source"], "tooltip_label")
        self.assertEqual(item["review_rating_class"], "positive")
        self.assertEqual(item["review_positive_pct"], 94.0)
        self.assertEqual(item["review_count"], 427532)

    def test_visible_review_label_is_used_when_tooltip_is_absent(self):
        html = """
        <div id="search_results" data-total-count="1">
          <a class="search_result_row" data-ds-appid="54320" href="/app/54320/game/">
            <span class="title">Visible Rating Game</span>
            <span class="search_review_summary positive">Mostly Positive</span>
          </a>
        </div>
        """
        parser = _SteamResults()
        parser.feed(html)
        parser.close()
        item = parser.items[0]
        self.assertEqual(item["review_summary"], "Mostly Positive")
        self.assertEqual(item["review_summary_source"], "visible_text")
        self.assertEqual(item["review_rating_class"], "positive")

    def test_exact_rating_label_comes_from_tooltip_not_css_class(self):
        html = """
        <div id="search_results" data-total-count="1">
          <a class="search_result_row" data-ds-appid="54321" href="/app/54321/game/">
            <span class="title">Tooltip Rating Game</span>
            <span class="search_review_summary positive"
              data-tooltip-html="Very Positive&lt;br&gt;94% of the 427,532 user reviews for this game are positive."></span>
          </a>
        </div>
        """
        parser = _SteamResults()
        parser.feed(html)
        parser.close()
        item = parser.items[0]
        self.assertEqual(item["review_summary"], "Very Positive")
        self.assertEqual(item["review_summary_source"], "tooltip_label")
        self.assertEqual(item["review_rating_class"], "positive")
        self.assertEqual(item["review_positive_pct"], 94.0)
        self.assertEqual(item["review_count"], 427532)

    def test_parses_total_count_from_visible_pagination_text(self):
        html = (
            "<html><body>showing 1 - 1 of 75"
            + _card("12345", "Game A", "Nov 9, 2026")
            + "</body></html>"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html):
                result = SteamSearchAdapter().fetch(_request(root, page_size=1))
        self.assertEqual(result.coverage["total_results"], 75)
        self.assertEqual(result.next_cursor, "1")
        self.assertEqual(result.status, "partial")

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
        self.assertEqual(parser.row_count, 2)


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
            self.assertEqual(result.scope["steam_filter"], "newreleases")
            self.assertEqual(result.scope["filter"], "newreleases")
            self.assertEqual(result.scope["filter_source"], "request_query_parameter")
            self.assertEqual(result.items[0]["filter"], "newreleases")
            self.assertEqual(result.items[0]["filter_source"], "request_query_parameter")
            self.assertTrue(Path(result.evidence_refs[0]["path"]).is_file())

            query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
            self.assertEqual(query["filter"], ["newreleases"])
            self.assertEqual(query["count"], ["2"])
            self.assertEqual(query["start"], ["0"])
            self.assertEqual(query["category1"], ["998"])
            self.assertEqual(query["cc"], ["us"])
            self.assertEqual(query["l"], ["english"])

    def test_recent_releases_alias_uses_steam_newreleases_filter(self):
        html = (
            '<div id="search_results" data-total-count="1">'
            + _card("12345", "Game A", "Nov 9, 2026")
            + "</div>"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html) as fetch:
                result = SteamSearchAdapter().fetch(_request(root, page_size=1))
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.items[0]["steam_filter"], "newreleases")
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)["filter"], ["newreleases"])

    def test_actual_25_rows_for_requested_10_advances_by_observed_rows(self):
        html = '<div id="search_results" data-total-count="50">' + "".join(
            _card(str(10000 + i), f"Game {i}", "Nov 9, 2026") for i in range(25)
        ) + "</div>"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html) as fetch:
                result = SteamSearchAdapter().fetch(_request(root, page_size=10))
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["count"], ["10"])
        self.assertEqual(result.coverage["raw_rows"], 25)
        self.assertEqual(len(result.items), 25)
        self.assertEqual(result.next_cursor, "25")
        self.assertEqual(result.status, "partial")
        self.assertFalse(result.coverage["page_count_matches"])

    def test_configured_25_row_page_advances_to_offset_25(self):
        html = '<div id="search_results" data-total-count="50">' + "".join(
            _card(str(20000 + i), f"Game {i}", "Nov 9, 2026") for i in range(25)
        ) + "</div>"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html) as fetch:
                result = SteamSearchAdapter().fetch(_request(root, page_size=25))
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)["count"], ["25"])
        self.assertEqual(result.coverage["raw_rows"], 25)
        self.assertTrue(result.coverage["page_complete"])
        self.assertEqual(result.next_cursor, "25")
        self.assertEqual(result.status, "partial")

    def test_final_page_is_complete_only_when_declared_total_matches(self):
        html = (
            '<div id="search_results" data-total-count="3">'
            + _card("33333", "Game C", "Nov 7, 2026")
            + "</div>"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html):
                result = SteamSearchAdapter().fetch(_request(root, cursor="2", page_size=2))
        self.assertEqual(result.status, "complete", msg=f"coverage={result.coverage!r}; errors={result.errors!r}; items={len(result.items)}")
        self.assertIsNone(result.next_cursor)
        self.assertTrue(result.coverage["page_complete"])
        self.assertTrue(result.coverage["pagination_complete"])

    def test_missing_total_never_claims_complete_even_when_page_looks_short(self):
        html = _card("12345", "Game A", "Nov 9, 2026")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html):
                result = SteamSearchAdapter().fetch(_request(root, page_size=2))
        self.assertEqual(result.status, "partial")
        self.assertIsNone(result.next_cursor)
        self.assertIsNone(result.coverage["total_results"])
        self.assertFalse(result.coverage["page_complete"])
        self.assertFalse(result.coverage["pagination_complete"])

    def test_zero_total_and_zero_rows_is_a_valid_empty_source(self):
        html = '<div id="search_results" data-total-count="0"></div>'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "output" / "self-v1"
            with patch("trendgpt.adapters.steam.get_public_text", return_value=html):
                result = SteamSearchAdapter().fetch(_request(root))
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.items, [])
        self.assertTrue(result.coverage["pagination_complete"])

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
