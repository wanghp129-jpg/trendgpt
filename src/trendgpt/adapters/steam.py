"""Steam Recent Releases and Popular New Releases adapter.

The adapter reads one bounded Steam search page per call. It preserves the raw
HTML, uses stable Steam AppIDs, applies Steam's Games category filter, and only
claims page completeness when the page's declared total matches parsed rows.
A bounded multi-page run is still partial unless the entire declared result set
was traversed without gaps or duplicate AppIDs.
"""
from __future__ import annotations

import re
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text

STEAM_BASE = "https://store.steampowered.com"
LIST_TYPES = {"recentreleases", "popularnew"}
APP_PATH_RE = re.compile(r"^/app/(\d+)(?:/|$)")
APP_ID_RE = re.compile(r"^\d+$")
COUNTRY_RE = re.compile(r"^[a-z]{2}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,16}$")


class _SteamResults(HTMLParser):
    """Parse Steam search_result_row cards and the search_results total count."""

    CAPTURE_CLASSES = {
        "title": "name",
        "search_released": "release_date_text",
        "search_price": "price_text",
        "search_reviewscore": "review_summary",
        "search_discount": "discount_text",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: dict | None = None
        self.capture: str | None = None
        self.capture_depth = 0
        self.capture_parts: list[str] = []
        self.items: list[dict] = []
        self.total_results: int | None = None
        self.excluded_non_app_results = 0
        self.invalid_rows = 0
        self.duplicate_app_ids = 0
        self._seen_app_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "div" and attributes.get("id") == "search_results":
            total = attributes.get("data-total-count")
            if isinstance(total, str) and total.isdigit():
                self.total_results = int(total)

        if tag == "a" and classes.intersection({"search_result_row", "search_result"}):
            if self.current is not None:
                self._finalize_current()
            self.current = {
                "url": attributes.get("href"),
                "platform": "steam",
                "steam_item_key": attributes.get("data-ds-itemkey"),
                "steam_tag_ids": attributes.get("data-ds-tagids"),
            }
            raw_app_id = attributes.get("data-ds-appid")
            if isinstance(raw_app_id, str) and APP_ID_RE.fullmatch(raw_app_id.strip()):
                self.current["data_app_id"] = raw_app_id.strip()
            return

        if self.current is None:
            return

        if self.capture is not None:
            self.capture_depth += 1
            return

        for class_name, field_name in self.CAPTURE_CLASSES.items():
            if class_name in classes:
                self.capture = field_name
                self.capture_depth = 1
                self.capture_parts = []
                break

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.capture is not None:
            normalized = " ".join(data.split())
            if normalized:
                self.capture_parts.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        if self.capture is not None:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                if self.current is not None:
                    self.current[self.capture] = " ".join(self.capture_parts).strip()
                self.capture = None
                self.capture_depth = 0
                self.capture_parts = []

        if tag == "a" and self.current is not None and self.capture is None:
            self._finalize_current()

    def _finalize_current(self) -> None:
        item = self.current
        self.current = None
        self.capture = None
        self.capture_depth = 0
        self.capture_parts = []
        if item is None:
            return

        raw_url = item.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            self.invalid_rows += 1
            return
        absolute_url = urljoin(STEAM_BASE + "/", raw_url.strip())
        parsed = urlsplit(absolute_url)
        if parsed.scheme != "https" or parsed.hostname != "store.steampowered.com":
            self.invalid_rows += 1
            return

        path_match = APP_PATH_RE.match(parsed.path)
        if path_match is None:
            self.excluded_non_app_results += 1
            return
        path_app_id = path_match.group(1)
        data_app_id = item.pop("data_app_id", None)
        if data_app_id is not None and data_app_id != path_app_id:
            self.invalid_rows += 1
            return
        app_id = path_app_id

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            self.invalid_rows += 1
            return
        if app_id in self._seen_app_ids:
            self.duplicate_app_ids += 1
            return
        self._seen_app_ids.add(app_id)

        item.pop("url", None)
        item["name"] = name.strip()
        item["url"] = absolute_url
        item["platform_id"] = app_id
        item["source_record_id"] = app_id
        item["published_at"] = None
        item["release_date_iso"] = None
        item["release_date_precision"] = "unparsed"
        item["result_kind"] = "steam_app"
        self.items.append(item)


class SteamSearchAdapter:
    source_id = "steam"

    def fetch(self, request: SourceRequest) -> SourceResult:
        list_type = request.scope.get("list_type")
        if list_type not in LIST_TYPES:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_list_type", "retryable": False}],
            )

        try:
            start = int(request.cursor or "0")
            page_size = int(request.page_limit if request.page_limit is not None else request.scope.get("page_size", 50))
            if start < 0 or not 1 <= page_size <= 50:
                raise ValueError("start must be non-negative and page size must be 1..50")
        except (TypeError, ValueError) as exc:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_pagination", "retryable": False, "message": str(exc)}],
            )

        country_code = request.scope.get("country_code")
        language = request.scope.get("language")
        if country_code is not None and (
            not isinstance(country_code, str) or not COUNTRY_RE.fullmatch(country_code.lower())
        ):
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_country_code", "retryable": False}],
            )
        if language is not None and (
            not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language.lower())
        ):
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_language", "retryable": False}],
            )

        query = {
            "filter": list_type,
            "count": page_size,
            "start": start,
            "category1": 998,
        }
        if country_code:
            query["cc"] = country_code.lower()
        if language:
            query["l"] = language.lower()
        url = f"{STEAM_BASE}/search/?{urlencode(query)}"

        try:
            html = get_public_text(url, max_bytes=5_000_000)
        except SourceFetchError as exc:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": exc.code, "retryable": exc.retryable}],
            )

        digest = sha256(html.encode("utf-8")).hexdigest()
        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        try:
            raw_ref = store_text_evidence(
                html,
                output_root=request.evidence_root,
                relative_path=f"evidence/sources/steam/{run_key}/{list_type}-{start}-{digest[:16]}.html",
                media_type="text/html",
            )
        except StorageError:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": "evidence_write_failed", "retryable": False}],
            )

        parser = _SteamResults()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                coverage={"url": url, "page_start": start},
                evidence_refs=[raw_ref],
                errors=[{"code": "html_parse_error", "retryable": False}],
            )

        items = parser.items
        total = parser.total_results
        expected_items = None if total is None else max(0, min(page_size, total - start))
        page_count_matches = expected_items is not None and len(items) == expected_items
        page_complete = (
            page_count_matches
            and parser.invalid_rows == 0
            and parser.duplicate_app_ids == 0
            and parser.excluded_non_app_results == 0
        )

        errors = []
        if parser.invalid_rows:
            errors.append({
                "code": "invalid_result_rows",
                "retryable": False,
                "count": parser.invalid_rows,
            })
        if parser.duplicate_app_ids:
            errors.append({
                "code": "duplicate_app_ids_within_page",
                "retryable": False,
                "count": parser.duplicate_app_ids,
            })
        if parser.excluded_non_app_results:
            errors.append({
                "code": "non_app_results_excluded",
                "retryable": False,
                "count": parser.excluded_non_app_results,
            })
        if total is not None and not page_count_matches:
            errors.append({
                "code": "page_count_mismatch",
                "retryable": False,
                "expected_items": expected_items,
                "parsed_items": len(items),
            })

        next_cursor = None
        if page_complete and total is not None and start + len(items) < total:
            next_cursor = str(start + len(items))
        elif total is None and len(items) == page_size:
            next_cursor = str(start + len(items))

        if not items:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "list_type": list_type},
                coverage={
                    "page_start": start,
                    "page_size": page_size,
                    "total_results": total,
                    "parsed_items": 0,
                    "pagination_complete": False,
                },
                evidence_refs=[raw_ref],
                errors=errors or [{"code": "parse_no_results", "retryable": False}],
            )

        status = "complete" if page_complete and next_cursor is None else "partial"
        return SourceResult(
            self.source_id,
            status,
            request.fetched_at,
            {**request.scope, "url": url, "list_type": list_type},
            items=[
                {
                    **item,
                    "list_type": list_type,
                    "discovery_reason": (
                        "Appeared in Steam Recent Releases"
                        if list_type == "recentreleases"
                        else "Appeared in Steam Popular New Releases"
                    ),
                }
                for item in items
            ],
            cursor=str(start),
            next_cursor=next_cursor,
            evidence_refs=[raw_ref],
            coverage={
                "page_start": start,
                "page_size": page_size,
                "parsed_items": len(items),
                "total_results": total,
                "expected_items": expected_items,
                "page_count_matches": page_count_matches,
                "page_complete": page_complete,
                "pagination_complete": page_complete and next_cursor is None,
                "excluded_non_app_results": parser.excluded_non_app_results,
                "invalid_rows": parser.invalid_rows,
                "duplicate_app_ids": parser.duplicate_app_ids,
                "category_filter": "games (category1=998)",
                "country_code": country_code.lower() if country_code else None,
                "language": language.lower() if language else None,
                "note": (
                    "Steam total count and this page's parsed rows are reconciled; "
                    "full source coverage still requires traversing every page in one bounded run."
                ),
            },
            errors=errors,
        )
