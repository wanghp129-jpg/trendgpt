"""Provider-injected Lesson 14 validation orchestrator.

This module implements decision order and fail-closed behavior only. It performs no
network requests itself; production provider adapters must be independently verified.
"""
from __future__ import annotations

from typing import Any, Callable


Provider = Callable[[dict[str, Any]], dict[str, Any]]


def _call(provider: Provider | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if provider is None:
        return {"status": "unavailable", "reason": "provider_not_configured"}
    try:
        result = provider(candidate)
    except Exception as exc:  # provider boundary: preserve a review state, not a false rejection
        return {"status": "error", "reason": f"provider_exception:{type(exc).__name__}"}
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        return {"status": "error", "reason": "invalid_provider_result"}
    return result


def validate_candidate(
    candidate: dict[str, Any],
    *,
    providers: dict[str, Provider],
    site_status: str | None = None,
) -> dict[str, Any]:
    """Run site → KD → optional prefilter → final browser → domain gates in order."""
    name = candidate.get("canonical_name")
    if not isinstance(name, str) or not name.strip():
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["missing_candidate_name"], "stages": {}}

    resolution = candidate.get("entity_resolution") or {}
    if resolution.get("status") == "ambiguous":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["ambiguous_game_identity"], "stages": {}}

    stages: dict[str, Any] = {}
    if site_status is None:
        site_result = _call(providers.get("site_lookup"), candidate)
        site_status = site_result.get("status", "unknown")
        stages["site"] = site_result
    else:
        stages["site"] = {"status": site_status}

    if site_status in {"already_built", "inflight"}:
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "drop",
                "reason_codes": [site_status], "stages": stages}
    if site_status != "clear":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["site_status_unknown"], "stages": stages}

    kd = _call(providers.get("kd"), candidate)
    stages["kd"] = kd
    if kd.get("status") != "success" or isinstance(kd.get("value"), bool) or not isinstance(kd.get("value"), (int, float)):
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["kd_unavailable_or_invalid"], "stages": stages}
    kd_value = kd["value"]
    if not 0 <= kd_value <= 100:
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["kd_out_of_range"], "stages": stages}
    if kd_value >= 30:
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "drop",
                "reason_codes": ["kd_gte_30"], "stages": stages}

    prefilter = _call(providers.get("prefilter"), candidate)
    if prefilter.get("status") in {"unavailable", "error", "failed", "missing", "pending"}:
        prefilter = {**prefilter, "status": "bypass_missing", "bypass_reason": prefilter.get("reason", "prefilter_unavailable")}
    stages["prefilter"] = prefilter
    if prefilter.get("status") == "blocked":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "drop",
                "reason_codes": ["dataforseo_explicit_reject"], "stages": stages}
    if prefilter.get("status") not in {"passed", "bypass_missing"}:
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["prefilter_uncertain"], "stages": stages}

    trends = _call(providers.get("google_trends"), candidate)
    stages["google_trends"] = trends
    if trends.get("status") == "rejected":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "drop",
                "reason_codes": ["google_trends_rejected"], "stages": stages}
    if trends.get("status") != "passed":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["google_trends_not_conclusive"], "stages": stages}

    domain = _call(providers.get("domain"), candidate)
    stages["domain"] = domain
    if domain.get("status") != "available":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["domain_not_confirmed_available"], "stages": stages}

    if resolution.get("status") != "resolved":
        return {"candidate_id": candidate.get("candidate_id"), "final_decision": "needs_review",
                "reason_codes": ["identity_requires_resolution_before_build"], "stages": stages}

    return {
        "candidate_id": candidate.get("candidate_id"),
        "entity_id": candidate.get("entity_id"),
        "canonical_name": name,
        "discovery_origin": candidate.get("discovery_origin"),
        "kd": kd_value,
        "google_trends_status": "passed",
        "domain_status": "available",
        "chosen_domain": domain.get("domain"),
        "final_decision": "build",
        "reason_codes": ["all_validation_gates_passed"],
        "dispatch_authorized": False,
        "stages": stages,
        "limitations": ["validation approval does not authorize dispatch; report, source policy, global dedupe and explicit authorization are separate gates"],
    }
