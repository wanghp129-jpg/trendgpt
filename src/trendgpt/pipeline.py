"""Pure decision gates for the Lesson 14 validation order."""
from __future__ import annotations

from typing import Any


def gate_seen(seen_status: str) -> dict[str, Any]:
    if seen_status == "new":
        return {"status": "continue", "next": "site"}
    if seen_status == "resume_due":
        return {"status": "continue", "next": "resume_previous_stage"}
    if seen_status == "reuse":
        return {"status": "skip", "reason": "valid prior stage result can be reused"}
    if seen_status == "already_final":
        return {"status": "skip", "reason": "candidate already has a final decision for this fingerprint"}
    return {"status": "needs_review", "reason": "unknown seen state"}


def gate_site(site_status: str) -> dict[str, Any]:
    if site_status == "clear":
        return {"status": "continue", "next": "kd"}
    if site_status in {"already_built", "inflight"}:
        return {"status": "skip", "reason": site_status}
    return {"status": "needs_review", "reason": "site identity or in-flight state is ambiguous"}


def gate_kd(status: str, value: float | None) -> dict[str, Any]:
    if status != "success" or value is None:
        return {"status": "needs_review", "next": None, "reason": "KD unavailable; do not treat missing data as high KD"}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        return {"status": "needs_review", "next": None, "reason": "KD value is invalid"}
    if value >= 30:
        return {"status": "drop", "next": None, "reason": "KD must be strictly below 30"}
    return {"status": "continue", "next": "dataforseo_prefilter"}


def gate_prefilter(status: str) -> dict[str, Any]:
    if status == "blocked":
        return {"status": "drop", "next": None, "reason": "complete prefilter evidence explicitly rejected the candidate"}
    if status in {"passed", "bypass_missing"}:
        return {"status": "continue", "next": "google_trends"}
    return {"status": "needs_review", "next": None, "reason": "prefilter is pending, failed, or uncertain"}


def gate_google_trends(status: str) -> dict[str, Any]:
    if status == "passed":
        return {"status": "continue", "next": "domain"}
    if status == "rejected":
        return {"status": "drop", "next": None, "reason": "final browser trend review explicitly rejected the candidate"}
    return {"status": "needs_review", "next": None, "reason": "final browser trend evidence is not conclusive"}


def gate_domain(status: str) -> dict[str, Any]:
    if status == "available":
        return {"status": "build_ready", "next": "report_and_dispatch_authorization"}
    if status == "all_registered":
        return {"status": "needs_review", "next": None, "reason": "current domain patterns are unavailable; keyword itself is not rejected"}
    return {"status": "needs_review", "next": None, "reason": "domain status is unknown or query failed"}


def dispatch_allowed(
    *,
    decision: str,
    report_confirmed: bool,
    source_policy_approved: bool,
    global_dedupe_clear: bool,
    authorization_ref_present: bool,
) -> bool:
    """Validation and authorization are separate; default is deny."""
    return all((
        decision == "build",
        report_confirmed,
        source_policy_approved,
        global_dedupe_clear,
        authorization_ref_present,
    ))
