"""YouTube recent-upload search adapter for supplementary game-discovery clues.

Follows Lesson 14's YouTube search URL pattern with the upload-date filter.
This is not a YouTube Data API client and does not require credentials.

Important: video titles are clues, not verified game entities. This adapter
preserves video/channel evidence and deliberately does not set candidate_name.
The shared candidate normalizer therefore keeps these rows in unparsed_items
until a separate identity-resolution step identifies a game.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from urllib.parse import urlencode
from typing import Any

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
UPLOAD_DATE_FILTER = "EgQIAhAB"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_QUERY_LENGTH = 200


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        simple = value.get("simpleText")
        if isinstance(simple, str) and simple.strip():
            return simple.strip()
        runs = value.get("runs")
        if isinstance(runs, list):
            parts = [
                run.get("text", "")
                for run in runs
                if isinstance(run, dict) and isinstance(run.get("text"), str)
            ]
            combined = "".join(parts).strip()
            return combined or None
    return None


def _extract_initial_data(page_html: str) -> dict[str, Any] | None:
    """Decode ytInitialData without evaluating page JavaScript."""
    markers = (
        "var ytInitialData =",
        "ytInitialData =",
        'window["ytInitialData"] =',
        "window['ytInitialData'] =",
    )
    decoder = json.JSONDecoder()
    for marker in markers:
        position = page_html.find(marker)
        if position < 0:
            continue
        start = page_html.find("{", position + len(marker))
        if start < 0:
            continue
        try:
            value, _ = decoder.raw_decode(page_html[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _find_primary_contents(data: dict[str, Any]) -> object | None:
    stack: list[object] = [data]
    visited = 0
    while stack and visited < 250_000:
        node = stack.pop()
        visited += 1
        if isinstance(node, dict):
            two_column = node.get("twoColumnSearchResultsRenderer")
            if isinstance(two_column, dict):
                primary = two_column.get("primaryContents")
                if primary is not None:
                    return primary
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _collect_renderers(primary: object) -> tuple[list[dict[str, Any]], bool]:
    stack: list[object] = [primary]
    videos: list[dict[str, Any]] = []
    seen: set[str] = set()
    continuation_present = False
    visited = 0
    while stack and visited < 250_000:
        node = stack.pop()
        visited += 1
        if isinstance(node, dict):
            renderer = node.get("videoRenderer")
            if isinstance(renderer, dict):
                video_id = renderer.get("videoId")
                if isinstance(video_id, str) and video_id not in seen:
                    seen.add(video_id)
                    videos.append(renderer)
            if "continuationItemRenderer" in node:
                continuation_present = True
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return videos, continuation_present


def _extract_description_snippet(
    renderer: dict[str, Any],
) -> tuple[str | None, list[str], str | None, list[str | None]]:
    """Extract a search-result description excerpt without claiming it is complete."""
    direct = _text_value(renderer.get("descriptionSnippet"))
    if direct:
        return direct, [direct], "descriptionSnippet", []

    detailed = renderer.get("detailedMetadataSnippets")
    parts: list[str] = []
    hover_texts: list[str | None] = []
    if isinstance(detailed, list):
        for entry in detailed:
            if not isinstance(entry, dict):
                continue
            text = _text_value(entry.get("snippetText"))
            if not text:
                continue
            parts.append(text)
            hover_texts.append(_text_value(entry.get("snippetHoverText")))

    if not parts:
        return None, [], None, []
    return "\n".join(parts), parts, "detailedMetadataSnippets[].snippetText", hover_texts


def _parse_video(renderer: dict[str, Any], *, query: str, query_role: str | None, rank: int) -> dict[str, Any] | None:
    video_id = renderer.get("videoId")
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        return None

    title = _text_value(renderer.get("title"))
    if not title:
        return None

    owner = renderer.get("ownerText") or renderer.get("longBylineText")
    channel_name = _text_value(owner)
    channel_id = None
    channel_url = None
    if isinstance(owner, dict):
        runs = owner.get("runs")
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, dict):
                    continue
                endpoint = run.get("navigationEndpoint")
                browse = endpoint.get("browseEndpoint") if isinstance(endpoint, dict) else None
                if isinstance(browse, dict):
                    candidate_id = browse.get("browseId")
                    if isinstance(candidate_id, str) and candidate_id.startswith("UC"):
                        channel_id = candidate_id
                        channel_url = f"https://www.youtube.com/channel/{candidate_id}"
                        break

    published_text = _text_value(renderer.get("publishedTimeText"))
    (
        description,
        description_parts,
        description_source,
        description_hover_texts,
    ) = _extract_description_snippet(renderer)
    duration = _text_value(renderer.get("lengthText"))
    views = _text_value(renderer.get("viewCountText"))
    thumbnails = renderer.get("thumbnail", {}).get("thumbnails", []) if isinstance(renderer.get("thumbnail"), dict) else []
    thumbnail_url = None
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict) and isinstance(thumbnail.get("url"), str):
                thumbnail_url = thumbnail["url"]
                break

    return {
        "title": title,
        "video_id": video_id,
        "source_record_id": video_id,
        "platform": "youtube_video",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "channel_name": channel_name,
        "channel_id": channel_id,
        "channel_url": channel_url,
        "published_time_text": published_text,
        # The page provides relative display text, not a trustworthy absolute timestamp.
        "published_at": None,
        "duration_text": duration,
        "view_count_text": views,
        "description_snippet": description,
        "description_snippet_parts": description_parts,
        "description_snippet_source": description_source,
        "description_snippet_completeness": (
            "search_result_excerpt" if description else "unavailable"
        ),
        "description_snippet_hover_texts": description_hover_texts,
        "thumbnail_url": thumbnail_url,
        "query": query,
        "query_role": query_role,
        "search_filter": UPLOAD_DATE_FILTER,
        "source_rank": rank,
        "identity_status": "unresolved_video_title",
        "discovery_reason": "Recent YouTube upload matched a supplementary game-discovery query",
    }


class YouTubeSearchAdapter:
    source_id = "youtube"

    def fetch(self, request: SourceRequest) -> SourceResult:
        query = request.scope.get("query")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > MAX_QUERY_LENGTH:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_query", "retryable": False}],
            )
        query = query.strip()
        upload_filter = request.scope.get("upload_filter", UPLOAD_DATE_FILTER)
        if upload_filter != UPLOAD_DATE_FILTER:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_upload_filter", "retryable": False}],
            )
        try:
            page_limit = int(request.page_limit if request.page_limit is not None else request.scope.get("page_size", 15))
            if not 1 <= page_limit <= 50:
                raise ValueError("page size must be between 1 and 50")
        except (TypeError, ValueError) as exc:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_pagination", "retryable": False, "message": str(exc)}],
            )
        if request.cursor is not None:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "youtube_search_continuation_not_supported", "retryable": False}],
            )

        url = f"{YOUTUBE_SEARCH_URL}?{urlencode({'search_query': query, 'sp': upload_filter})}"
        try:
            page_html = get_public_text(url, max_bytes=5_000_000)
        except SourceFetchError as exc:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": exc.code, "retryable": exc.retryable}],
            )

        digest = sha256(page_html.encode("utf-8")).hexdigest()
        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        query_key = sha256(query.encode("utf-8")).hexdigest()[:12]
        try:
            raw_ref = store_text_evidence(
                page_html,
                output_root=request.evidence_root,
                relative_path=f"evidence/sources/youtube/{run_key}/{query_key}-{digest[:16]}.html",
                media_type="text/html",
            )
        except StorageError:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": "evidence_write_failed", "retryable": False}],
            )

        initial_data = _extract_initial_data(page_html)
        if initial_data is None:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "search_filter": UPLOAD_DATE_FILTER},
                evidence_refs=[raw_ref],
                errors=[{"code": "youtube_initial_data_missing", "retryable": False}],
            )
        primary = _find_primary_contents(initial_data)
        if primary is None:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "search_filter": UPLOAD_DATE_FILTER},
                evidence_refs=[raw_ref],
                errors=[{"code": "youtube_search_results_missing", "retryable": False}],
            )

        renderers, continuation_present = _collect_renderers(primary)
        raw_video_count = len(renderers)
        accepted_renderers = renderers[:page_limit]
        items: list[dict[str, Any]] = []
        invalid_rows = 0
        for index, renderer in enumerate(accepted_renderers):
            item = _parse_video(
                renderer, query=query,
                query_role=request.scope.get("query_role") if isinstance(request.scope.get("query_role"), str) else None,
                rank=index + 1,
            )
            if item is None:
                invalid_rows += 1
                continue
            items.append(item)

        overflow_rows = max(0, raw_video_count - page_limit)
        errors: list[dict[str, Any]] = []
        if overflow_rows:
            errors.append({
                "code": "youtube_response_exceeds_page_limit",
                "retryable": False,
                "raw_video_results": raw_video_count,
                "accepted_rows": page_limit,
                "overflow_rows": overflow_rows,
            })
        if invalid_rows:
            errors.append({"code": "invalid_video_rows", "retryable": False, "count": invalid_rows})

        status = "partial"
        if not items:
            status = "blocked"
            if not errors:
                errors.append({"code": "youtube_search_returned_no_usable_videos", "retryable": False})

        return SourceResult(
            self.source_id,
            status,
            request.fetched_at,
            {
                **request.scope,
                "url": url,
                "search_filter": UPLOAD_DATE_FILTER,
                "filter_source": "request_query_parameter",
                "pagination_mode": "single_page_recent_upload_search",
                "identity_resolution": "unresolved_video_title",
            },
            items=items,
            cursor=None,
            next_cursor=None,
            coverage={
                "page_size": page_limit,
                "raw_video_results": raw_video_count,
                "accepted_rows": len(items),
                "overflow_rows": overflow_rows,
                "invalid_rows": invalid_rows,
                "continuation_present": continuation_present,
                "pagination_mode": "single_page_recent_upload_search",
                "pagination_complete": False,
                "search_filter": UPLOAD_DATE_FILTER,
                "filter_source": "request_query_parameter",
                "response_filter_status": "unverified",
                "identity_resolved": False,
                "published_at_precision": "relative_text_only",
                "note": "Supplementary recent-upload clues only; titles are not asserted to be game entities and this is not full YouTube search coverage.",
            },
            evidence_refs=[raw_ref],
            errors=errors,
        )
