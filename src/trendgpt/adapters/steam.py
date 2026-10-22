"""Steam recent-release/popular-new-release HTML adapter; one bounded page per call."""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlencode

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text


class _SteamResults(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.capture = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "a" and "search_result" in classes:
            self.current = {"url": attrs.get("href"), "platform": "steam"}
        elif self.current is not None and tag == "span" and "title" in classes:
            self.capture = "name"
            self.current.setdefault("name", "")
        elif self.current is not None and tag == "div" and "search_released" in classes:
            self.capture = "release_date_text"
            self.current.setdefault("release_date_text", "")

    def handle_data(self, data):
        if self.current is not None and self.capture:
            self.current[self.capture] = (self.current.get(self.capture) or "") + data.strip()

    def handle_endtag(self, tag):
        if tag == "span" and self.capture == "name":
            self.capture = None
        elif tag == "div" and self.capture == "release_date_text":
            self.capture = None
        elif tag == "a" and self.current is not None:
            href = self.current.get("url") or ""
            parts = href.split("/app/")
            if len(parts) > 1:
                appid = parts[1].split("/", 1)[0]
                if appid.isdigit() and self.current.get("name", "").strip():
                    self.current["platform_id"] = appid
                    self.current["source_record_id"] = appid
                    self.current["published_at"] = None
                    self.items.append(self.current)
            self.current = None
            self.capture = None


class SteamSearchAdapter:
    source_id = "steam"

    def fetch(self, request: SourceRequest) -> SourceResult:
        list_type = request.scope.get("list_type")
        if list_type not in {"recentreleases", "popularnew"}:
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                errors=[{"code": "invalid_list_type", "retryable": False}])
        try:
            start = int(request.cursor or "0")
            page_size = int(request.page_limit or request.scope.get("page_size", 50))
            if start < 0 or not 1 <= page_size <= 50:
                raise ValueError("start must be non-negative and page size must be 1..50")
        except (TypeError, ValueError) as exc:
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                errors=[{"code": "invalid_pagination", "retryable": False, "message": str(exc)}])
        url = "https://store.steampowered.com/search/?" + urlencode({"filter": list_type, "count": page_size, "start": start})
        try:
            html = get_public_text(url)
        except SourceFetchError as exc:
            return SourceResult(self.source_id, "failed", request.fetched_at, request.scope,
                                errors=[{"code": exc.code, "retryable": exc.retryable}])
        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        try:
            raw_ref = store_text_evidence(
                html, output_root=request.evidence_root,
                relative_path=f"evidence/sources/steam/{run_key}/{list_type}-{start}.html",
                media_type="text/html",
            )
        except StorageError:
            return SourceResult(self.source_id, "failed", request.fetched_at, request.scope,
                                errors=[{"code": "evidence_write_failed", "retryable": False}])
        parser = _SteamResults()
        parser.feed(html)
        items = parser.items
        for item in items:
            item["list_type"] = list_type
        if not items:
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                coverage={"url": url, "page_start": start},
                                evidence_refs=[raw_ref],
                                errors=[{"code": "parse_no_results", "retryable": False}])
        next_cursor = str(start + len(items)) if len(items) >= page_size else None
        return SourceResult(
            self.source_id, "partial", request.fetched_at,
            {**request.scope, "url": url, "list_type": list_type}, items=items,
            cursor=str(start), next_cursor=next_cursor, evidence_refs=[raw_ref],
            coverage={"page_start": start, "page_size": page_size, "parsed_items": len(items),
                      "pagination_complete": False,
                      "note": "HTML parser has not verified source total or full pagination"},
        )
