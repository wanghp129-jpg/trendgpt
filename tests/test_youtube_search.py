from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from trendgpt.adapters.youtube_search import (
    UPLOAD_DATE_FILTER,
    YouTubeSearchAdapter,
)
from trendgpt.cli import _make_adapter
from trendgpt.contracts import validate_candidate_snapshot
from trendgpt.sources import SourceRequest, merge_source_results


def _video(video_id: str, title: str, *, channel_id="UCabcdefghijk") -> dict:
    return {
        "videoRenderer": {
            "videoId": video_id,
            "title": {"runs": [{"text": title}]},
            "ownerText": {
                "runs": [{
                    "text": "Indie Studio",
                    "navigationEndpoint": {
                        "browseEndpoint": {"browseId": channel_id}
                    },
                }]
            },
            "publishedTimeText": {"simpleText": "2 hours ago"},
            "viewCountText": {"simpleText": "1.2K views"},
            "lengthText": {"simpleText": "12:34"},
            "descriptionSnippet": {"runs": [{"text": "Official gameplay reveal"}]},
            "thumbnail": {"thumbnails": [{"url": "https://i.ytimg.com/vi/example/default.jpg"}]},
        }
    }


def _page(*videos: dict, continuation=False) -> str:
    contents = [{"itemSectionRenderer": {"contents": list(videos)}}]
    if continuation:
        contents[0]["itemSectionRenderer"]["contents"].append(
            {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "opaque"}}}}
        )
    data = {
        "contents": {
            "twoColumnSearchResultsRenderer": {
                "primaryContents": {"sectionListRenderer": {"contents": contents}}
            }
        }
    }
    return "<html><script>var ytInitialData = " + json.dumps(data) + ";</script></html>"


def _request(root: Path, *, query="releasedategameplay", query_role=None, page_size=15) -> SourceRequest:
    return SourceRequest(
        run_id="youtube-test-run",
        source_id="youtube",
        fetched_at="2026-11-10T00:01:00+08:00",
        scope={"query": query, "query_role": query_role},
        evidence_root=str(root),
        page_limit=page_size,
    )


