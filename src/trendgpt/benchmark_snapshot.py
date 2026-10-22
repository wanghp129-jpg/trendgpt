"""Read an already archived TrendOracle raw snapshot without calling the API.

The current provider payload has no authoritative generated_at/updated_at marker and
does not prove complete-set semantics. This reader therefore emits a not-ready
benchmark unless a later, separately reviewed policy adds trustworthy confirmation.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
from .storage import atomic_write_json, evidence_ref


def read_archived_api_snapshot(
    raw_path: str | Path,
    *,
    acquired_at: str,
    output_root: str | Path,
) -> dict[str, Any]:
    raw_path = Path(raw_path).absolute()
    raw = load_json(raw_path)
    if not isinstance(raw, dict):
        raise ContractError("API raw snapshot must be an object")
    if not isinstance(raw.get("words"), list) or not isinstance(raw.get("bonus_words"), list):
        raise ContractError("API raw snapshot must contain words and bonus_words arrays")
    try:
        parsed_time = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContractError("acquired_at must be an RFC3339 timestamp") from exc
    if parsed_time.tzinfo is None:
        raise ContractError("acquired_at must include a timezone offset")

    normalized = []
    unparsed = 0
    for bucket in ("words", "bonus_words"):
        for position, item in enumerate(raw[bucket]):
            if isinstance(item, str) and item.strip():
                keyword, extra = item.strip(), {}
            elif isinstance(item, dict) and isinstance(item.get("keyword"), str) and item["keyword"].strip():
                keyword = item["keyword"].strip()
                extra = {key: item.get(key) for key in ("platform",) if isinstance(item.get(key), str)}
            else:
                unparsed += 1
                continue
            record = {"keyword": keyword, "source_bucket": bucket, "source_position": position}
            if "platform" in extra:
                record["platform"] = extra["platform"]
            normalized.append(record)

    # Never copy the raw identity field or the whole provider response to this artifact.
    raw_ref = evidence_ref(raw_path, root=raw_path.parent)
    snapshot = {
        "schema": "api-benchmark-snapshot-v1",
        "snapshot_id": raw_ref["sha256"][:24],
        "acquired_at": acquired_at,
        "source": "trendoracle",
        "provider_date": raw.get("date"),
        "provider_window": raw.get("window"),
        "provider_generated_at": None,
        "provider_updated_at": None,
        "provider_timezone": None,
        "raw_response_ref": raw_ref,
        "normalized_records": normalized,
        "completeness": {
            "status": "unknown",
            "unparsed_records": unparsed,
            "provider_full_set_assertion": None,
            "reason": "the archived payload does not prove that the provider returned a complete benchmark set",
        },
        "freshness": {
            "status": "unknown",
            "reason": "local acquisition time is not provider generation/update time",
        },
        "update_confirmation": {
            "confirmed": False,
            "method": "unknown",
            "evidence_refs": [],
            "reason": "provider generated_at/updated_at is absent; operator confirmation is required",
        },
        "evaluation_status": "benchmark_not_ready",
        "usable_for_evaluation": False,
        "exclusions": [],
        "limitations": [
            "this function reads a local archived raw file and performs no network request",
            "the raw response may contain private identity data and must remain access-controlled",
            "keyword records are a reference set only and must never be injected into self-discovery candidates",
        ],
    }
    output_path = Path(output_root).absolute() / "benchmarks" / snapshot["snapshot_id"] / "api_benchmark_snapshot.json"
    atomic_write_json(output_path, snapshot, root=output_root)
    snapshot["output_path"] = str(output_path)
    return snapshot
