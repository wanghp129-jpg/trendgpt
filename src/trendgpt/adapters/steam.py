"""Steam Recent Releases and Popular New Releases adapter.

Steam's public search filter for the Recent Releases view is newreleases.
The source-plan name recentreleases is retained as a human-readable alias.

Steam may return more rows than a small requested count (the VPS pilot observed
25 rows for count=10). Pagination therefore advances by the number of raw result
rows actually returned, not by the requested count or the number of accepted apps.
"""
from __future__ import annotations

import html
import re
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text

STEAM_BASE = "https://store.steampowered.com"
LIST_FILTERS = {
    "recentreleases": "newreleases",
    "popularnew": "popularnew",
}
APP_PATH_RE = re.compile(r"^/app/(\d+)(?:/|$)")
APP_ID_RE = re.compile(r"^\d+$")
COUNTRY_RE = re.compile(r"^[a-z]{2}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,16}$")
TOTAL_TEXT_RE = re.compile(
    r"showing\s+[\d,]+\s*[-–]\s*[\d,]+\s+of\s+([\d,]+)",
    re.IGNORECASE,
)
REVIEW_RATIO_RE = re.compile(
    r"(?P<pct>\d+(?:[.,]\d+)?)\s*%.*?"
    r"(?P<count>\d[\d,.\s]*)\s+user reviews",
    re.IGNORECASE | re.DOTALL,
)


def _parse_int(value: str | None) -> int | None:
    if not isinstance(value, str):
        return None
    digits = value.strip().replace(",", "")
    return int(digits) if digits.isdigit() else None


def _plain_text(value: str) -> str:
    decoded = html.unescape(value or "")
    decoded = re.sub(r"(?i)<br\s*/?>", " ", decoded)
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    return " ".join(decoded.split())