class YouTubeSearchAdapterTests(unittest.TestCase):
    def test_cli_dispatch_uses_recent_upload_search_adapter(self):
        self.assertIsInstance(_make_adapter("youtube"), YouTubeSearchAdapter)

    def test_builds_recent_upload_search_and_preserves_video_channel_evidence(self):
        html = _page(_video("abcdefghijk", "New Game Official Gameplay Trailer"), continuation=True)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html) as fetch:
                result = YouTubeSearchAdapter().fetch(_request(root, query_role="release_date_gameplay"))
            self.assertTrue(Path(result.evidence_refs[0]["path"]).is_file())

        result.validate()
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item["video_id"], "abcdefghijk")
        self.assertEqual(item["source_record_id"], "abcdefghijk")
        self.assertEqual(item["platform"], "youtube_video")
        self.assertEqual(item["title"], "New Game Official Gameplay Trailer")
        self.assertEqual(item["channel_id"], "UCabcdefghijk")
        self.assertEqual(item["channel_name"], "Indie Studio")
        self.assertEqual(item["published_time_text"], "2 hours ago")
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["search_filter"], UPLOAD_DATE_FILTER)
        self.assertEqual(item["query_role"], "release_date_gameplay")
        self.assertEqual(item["identity_status"], "unresolved_video_title")
        self.assertEqual(item["description_snippet"], "Official gameplay reveal")
        self.assertEqual(item["description_snippet_source"], "descriptionSnippet")
        self.assertEqual(item["description_snippet_completeness"], "search_result_excerpt")
        self.assertEqual(item["description_snippet_parts"], ["Official gameplay reveal"])
        self.assertNotIn("candidate_name", item)
        self.assertTrue(result.coverage["continuation_present"])
        self.assertFalse(result.coverage["identity_resolved"])
        self.assertEqual(result.coverage["response_filter_status"], "unverified")

        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query["search_query"], ["releasedategameplay"])
        self.assertEqual(query["sp"], [UPLOAD_DATE_FILTER])

    def test_falls_back_to_detailed_metadata_snippets_and_preserves_excerpt_provenance(self):
        renderer = _video("abcdefghijk", "Path of Exile 2 gameplay")["videoRenderer"]
        renderer["descriptionSnippet"] = ""
        renderer["detailedMetadataSnippets"] = [
            {
                "snippetText": {"runs": [
                    {"text": "Path of Exile 2 "},
                    {"text": "features "},
                    {"text": "new classes"},
                ]},
                "snippetHoverText": {"simpleText": "From the video description"},
            },
            {
                "snippetText": {"simpleText": "Shadow and Duelist gameplay"},
                "snippetHoverText": {"runs": [{"text": "From the video description"}]},
            },
        ]
        renderer["expandableMetadata"] = {
            "expandableMetadataRenderer": {
                "header": {"expandedTitle": "AI-generated video summary"},
                "expandedContent": {
                    "videoSummaryContentViewModel": {"text": "AI summary must stay separate"}
                },
            }
        }
        renderer["chapters"] = [{"title": "Chapter One"}]
        html = _page({"videoRenderer": renderer})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html) as fetch:
                result = YouTubeSearchAdapter().fetch(_request(root))
            fetch.assert_called_once()

        item = result.items[0]
        expected = "Path of Exile 2 features new classes\nShadow and Duelist gameplay"
        self.assertEqual(item["description_snippet"], expected)
        self.assertEqual(
            item["description_snippet_parts"],
            ["Path of Exile 2 features new classes", "Shadow and Duelist gameplay"],
        )
        self.assertEqual(item["description_snippet_source"], "detailedMetadataSnippets[].snippetText")
        self.assertEqual(item["description_snippet_completeness"], "search_result_excerpt")
        self.assertEqual(
            item["description_snippet_hover_texts"],
            ["From the video description", "From the video description"],
        )
        self.assertNotIn("AI summary must stay separate", item["description_snippet"])
        self.assertNotIn("Chapter One", item["description_snippet"])
        self.assertNotIn("candidate_name", item)

        snapshot = validate_candidate_snapshot(merge_source_results(
            [result],
            run_id="youtube-test-run",
            run_date="2026-11-10",
            slot="00",
            timezone="Asia/Shanghai",
            started_at="2026-11-10T00:00:00+08:00",
            collected_at="2026-11-10T00:01:00+08:00",
            cutoff_at="2026-11-10T00:02:00+08:00",
            code_version="test",
            normalization_version="test",
            source_policy_version="test",
        ))
        clue = snapshot["unparsed_items"][0]
        self.assertEqual(clue["raw_record"]["description_snippet"], expected)
        self.assertEqual(clue["raw_record"]["description_snippet_parts"], item["description_snippet_parts"])

    def test_prefers_nonempty_description_snippet_over_detailed_metadata_snippets(self):
        renderer = _video("abcdefghijk", "Game One Gameplay")["videoRenderer"]
        renderer["detailedMetadataSnippets"] = [{
            "snippetText": {"simpleText": "Fallback excerpt"},
            "snippetHoverText": {"simpleText": "From the video description"},
        }]
        html = _page({"videoRenderer": renderer})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html):
                result = YouTubeSearchAdapter().fetch(_request(root))

        item = result.items[0]
        self.assertEqual(item["description_snippet"], "Official gameplay reveal")
        self.assertEqual(item["description_snippet_source"], "descriptionSnippet")
        self.assertEqual(item["description_snippet_parts"], ["Official gameplay reveal"])

    def test_marks_description_unavailable_when_both_search_excerpt_fields_are_missing(self):
        renderer = _video("abcdefghijk", "Game One Gameplay")["videoRenderer"]
        renderer.pop("descriptionSnippet")
        renderer.pop("detailedMetadataSnippets", None)
        html = _page({"videoRenderer": renderer})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html):
                result = YouTubeSearchAdapter().fetch(_request(root))

        item = result.items[0]
        self.assertIsNone(item["description_snippet"])
        self.assertEqual(item["description_snippet_parts"], [])
        self.assertIsNone(item["description_snippet_source"])
        self.assertEqual(item["description_snippet_completeness"], "unavailable")
        self.assertEqual(item["description_snippet_hover_texts"], [])

    def test_video_titles_remain_unparsed_clues_not_game_candidates(self):
        html = _page(_video("abcdefghijk", "NEW GAME Official Gameplay Trailer"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html):
                result = YouTubeSearchAdapter().fetch(
                    _request(root, query="upcominggame gameplay", query_role="upcoming_gameplay")
                )
        snapshot = validate_candidate_snapshot(merge_source_results(
            [result],
            run_id="youtube-test-run",
            run_date="2026-11-10",
            slot="00",
            timezone="Asia/Shanghai",
            started_at="2026-11-10T00:00:00+08:00",
            collected_at="2026-11-10T00:01:00+08:00",
            cutoff_at="2026-11-10T00:02:00+08:00",
            code_version="test",
            normalization_version="test",
            source_policy_version="test",
        ))
        self.assertEqual(snapshot["candidates"], [])
        self.assertEqual(snapshot["counts"]["unparsed_records"], 1)
        clue = snapshot["unparsed_items"][0]
        self.assertEqual(clue["raw_record"]["title"], "NEW GAME Official Gameplay Trailer")
        self.assertEqual(clue["raw_record"]["query_role"], "upcoming_gameplay")
        self.assertTrue(clue["raw_evidence_refs"])

    def test_uses_page_limit_and_reports_overflow_without_claiming_full_coverage(self):
        html = _page(
            _video("abcdefghijk", "Game One Gameplay"),
            _video("lmnopqrstuv", "Game Two Reveal"),
            continuation=True,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value=html):
                result = YouTubeSearchAdapter().fetch(_request(root, page_size=1))

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["title"], "Game One Gameplay")
        self.assertEqual(result.coverage["raw_video_results"], 2)
        self.assertEqual(result.coverage["accepted_rows"], 1)
        self.assertEqual(result.coverage["overflow_rows"], 1)
        self.assertFalse(result.coverage["pagination_complete"])
        self.assertIsNone(result.next_cursor)
        self.assertEqual(result.errors[0]["code"], "youtube_response_exceeds_page_limit")
        self.assertEqual(result.status, "partial")

    def test_missing_initial_data_is_blocked_and_raw_page_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            with patch("trendgpt.adapters.youtube_search.get_public_text", return_value="<html>challenge</html>"):
                result = YouTubeSearchAdapter().fetch(_request(root))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.errors[0]["code"], "youtube_initial_data_missing")
        self.assertTrue(result.evidence_refs)

    def test_rejects_invalid_query_page_size_and_continuation_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "self-v1"
            adapter = YouTubeSearchAdapter()
            invalid_query = adapter.fetch(_request(root, query=" "))
            invalid_size = adapter.fetch(_request(root, page_size=51))
            invalid_filter = adapter.fetch(
                SourceRequest(
                    run_id="youtube-test-run", source_id="youtube",
                    fetched_at="2026-11-10T00:01:00+08:00",
                    scope={"query": "upcominggame gameplay", "upload_filter": "invalid"},
                    evidence_root=str(root), page_limit=15,
                )
            )
            continuation = adapter.fetch(
                SourceRequest(
                    run_id="youtube-test-run",
                    source_id="youtube",
                    fetched_at="2026-11-10T00:01:00+08:00",
                    scope={"query": "upcominggame gameplay"},
                    evidence_root=str(root),
                    cursor="opaque-token",
                    page_limit=15,
                )
            )
        self.assertEqual(invalid_query.errors[0]["code"], "invalid_query")
        self.assertEqual(invalid_size.errors[0]["code"], "invalid_pagination")
        self.assertEqual(invalid_filter.errors[0]["code"], "invalid_upload_filter")
        self.assertEqual(continuation.errors[0]["code"], "youtube_search_continuation_not_supported")


if __name__ == "__main__":
    unittest.main()
