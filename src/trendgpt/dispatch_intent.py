"""Create an isolated dispatch intent only; never send a website_create request."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
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
    if verified_result.get("discovery_origin") != "self_discovered":
        raise DispatchIntentError("only independently collected self_discovered candidates may enter this intent path")
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

    policy_id = source_policy.get("policy_id")
    if source_policy.get("approved") is not True or not isinstance(policy_id, str) or not policy_id.strip():
        raise DispatchIntentError("self-source policy must be explicitly approved")
    if policy_id.casefold() == "trendoracle-ready":
        raise DispatchIntentError("the existing API-only trendoracle-ready policy must never be reused for self-discovered candidates")
    policy_ref = source_policy.get("evidence_ref")
    if not _valid_ref(policy_ref):
        raise DispatchIntentError("self-source policy approval evidence must exist and match its SHA-256 reference")

    _timestamp(global_dedupe.get("checked_at"), "global_dedupe.checked_at")
    if global_dedupe.get("status") != "clear":
        raise DispatchIntentError("global API/self/inflight duplicate check must be clear")
    dedupe_ref = global_dedupe.get("evidence_ref")
    if not _valid_ref(dedupe_ref):
        raise DispatchIntentError("global dedupe evidence must exist and match its SHA-256 reference")

    if authorization.get("approved") is not True or not isinstance(authorization.get("authorization_id"), str) or not authorization["authorization_id"].strip():
        raise DispatchIntentError("explicit dispatch authorization is required")
    authorization_ref = authorization.get("evidence_ref")
    if not _valid_ref(authorization_ref):
        raise DispatchIntentError("authorization evidence must exist and match its SHA-256 reference")

    fingerprint_data = "|".join((
        candidate_id, entity_id, domain, str(verified_result.get("code_version", "")),
        policy_id, report_ref["sha256"], policy_ref["sha256"], dedupe_ref["sha256"],
        authorization["authorization_id"], authorization_ref["sha256"],
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
        "source_policy": {"policy_id": policy_id, "approved": True, "evidence_ref": policy_ref},
        "global_dedupe": {"status": "clear", "checked_at": global_dedupe["checked_at"], "evidence_ref": dedupe_ref},
        "authorization": {"authorization_id": authorization["authorization_id"], "approved": True, "evidence_ref": authorization_ref},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendgpt-dispatch-intent")
    parser.add_argument("--verified-result", required=True)
    parser.add_argument("--report-receipt", required=True)
    parser.add_argument("--source-policy", required=True)
    parser.add_argument("--global-dedupe", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--output-root", required=True, help="must end in self-v1")
    parser.add_argument("--created-at", required=True, help="RFC3339 timestamp with timezone")
    args = parser.parse_args(argv)
    try:
        inputs = {
            "verified_result": load_json(args.verified_result),
            "report_receipt": load_json(args.report_receipt),
            "source_policy": load_json(args.source_policy),
            "global_dedupe": load_json(args.global_dedupe),
            "authorization": load_json(args.authorization),
        }
        for key, value in inputs.items():
            if not isinstance(value, dict):
                raise ContractError(f"{key} must be a JSON object")
        result = create_dispatch_intent(
            **inputs, output_root=args.output_root, created_at=args.created_at,
        )
        print(json.dumps({
            "status": "intent_only", "intent_id": result["intent_id"],
            "request_sent": False, "delivery_status": result["delivery_status"],
            "output_path": str(Path(args.output_root).absolute() / "dispatch-intents" / f"{result['intent_id']}.json"),
        }, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, DispatchIntentError, StorageError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