class _SteamResults(HTMLParser):
    """Parse Steam search_result_row cards and preserve structured row metadata."""

    CAPTURE_CLASSES = {
        "title": "name",
        "search_released": "release_date_text",
        "search_price": "price_text",
        "discount_final_price": "price_final_text",
        "discount_original_price": "price_original_text",
        "discount_pct": "discount_text",
        "search_review_summary": "review_summary_text",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current: dict | None = None
        self.active_captures: list[dict] = []
        self.items: list[dict] = []
        self.total_results: int | None = None
        self.row_count = 0
        self.excluded_non_app_results = 0
        self.invalid_rows = 0
        self.duplicate_app_ids = 0
        self._seen_app_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "div" and attributes.get("id") == "search_results":
            total = _parse_int(attributes.get("data-total-count"))
            if total is not None:
                self.total_results = total

        if tag == "a" and classes.intersection({"search_result_row", "search_result"}):
            if self.current is not None:
                self._finalize_current()
            self.row_count += 1
            self.current = {
                "url": attributes.get("href"),
                "platform": "steam",
                "steam_item_key": attributes.get("data-ds-itemkey"),
                "steam_tag_ids": attributes.get("data-ds-tagids"),
            }
            raw_app_id = attributes.get("data-ds-appid")
            if isinstance(raw_app_id, str) and APP_ID_RE.fullmatch(raw_app_id.strip()):
                self.current["data_app_id"] = raw_app_id.strip()
            self._capture_price_attributes(attributes)
            return

        if self.current is None:
            return

        for capture in self.active_captures:
            capture["depth"] += 1

        self._capture_price_attributes(attributes)

        if "search_review_summary" in classes:
            tooltip = attributes.get("data-tooltip-html") or attributes.get("title")
            if isinstance(tooltip, str) and tooltip.strip():
                self.current["review_tooltip_html"] = tooltip
            rating_classes = sorted(classes - {"search_review_summary"})
            if rating_classes:
                self.current["review_rating_class"] = " ".join(rating_classes)

        for class_name, field_name in self.CAPTURE_CLASSES.items():
            if class_name in classes:
                self.active_captures.append({
                    "field": field_name,
                    "depth": 1,
                    "parts": [],
                })

    def _capture_price_attributes(self, attributes: dict) -> None:
        if self.current is None:
            return
        final_minor = attributes.get("data-price-final")
        if isinstance(final_minor, str) and final_minor.isdigit():
            self.current["price_final_minor_units"] = final_minor
        currency = attributes.get("data-currency")
        if isinstance(currency, str) and currency.strip():
            self.current["price_currency_id"] = currency.strip()
        discount = attributes.get("data-discount")
        if isinstance(discount, str) and discount.isdigit():
            self.current["discount_pct_numeric"] = int(discount)

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        normalized = " ".join(data.split())
        if not normalized:
            return
        for capture in self.active_captures:
            capture["parts"].append(normalized)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return

        completed: list[dict] = []
        for capture in self.active_captures:
            capture["depth"] -= 1
            if capture["depth"] <= 0:
                completed.append(capture)

        for capture in completed:
            value = " ".join(capture["parts"]).strip()
            if value:
                self.current[capture["field"]] = value
            self.active_captures.remove(capture)

        if tag == "a":
            self._finalize_current()

    def _finalize_current(self) -> None:
        item = self.current
        if item is None:
            return
        for capture in self.active_captures:
            value = " ".join(capture["parts"]).strip()
            if value:
                item[capture["field"]] = value
        self.current = None
        self.active_captures = []

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

        tooltip = _plain_text(item.get("review_tooltip_html", ""))
        review_summary = item.get("review_summary_text")
        if not isinstance(review_summary, str) or not review_summary.strip():
            review_summary = item.get("review_rating_class")
        if (not isinstance(review_summary, str) or not review_summary.strip()) and tooltip:
            review_summary = re.split(r"\d+(?:[.,]\d+)?\s*%", tooltip, maxsplit=1)[0].strip()
        if isinstance(review_summary, str) and review_summary.strip():
            item["review_summary"] = review_summary.strip()

        if tooltip:
            item["review_tooltip_text"] = tooltip
            ratio = REVIEW_RATIO_RE.search(tooltip)
            if ratio:
                try:
                    item["review_positive_pct"] = float(ratio.group("pct").replace(",", "."))
                except ValueError:
                    pass
                count = re.sub(r"\D", "", ratio.group("count"))
                if count:
                    item["review_count"] = int(count)

        final_price = item.get("price_final_text")
        if isinstance(final_price, str) and final_price.strip():
            item["price_text"] = final_price.strip()
        elif isinstance(item.get("price_text"), str):
            item["price_text"] = item["price_text"].strip()

        for field_name in ("price_original_text", "discount_text"):
            if isinstance(item.get(field_name), str):
                item[field_name] = item[field_name].strip()

        if item.get("price_original_text"):
            item["price_original"] = item["price_original_text"]
        if item.get("discount_text"):
            item["discount_pct"] = item["discount_text"]

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
        steam_filter = LIST_FILTERS.get(list_type)
        if steam_filter is None:
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
            "filter": steam_filter,
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
            html_text = get_public_text(url, max_bytes=5_000_000)
        except SourceFetchError as exc:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": exc.code, "retryable": exc.retryable}],
            )

        digest = sha256(html_text.encode("utf-8")).hexdigest()
        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        try:
            raw_ref = store_text_evidence(
                html_text,
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
            parser.feed(html_text)
            parser.close()
        except Exception:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                coverage={"url": url, "page_start": start},
                evidence_refs=[raw_ref],
                errors=[{"code": "html_parse_error", "retryable": False}],
            )

        if parser.total_results is None:
            total_match = TOTAL_TEXT_RE.search(_plain_text(html_text))
            if total_match:
                parser.total_results = _parse_int(total_match.group(1))

        items = parser.items
        total = parser.total_results
        expected_rows = None if total is None else max(0, min(page_size, total - start))
        page_count_matches = expected_rows is not None and parser.row_count == expected_rows
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
                "expected_rows": expected_rows,
                "raw_rows": parser.row_count,
                "parsed_apps": len(items),
            })

        next_cursor = None
        if total is not None and start + parser.row_count < total and parser.row_count > 0:
            next_cursor = str(start + parser.row_count)
        elif total is None and parser.row_count == page_size:
            next_cursor = str(start + parser.row_count)

        if not items:
            if total == 0 and parser.row_count == 0 and not errors:
                return SourceResult(
                    self.source_id,
                    "complete",
                    request.fetched_at,
                    {**request.scope, "url": url, "list_type": list_type, "steam_filter": steam_filter},
                    items=[],
                    cursor=str(start),
                    next_cursor=None,
                    coverage={
                        "url": url,
                        "page_start": start,
                        "page_size": page_size,
                        "total_results": 0,
                        "raw_rows": 0,
                        "parsed_items": 0,
                        "page_complete": True,
                        "pagination_complete": True,
                        "steam_filter": steam_filter,
                    },
                    evidence_refs=[raw_ref],
                    errors=[],
                )
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "list_type": list_type, "steam_filter": steam_filter},
                coverage={
                    "page_start": start,
                    "page_size": page_size,
                    "total_results": total,
                    "raw_rows": parser.row_count,
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
            {**request.scope, "url": url, "list_type": list_type, "steam_filter": steam_filter},
            items=[
                {
                    **item,
                    "list_type": list_type,
                    "steam_filter": steam_filter,
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
                "url": url,
                "page_start": start,
                "page_size": page_size,
                "raw_rows": parser.row_count,
                "parsed_items": len(items),
                "total_results": total,
                "expected_rows": expected_rows,
                "page_count_matches": page_count_matches,
                "page_complete": page_complete,
                "pagination_complete": page_complete and next_cursor is None,
                "excluded_non_app_results": parser.excluded_non_app_results,
                "invalid_rows": parser.invalid_rows,
                "duplicate_app_ids": parser.duplicate_app_ids,
                "steam_filter": steam_filter,
                "category_filter": "games (category1=998)",
                "country_code": country_code.lower() if country_code else None,
                "language": language.lower() if language else None,
                "metadata_counts": {
                    "price": sum(bool(item.get("price_text")) for item in items),
                    "review": sum(bool(item.get("review_summary")) for item in items),
                    "discount": sum(bool(item.get("discount_pct")) for item in items),
                },
                "note": (
                    "Pagination advances by raw result-row count. Full source coverage "
                    "still requires traversing every page in one bounded run."
                ),
            },
            errors=errors,
        )
