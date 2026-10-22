"""Roblox public chart-page adapter.

A zero-card parse is blocked rather than reported as an empty complete list. Since
this parser cannot prove pagination completeness, successful pages remain partial.
"""
from __future__ import annotations

from hashlib import sha256
import re
from html.parser import HTMLParser

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text


class _RobloxCards(HTMLParser):
    game_path = re.compile(r"/games/(\d+)(?:/|\?|$)")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href") or ""
            match = self.game_path.search(href)
            if match:
                self.anchor = {
                    "url": "https://www.roblox.com" + href if href.startswith("/") else href,
                    "platform": "roblox",
                    "platform_id": match.group(1),
                    "source_record_id": match.group(1),
                    "name": (attrs.get("title") or attrs.get("aria-label") or "").strip(),
                    "_text": "",
                }

    def handle_data(self, data):
        if self.anchor is not None and data.strip():
            self.anchor["_text"] = (self.anchor.get("_text", "") + " " + data.strip()).strip()

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            name = self.anchor.get("name") or self.anchor.get("_text", "")
            self.anchor.pop("_text", None)
            if name:
                self.anchor["name"] = name
                self.items.append(self.anchor)
            self.anchor = None


class RobloxChartAdapter:
    source_id = "roblox"

    def fetch(self, request: SourceRequest) -> SourceResult:
        list_type = request.scope.get("list_type")
        urls = {
            "up-and-coming": "https://www.roblox.com/charts/up-and-coming?country=us&device=computer",
            "top-playing-now": "https://www.roblox.com/charts/top-playing-now",
        }
        if list_type not in urls:
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                errors=[{"code": "invalid_list_type", "retryable": False}])
        url = urls[list_type]
        try:
            html = get_public_text(url)
        except SourceFetchError as exc:
            return SourceResult(self.source_id, "failed", request.fetched_at, request.scope,
                                errors=[{"code": exc.code, "retryable": exc.retryable}])
        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        try:
            raw_ref = store_text_evidence(
                html, output_root=request.evidence_root,
                relative_path=f"evidence/sources/roblox/{run_key}/{list_type}.html",
                media_type="text/html",
            )
        except StorageError:
            return SourceResult(self.source_id, "failed", request.fetched_at, request.scope,
                                errors=[{"code": "evidence_write_failed", "retryable": False}])
        parser = _RobloxCards()
        parser.feed(html)
        if not parser.items:
            return SourceResult(self.source_id, "blocked", request.fetched_at,
                                {**request.scope, "url": url}, coverage={"pagination_complete": False},
                                evidence_refs=[raw_ref],
                                errors=[{"code": "page_structure_unrecognized_or_no_cards", "retryable": False}])
        for item in parser.items:
            item["list_type"] = list_type
        return SourceResult(
            self.source_id, "partial", request.fetched_at, {**request.scope, "url": url},
            items=parser.items, evidence_refs=[raw_ref],
            coverage={"parsed_items": len(parser.items), "pagination_complete": False,
                      "note": "HTML adapter cannot prove the complete chart was captured"},
        )
