"""Provider-neutral source contracts; no network calls occur in this module."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


SOURCE_STATUSES = {"complete", "partial", "failed", "blocked"}
DISCOVERY_ORIGINS = {"self_discovered", "external_supplement"}


@dataclass(frozen=True)
class SourceRequest:
    run_id: str
    source_id: str
    fetched_at: str
    scope: dict[str, Any]
    evidence_root: str
    cursor: str | None = None
    page_limit: int | None = None
    since: str | None = None


@dataclass
class SourceResult:
    source_id: str
    status: str
    fetched_at: str
    scope: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    cursor: str | None = None
    next_cursor: str | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> "SourceResult":
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"invalid source status: {self.status}")
        if not isinstance(self.items, list) or not all(isinstance(item, dict) for item in self.items):
            raise ValueError("items must be an array of objects")
        if self.status == "complete" and self.errors:
            raise ValueError("complete source result cannot contain unresolved errors")
        if self.status == "complete" and self.next_cursor:
            raise ValueError("complete source result cannot have an unconsumed next_cursor")
        if self.status in {"failed", "blocked"} and not self.errors:
            raise ValueError("failed/blocked source result must include an error")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


class SourceAdapter(Protocol):
    source_id: str

    def fetch(self, request: SourceRequest) -> SourceResult:
        """Fetch one bounded page and preserve original source records."""
        ...


def merge_source_results(
    source_results: list[SourceResult],
    *,
    run_id: str,
    run_date: str,
    slot: str,
    timezone: str,
    started_at: str,
    collected_at: str,
    cutoff_at: str,
    code_version: str,
    normalization_version: str,
    source_policy_version: str,
) -> dict[str, Any]:
    """Build a candidate snapshot without injecting API/manual candidates.

    Stable IDs are deduplicated only within a source/platform identity. Same-name
    records across platforms remain separate until an explicit entity mapping exists.
    """
    from hashlib import sha256
    from .normalize import normalize_name

    normalized_results = [result.validate() for result in source_results]
    source_runs, candidates, seen = [], [], {}
    raw_records = parsed_records = unparsed_records = 0

    for result in normalized_results:
        source_runs.append({
            "source_id": result.source_id,
            "status": result.status,
            "scope": result.scope,
            "fetched_at": result.fetched_at,
            "cursor": result.cursor,
            "next_cursor": result.next_cursor,
            "coverage": result.coverage,
            "errors": result.errors,
            "raw_evidence_refs": result.evidence_refs,
        })
        for position, raw in enumerate(result.items):
            raw_records += 1
            title = raw.get("title") or raw.get("name") or raw.get("keyword")
            source_record_id = raw.get("source_record_id") or raw.get("platform_id") or raw.get("id")
            platform = raw.get("platform") or result.source_id
            if not isinstance(title, str) or not title.strip():
                unparsed_records += 1
                continue
            parsed_records += 1
            identity = f"{platform}:{source_record_id}" if source_record_id is not None else f"{result.source_id}:{normalize_name(title)}:{position}"
            candidate_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
            if identity in seen:
                candidate = seen[identity]
                candidate["raw_titles"].append(title)
                candidate["sources"].append({
                    "source_id": result.source_id,
                    "source_record_id": str(source_record_id) if source_record_id is not None else None,
                    "position": position,
                    "fetched_at": result.fetched_at,
                    "url": raw.get("url"),
                })
                continue
            candidate = {
                "candidate_id": candidate_id,
                "entity_id": f"provisional:{candidate_id}",
                "canonical_name": title.strip(),
                "aliases": [],
                "raw_titles": [title],
                "entity_resolution": {"status": "provisional", "method": "source_record_identity", "confidence": None},
                "platforms": [str(platform)],
                "platform_ids": {str(platform): str(source_record_id)} if source_record_id is not None else {},
                "discovery_origin": "self_discovered",
                "origin_events": [{
                    "origin": "self_discovered",
                    "source_id": result.source_id,
                    "observed_at": result.fetched_at,
                    "run_id": run_id,
                }],
                "first_discovered_at": result.fetched_at,
                "first_self_discovered_at": result.fetched_at,
                "independent_eligibility": {"eligible": True, "reason": "source-observed-before-benchmark-exposure"},
                "sources": [{
                    "source_id": result.source_id,
                    "source_record_id": str(source_record_id) if source_record_id is not None else None,
                    "position": position,
                    "fetched_at": result.fetched_at,
                    "url": raw.get("url"),
                    "list_type": raw.get("list_type"),
                    "published_at": raw.get("published_at"),
                }],
                "platform_signals": raw.get("signals", []) if isinstance(raw.get("signals", []), list) else [],
                "discovery_reasons": [str(raw.get("discovery_reason") or f"observed in {result.source_id}")],
                "raw_evidence_refs": result.evidence_refs,
                "missing_fields": [],
            }
            seen[identity] = candidate
            candidates.append(candidate)

    statuses = {result.status for result in normalized_results}
    if not normalized_results or statuses <= {"failed", "blocked"}:
        collection_status, completeness = "failed", "unknown"
    elif statuses == {"complete"}:
        collection_status, completeness = "complete", "complete"
    else:
        collection_status, completeness = "partial", "partial"

    return {
        "schema": "self-candidate-keywords-v1",
        "run_id": run_id,
        "date": run_date,
        "slot": slot,
        "timezone": timezone,
        "started_at": started_at,
        "collected_at": collected_at,
        "cutoff_at": cutoff_at,
        "code_version": code_version,
        "normalization_version": normalization_version,
        "source_policy_version": source_policy_version,
        "collection_status": collection_status,
        "completeness": completeness,
        "source_runs": source_runs,
        "candidates": candidates,
        "counts": {
            "raw_records": raw_records,
            "parsed_records": parsed_records,
            "unparsed_records": unparsed_records,
            "entities": len(candidates),
        },
    }
