"""YouTube recent-search RSS adapter used only as a supplementary clue source.

Video titles are not assumed to be game names. Identity extraction/review is a
separate stage; this adapter preserves the original video record.
"""
from __future__ import annotations

from urllib.parse import urlencode
from xml.etree import ElementTree

from ..sources import SourceRequest, SourceResult
from .http import SourceFetchError, get_public_text


class YouTubeRssAdapter:
    source_id = "youtube"

    def fetch(self, request: SourceRequest) -> SourceResult:
        query = request.scope.get("query")
        if not isinstance(query, str) or not query.strip():
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                errors=[{"code": "query_required", "retryable": False}])
        url = "https://www.youtube.com/feeds/videos.xml?" + urlencode({"search_query": query})
        try:
            xml = get_public_text(url, max_bytes=2_000_000)
            root = ElementTree.fromstring(xml)
        except SourceFetchError as exc:
            return SourceResult(self.source_id, "failed", request.fetched_at, request.scope,
                                errors=[{"code": exc.code, "retryable": exc.retryable}])
        except ElementTree.ParseError:
            return SourceResult(self.source_id, "blocked", request.fetched_at, request.scope,
                                errors=[{"code": "invalid_feed_xml", "retryable": False}])

        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        items = []
        for entry in root.findall("atom:entry", ns):
            video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
            title = entry.findtext("atom:title", default="", namespaces=ns)
            published = entry.findtext("atom:published", default="", namespaces=ns)
            author = entry.findtext("atom:author/atom:name", default="", namespaces=ns)
            if not video_id or not title:
                continue
            items.append({
                "title": title,
                "source_record_id": video_id,
                "platform": "youtube_video",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published or None,
                "author": author or None,
                "query": query,
                "identity_status": "unresolved_video_title",
            })
        if not items:
            return SourceResult(self.source_id, "partial", request.fetched_at,
                                {**request.scope, "url": url}, items=[],
                                coverage={"feed_limit": 15, "parsed_items": 0, "identity_resolved": False},
                                errors=[{"code": "feed_empty_or_schema_changed", "retryable": False}])
        return SourceResult(
            self.source_id, "partial", request.fetched_at, {**request.scope, "url": url},
            items=items,
            coverage={"feed_limit": 15, "parsed_items": len(items), "identity_resolved": False,
                      "note": "RSS results are supplementary clues, not verified game entities"},
        )
