"""Roblox Up-and-Coming and Top Playing Now public chart adapter.

Uses Roblox's anonymous Explore API, not HTML scraping, browser sessions,
cookies, CSRF tokens, third-party proxies, or authenticated Open Cloud.

The Explore response is an observed web contract, not a stable Open Cloud SLA.
Only the public chart rows supplied by the endpoint are claimed; this is not a
crawl of all Roblox experiences. Opaque page tokens are followed only within
the caller's explicit page budget.
"""
from __future__ import annotations

import json
import re
import uuid
from hashlib import sha256
from urllib.parse import urlencode

from ..sources import SourceRequest, SourceResult
from ..storage import StorageError, store_text_evidence
from .http import SourceFetchError, get_public_text

ROBLOX_EXPLORE_BASE = "https://apis.roblox.com/explore-api/v1/get-sort-content"
SORT_IDS = {
    "up-and-coming": "up-and-coming",
    "top-playing-now": "top-playing-now",
}
COUNTRY_RE = re.compile(r"^(?:[a-z]{2}|all)$")
ALLOWED_DEVICES = {"computer", "phone", "tablet", "all", "console"}
MAX_PAGE_ROWS = 50
MAX_PAGE_TOKEN_LENGTH = 1024


def _positive_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return value
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None




def _response_scope(body: object) -> tuple[str | None, str | None, str]:
    """Read only explicit response scope declarations; never infer from request params."""
    if not isinstance(body, dict):
        return None, None, "unverified"
    containers = [body]
    for key in ("scope", "request", "filters", "metadata", "context"):
        value = body.get(key)
        if isinstance(value, dict):
            containers.append(value)
    country = device = None
    for container in containers:
        if country is None:
            for key in ("country", "countryCode", "region", "regionCode"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    country = value.strip().lower()
                    break
        if device is None:
            for key in ("device", "deviceType", "platform"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    device = value.strip().lower()
                    break
    if country is None or device is None:
        return country, device, "unverified"
    return country, device, "declared"

def _extract_game_rows(body: object) -> tuple[list[object], str | None]:
    """Accept known observed list containers, but never recursively guess rows."""
    if not isinstance(body, dict):
        return [], None
    for key in ("games", "content", "sortContent", "results"):
        value = body.get(key)
        if isinstance(value, list):
            return value, key
    data = body.get("data")
    if isinstance(data, list):
        return data, "data"
    if isinstance(data, dict):
        for key in ("games", "content", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value, f"data.{key}"
    return [], None


def _parse_game(row: dict, *, list_type: str, position: int) -> dict | None:
    universe_id = _positive_id(row.get("universeId"))
    name = row.get("name") or row.get("title")
    if universe_id is None or not isinstance(name, str) or not name.strip():
        return None

    root_place_id = _positive_id(row.get("rootPlaceId") or row.get("placeId"))
    player_count = _non_negative_int(row.get("playerCount"))
    up_votes = _non_negative_int(row.get("totalUpVotes"))
    down_votes = _non_negative_int(row.get("totalDownVotes"))
    if up_votes is None:
        up_votes = _non_negative_int(row.get("upVotes"))
    if down_votes is None:
        down_votes = _non_negative_int(row.get("downVotes"))

    source_rank = _positive_id(row.get("positionInPage")) or str(position + 1)
    item = {
        "name": name.strip(),
        "platform": "roblox",
        "platform_id": universe_id,
        "source_record_id": universe_id,
        "universe_id": universe_id,
        "root_place_id": root_place_id,
        "url": f"https://www.roblox.com/games/{root_place_id}" if root_place_id else None,
        "list_type": list_type,
        "sort_id": SORT_IDS[list_type],
        "source_rank": int(source_rank),
        "player_count": player_count,
        "playerCount": player_count,
        "total_up_votes": up_votes,
        "total_down_votes": down_votes,
        "is_sponsored": row.get("isSponsored") if isinstance(row.get("isSponsored"), bool) else None,
        "genre_l1": row.get("genreL1") if isinstance(row.get("genreL1"), str) else None,
        "genre_l2": row.get("genreL2") if isinstance(row.get("genreL2"), str) else None,
        "creator_name": row.get("creatorName") if isinstance(row.get("creatorName"), str) else None,
        "discovery_reason": (
            "Appeared in Roblox Up-and-Coming"
            if list_type == "up-and-coming"
            else "Appeared in Roblox Top Playing Now"
        ),
        "signals": [],
    }
    if player_count is not None:
        item["signals"].append({"type": "roblox_concurrent_players", "value": player_count})
    if up_votes is not None:
        item["signals"].append({"type": "roblox_up_votes", "value": up_votes})
    if down_votes is not None:
        item["signals"].append({"type": "roblox_down_votes", "value": down_votes})
    return item


class RobloxChartAdapter:
    source_id = "roblox"

    def fetch(self, request: SourceRequest) -> SourceResult:
        list_type = request.scope.get("list_type")
        sort_id = SORT_IDS.get(list_type) if isinstance(list_type, str) else None
        if sort_id is None:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_list_type", "retryable": False}],
            )

        country = request.scope.get("country", "us")
        device = request.scope.get("device", "computer")
        if not isinstance(country, str) or not COUNTRY_RE.fullmatch(country.lower()):
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_country", "retryable": False}],
            )
        if not isinstance(device, str) or device not in ALLOWED_DEVICES:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_device", "retryable": False}],
            )
        try:
            page_size = int(request.page_limit if request.page_limit is not None else request.scope.get("page_size", 50))
            if not 1 <= page_size <= MAX_PAGE_ROWS:
                raise ValueError("page size must be between 1 and 50")
        except (TypeError, ValueError) as exc:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_pagination", "retryable": False, "message": str(exc)}],
            )

        page_token = request.cursor
        if page_token is not None and (
            not isinstance(page_token, str)
            or not page_token
            or len(page_token) > MAX_PAGE_TOKEN_LENGTH
            or any(ord(char) < 32 for char in page_token)
        ):
            return SourceResult(
                self.source_id, "blocked", request.fetched_at, request.scope,
                errors=[{"code": "invalid_page_token", "retryable": False}],
            )

        # Stable opaque session identifier across the pages of this source run.
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"trendgpt:{request.run_id}"))
        params = {
            "sessionId": session_id,
            "sortId": sort_id,
            "device": device,
            "country": country.lower(),
            "maxRows": page_size,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        url = f"{ROBLOX_EXPLORE_BASE}?{urlencode(params)}"

        try:
            raw_text = get_public_text(url, max_bytes=5_000_000)
        except SourceFetchError as exc:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": exc.code, "retryable": exc.retryable}],
            )

        run_key = sha256(request.run_id.encode("utf-8")).hexdigest()[:16]
        cursor_key = "first" if page_token is None else sha256(page_token.encode("utf-8")).hexdigest()[:12]
        digest = sha256(raw_text.encode("utf-8")).hexdigest()
        try:
            raw_ref = store_text_evidence(
                raw_text,
                output_root=request.evidence_root,
                relative_path=f"evidence/sources/roblox/{run_key}/{list_type}-{cursor_key}-{digest[:16]}.json",
                media_type="application/json",
            )
        except StorageError:
            return SourceResult(
                self.source_id, "failed", request.fetched_at, request.scope,
                errors=[{"code": "evidence_write_failed", "retryable": False}],
            )

        try:
            body = json.loads(raw_text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (json.JSONDecodeError, ValueError):
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "sort_id": sort_id},
                coverage={"pagination_mode": "opaque_page_token", "page_token_used": page_token is not None},
                evidence_refs=[raw_ref],
                errors=[{"code": "invalid_json_response", "retryable": False}],
            )

        effective_country, effective_device, response_scope_status = _response_scope(body)
        requested_country = country.lower()
        requested_device = device
        scope_matches = (
            effective_country == requested_country
            and effective_device == requested_device
        ) if response_scope_status == "declared" else False
        scope_verification = (
            "matched" if scope_matches else
            "mismatch" if response_scope_status == "declared" else
            "unverified"
        )
        rows, payload_path = _extract_game_rows(body)
        if payload_path is None:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "sort_id": sort_id},
                coverage={"response_keys": sorted(body.keys()) if isinstance(body, dict) else [], "pagination_mode": "opaque_page_token"},
                evidence_refs=[raw_ref],
                errors=[{"code": "unrecognized_chart_response_shape", "retryable": False}],
            )

        items: list[dict] = []
        seen_ids: set[str] = set()
        invalid_rows = 0
        duplicate_ids = 0
        # The Explore endpoint may ignore maxRows and return a larger chart payload.
        # Never pass more than the configured limit into candidate normalization.
        overflow_rows = max(0, len(rows) - page_size)
        accepted_rows = rows[:page_size]
        for position, row in enumerate(accepted_rows):
            if not isinstance(row, dict):
                invalid_rows += 1
                continue
            item = _parse_game(row, list_type=list_type, position=position)
            if item is None:
                invalid_rows += 1
                continue
            if item["platform_id"] in seen_ids:
                duplicate_ids += 1
                continue
            seen_ids.add(item["platform_id"])
            items.append(item)

        raw_next_token = body.get("nextPageToken") if isinstance(body, dict) else None
        if raw_next_token is None and isinstance(body, dict):
            raw_next_token = body.get("nextPageCursor")
        errors: list[dict] = []
        next_cursor = None
        reported_next_token_present = isinstance(raw_next_token, str) and bool(raw_next_token)
        if overflow_rows:
            errors.append({
                "code": "response_exceeds_max_rows",
                "retryable": False,
                "requested_max_rows": page_size,
                "raw_rows": len(rows),
                "accepted_rows": len(accepted_rows),
                "overflow_rows": overflow_rows,
            })
            # A server token may start after the oversized response. Following it
            # after truncating this page would silently skip the overflow rows.
            next_cursor = None
        elif raw_next_token is not None:
            if isinstance(raw_next_token, str) and raw_next_token and len(raw_next_token) <= MAX_PAGE_TOKEN_LENGTH and not any(ord(char) < 32 for char in raw_next_token):
                next_cursor = raw_next_token
            elif raw_next_token not in ("", None):
                errors.append({"code": "invalid_next_page_token", "retryable": False})
        if invalid_rows:
            errors.append({"code": "invalid_chart_rows", "retryable": False, "count": invalid_rows})
        if duplicate_ids:
            errors.append({"code": "duplicate_universe_ids_within_page", "retryable": False, "count": duplicate_ids})

        page_complete = (
            bool(rows) and overflow_rows == 0
            and invalid_rows == 0 and duplicate_ids == 0
            and len(items) == len(accepted_rows)
        )
        pagination_complete = page_complete and next_cursor is None and not errors

        if not items:
            return SourceResult(
                self.source_id, "blocked", request.fetched_at,
                {**request.scope, "url": url, "sort_id": sort_id},
                cursor=page_token,
                next_cursor=next_cursor,
                coverage={
                    "payload_path": payload_path,
                    "page_size": page_size,
                    "raw_rows": len(rows),
                    "parsed_items": 0,
                    "invalid_rows": invalid_rows,
                    "duplicate_universe_ids": duplicate_ids,
                    "pagination_mode": "opaque_page_token",
                    "pagination_complete": False,
                },
                evidence_refs=[raw_ref],
                errors=errors or [{"code": "chart_returned_no_usable_games", "retryable": False}],
            )

        status = "complete" if pagination_complete and scope_verification == "matched" else "partial"
        for item in items:
            item["country"] = effective_country
            item["device"] = effective_device
            item["requested_country"] = requested_country
            item["requested_device"] = requested_device
            item["scope_verification"] = scope_verification
        return SourceResult(
            self.source_id,
            status,
            request.fetched_at,
            {
                **request.scope,
                "url": url,
                "sort_id": sort_id,
                "country": effective_country,
                "device": effective_device,
                "requested_country": requested_country,
                "requested_device": requested_device,
                "response_scope_status": response_scope_status,
                "scope_verification": scope_verification,
                "max_rows": page_size,
                "pagination_mode": "opaque_page_token",
            },
            items=items,
            cursor=page_token,
            next_cursor=next_cursor,
            coverage={
                "payload_path": payload_path,
                "page_size": page_size,
                "requested_max_rows": page_size,
                "raw_rows": len(rows),
                "accepted_rows": len(accepted_rows),
                "overflow_rows": overflow_rows,
                "parsed_items": len(items),
                "reported_next_page_token_present": reported_next_token_present,
                "requested_country": requested_country,
                "requested_device": requested_device,
                "effective_country": effective_country,
                "effective_device": effective_device,
                "scope_verification": scope_verification,
                "invalid_rows": invalid_rows,
                "duplicate_universe_ids": duplicate_ids,
                "page_complete": page_complete,
                "pagination_mode": "opaque_page_token",
                "next_page_token_present": next_cursor is not None,
                "pagination_complete": pagination_complete,
                "chart_scope": "Roblox public chart snapshot; not a full catalog crawl",
                "note": "Only games returned by Roblox's selected chart are represented; missing games are not evidence of nonexistence.",
            },
            evidence_refs=[raw_ref],
            errors=errors,
        )
