"""API benchmark comparison; benchmark records never enter self-discovery data."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .normalize import resolve_exact


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def adjudicate_independence(
    candidate: dict[str, Any],
    *,
    first_api_observed_at: str,
    evidence_ref: dict[str, Any],
    adjudicated_by: str,
) -> dict[str, Any]:
    """Mark relative observation independence only with an explicit timestamp and evidence.

    This does not prove provider generation time when the API omits it. The recorded
    conclusion is deliberately limited to 'self observed before local API observation'.
    """
    api_seen = _parse_time(first_api_observed_at)
    ref_path = evidence_ref.get("path") if isinstance(evidence_ref, dict) else None
    ref_hash = evidence_ref.get("sha256") if isinstance(evidence_ref, dict) else None
    if not isinstance(ref_path, str) or not ref_path.startswith("/") or not isinstance(ref_hash, str) or len(ref_hash) != 64:
        raise ValueError("an absolute evidence path and SHA-256 digest are required")
    if not isinstance(adjudicated_by, str) or not adjudicated_by.strip():
        raise ValueError("adjudicated_by is required")
    result = deepcopy(candidate)
    first_self = result.get("first_self_discovered_at")
    eligibility = {
        "eligible": False,
        "reason": "missing_self_discovery_timestamp",
        "method": "manual_evidence_adjudication",
        "first_api_observed_at": first_api_observed_at,
        "evidence_ref": {"path": ref_path, "sha256": ref_hash},
        "adjudicated_by": adjudicated_by,
    }
    if isinstance(first_self, str):
        try:
            eligible = _parse_time(first_self) <= api_seen
        except ValueError:
            eligible = False
            eligibility["reason"] = "invalid_self_discovery_timestamp"
        else:
            eligibility["eligible"] = eligible
            eligibility["reason"] = (
                "self_observed_before_local_api_observation"
                if eligible else "api_observed_before_or_at_self_discovery"
            )
    result["independent_eligibility"] = eligibility
    return result


def _self_eligible(candidate: dict[str, Any], cutoff: datetime) -> bool:
    if candidate.get("discovery_origin") != "self_discovered":
        return False
    eligibility = candidate.get("independent_eligibility") or {}
    if eligibility.get("eligible") is not True:
        return False
    first_seen = candidate.get("first_self_discovered_at")
    if not isinstance(first_seen, str):
        return False
    try:
        return _parse_time(first_seen) <= cutoff
    except ValueError:
        return False


def compare_snapshots(
    benchmark: dict[str, Any],
    self_snapshots: list[dict[str, Any]],
    *,
    cutoff: str,
    benchmark_enabled: bool = True,
) -> dict[str, Any]:
    """Compare immutable snapshots conservatively; unusable benchmark => null coverage."""
    cutoff_dt = _parse_time(cutoff)
    if not benchmark_enabled:
        return {
            "status": "disabled", "denominator": None, "matched": None,
            "missed": None, "ambiguous": None, "independent_coverage": None,
            "matches": [], "limitations": ["benchmark comparison is disabled"],
        }

    completeness = benchmark.get("completeness") or {}
    update = benchmark.get("update_confirmation") or {}
    records = benchmark.get("normalized_records")
    ready = (
        benchmark.get("evaluation_status") == "ready"
        and benchmark.get("usable_for_evaluation") is True
        and completeness.get("status") == "complete"
        and update.get("confirmed") is True
        and isinstance(records, list)
        and len(records) > 0
    )
    if not ready:
        return {
            "status": "benchmark_not_ready", "denominator": None,
            "matched": None, "missed": None, "ambiguous": None,
            "independent_coverage": None, "matches": [],
            "limitations": ["benchmark freshness, completeness, or update confirmation is insufficient"],
        }

    candidates: list[dict[str, Any]] = []
    for snapshot in self_snapshots:
        items = snapshot.get("candidates")
        if not isinstance(items, list):
            continue
        candidates.extend(c for c in items if isinstance(c, dict) and _self_eligible(c, cutoff_dt))

    matches, missed, ambiguous = [], [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("canonical_name") or record.get("keyword")
        if not isinstance(name, str) or not name.strip():
            missed.append({"benchmark_record": record, "reason": "missing_name"})
            continue
        resolution = resolve_exact(name, candidates)
        if resolution["status"] == "matched":
            matches.append({
                "benchmark_name": name,
                "candidate_id": resolution["candidate"].get("candidate_id"),
                "entity_id": resolution["candidate"].get("entity_id"),
                "method": resolution["method"],
            })
        elif resolution["status"] == "ambiguous":
            ambiguous.append({"benchmark_name": name, "reason": "multiple_exact_matches"})
        else:
            missed.append({"benchmark_name": name, "reason": "no_independent_match"})

    denominator = len(records)
    return {
        "status": "ready",
        "denominator": denominator,
        "matched": len(matches),
        "missed": len(missed),
        "ambiguous": len(ambiguous),
        "independent_coverage": len(matches) / denominator if denominator else None,
        "matches": matches,
        "missed_records": missed,
        "ambiguous_records": ambiguous,
        "cutoff": cutoff,
        "limitations": [
            "exact normalized names and explicit aliases only; fuzzy matches require review",
            "independence is relative to observed API exposure, not provider generation time when that time is unavailable",
        ],
    }
