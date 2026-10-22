"""Create an isolated dispatch intent only; never send a website_create request."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import StorageError, atomic_write_json, reject_symlink_components, sha256_file


class DispatchIntentError(ValueError):
    pass


def _valid_ref(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    path, digest = value.get("path"), value.get("sha256")
    if not isinstance(path, str) or not Path(path).is_absolute():
        return False
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        return False
    return sha256_file(target) == digest


def _timestamp(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise DispatchIntentError(f"{name} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DispatchIntentError(f"{name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise DispatchIntentError(f"{name} must include a timezone offset")


def create_dispatch_intent(
    verified_result: dict[str, Any],
    *,
    report_receipt: dict[str, Any],
    source_policy: dict[str, Any],
    global_dedupe: dict[str, Any],
    authorization: dict[str, Any],
    output_root: str | Path,
    created_at: str,
) -> dict[str, Any]:
    """Write a deny-by-default intent artifact after all explicit gates are satisfied."""
    root = Path(output_root).absolute()
    if root.name != "self-v1":
        raise StorageError("dispatch intent root must end in self-v1")
    _timestamp(created_at, "created_at")
    if verified_result.get("final_decision") != "build":
        raise DispatchIntentError("candidate must have a final build decision")
    candidate_id = verified_result.get("candidate_id")
    entity_id = verified_result.get("entity_id")
    domain = verified_result.get("chosen_domain")
    if not all(isinstance(v, str) and v.strip() for v in (candidate_id, entity_id, domain)):
        raise DispatchIntentError("candidate_id, entity_id and chosen_domain are required")
    if verified_result.get("domain_status") != "available":
        raise DispatchIntentError("domain availability must be confirmed")
    if verified_result.get("google_trends_status") != "passed":
        raise DispatchIntentError("final Google Trends decision must be passed")
    kd = verified_result.get("kd")
    if isinstance(kd, bool) or not isinstance(kd, (int, float)) or not 0 <= kd < 30:
        raise DispatchIntentError("a real KD value strictly below 30 is required")

    if report_receipt.get("status") != "confirmed" or report_receipt.get("readback_verified") is not True:
        raise DispatchIntentError("valid report write and readback must be confirmed")
    report_ref = report_receipt.get("evidence_ref")
    if not _valid_ref(report_ref):
        raise DispatchIntentError("report evidence must exist and match its SHA-256 reference")

    if source_policy.get("approved") is not True or not isinstance(source_policy.get("policy_id"), str) or not source_policy["policy_id"].strip():
        raise DispatchIntentError("self-source policy must be explicitly approved")
    _timestamp(global_dedupe.get("checked_at"), "global_dedupe.checked_at")
    if global_dedupe.get("status") != "clear":
        raise DispatchIntentError("global API/self/inflight duplicate check must be clear")
    if authorization.get("approved") is not True or not isinstance(authorization.get("authorization_id"), str) or not authorization["authorization_id"].strip():
        raise DispatchIntentError("explicit dispatch authorization is required")

    fingerprint_data = "|".join((
        candidate_id, entity_id, domain, str(verified_result.get("code_version", "")),
        source_policy["policy_id"], report_ref["sha256"],
    ))
    intent_id = hashlib.sha256(fingerprint_data.encode("utf-8")).hexdigest()[:32]
    intent = {
        "schema": "self-dispatch-intent-v1",
        "intent_id": intent_id,
        "created_at": created_at,
        "candidate_id": candidate_id,
        "entity_id": entity_id,
        "canonical_name": verified_result.get("canonical_name"),
        "chosen_domain": domain,
        "source": "self_discovered",
        "validation": {
            "final_decision": "build", "kd": kd,
            "google_trends_status": "passed", "domain_status": "available",
        },
        "report_receipt": report_receipt,
        "source_policy": {"policy_id": source_policy["policy_id"], "approved": True},
        "global_dedupe": {"status": "clear", "checked_at": global_dedupe["checked_at"]},
        "authorization": {"authorization_id": authorization["authorization_id"], "approved": True},
        "dispatch_status": "intent_only",
        "request_sent": False,
        "website_task_id": None,
        "delivery_status": "not_started",
        "limitations": [
            "this artifact does not call website_create",
            "a future adapter must enforce idempotency and reconcile the original task ID",
        ],
    }
    target = root / "dispatch-intents" / f"{intent_id}.json"
    reject_symlink_components(target)
    atomic_write_json(target, intent, root=root)
    return intent
