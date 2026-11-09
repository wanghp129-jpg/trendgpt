"""Read an already archived TrendOracle raw snapshot without calling the API.

Provider timing and complete-set semantics are not inferred from local fetch time.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
from .storage import StorageError, atomic_write_json, evidence_ref


def read_archived_api_snapshot(
    raw_path: str | Path,
    *,
    acquired_at: str,
    output_root: str | Path,
    snapshot_metadata: dict[str, Any] | None = None,
    relative_output_dir: str | Path | None = None,
    immutable: bool = False,
) -> dict[str, Any]:
    root = Path(output_root).absolute()
    if root.name != "self-v1":
        raise ContractError("output_root must end in self-v1; refusing production namespace")
    raw_path = Path(raw_path).absolute()
    raw = load_json(raw_path)
    if not isinstance(raw, dict):
        raise ContractError("API raw snapshot must be an object")
    try:
        parsed_time = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContractError("acquired_at must be an RFC3339 timestamp") from exc
    if parsed_time.tzinfo is None:
        raise ContractError("acquired_at must include a timezone offset")

    normalized = []
    unparsed = 0
    bucket_issues: list[str] = []
    for bucket in ("words", "bonus_words"):
        items = raw.get(bucket)
        if not isinstance(items, list):
            bucket_issues.append(bucket)
            continue
        for position, item in enumerate(items):
            if isinstance(item, str) and item.strip():
                keyword, extra = item.strip(), {}
            elif isinstance(item, dict) and isinstance(item.get("keyword"), str) and item["keyword"].strip():
                keyword = item["keyword"].strip()
                extra = {key: item.get(key) for key in ("platform",) if isinstance(item.get(key), str)}
            else:
                unparsed += 1
                continue
            record = {"keyword": keyword, "source_bucket": bucket, "source_position": position}
            if "platform" in extra and extra["platform"].strip():
                record["platform"] = extra["platform"].strip()
            normalized.append(record)

    raw_ref = evidence_ref(raw_path, root=raw_path.parent)
    snapshot = {
        "schema": "api-benchmark-snapshot-v1",
        "snapshot_id": raw_ref["sha256"][:24],
        "acquired_at": acquired_at,
        "acquired_at_semantics": "local fetch-run start; not provider mining or publication time",
        "source": "trendoracle",
        "provider_date": raw.get("date"),
        "provider_window": raw.get("window"),
        "provider_generated_at": None,
        "provider_updated_at": None,
        "provider_timezone": None,
        "raw_response_ref": raw_ref,
        "normalized_records": normalized,
        "completeness": {
            "status": "partial" if bucket_issues or unparsed else "unknown",
            "unparsed_records": unparsed,
            "invalid_or_missing_buckets": bucket_issues,
            "provider_full_set_assertion": None,
            "reason": (
                "one or more word buckets are missing/invalid or contain unparseable records"
                if bucket_issues or unparsed
                else "the archived payload does not prove that the provider returned a complete benchmark set"
            ),
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

    if snapshot_metadata is not None:
        if not isinstance(snapshot_metadata, dict):
            raise ContractError("snapshot_metadata must be an object")
        reserved = {
            "schema", "snapshot_id", "acquired_at", "source", "provider_date",
            "provider_window", "provider_generated_at", "provider_updated_at",
            "provider_timezone", "raw_response_ref", "normalized_records",
            "freshness", "evaluation_status", "usable_for_evaluation", "output_path",
        }
        conflicts = reserved.intersection(snapshot_metadata)
        if conflicts:
            raise ContractError(f"snapshot_metadata cannot override reserved fields: {', '.join(sorted(conflicts))}")
        snapshot.update(snapshot_metadata)

    if relative_output_dir is None:
        output_dir = root / "benchmarks" / snapshot["snapshot_id"]
    else:
        relative = Path(relative_output_dir)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ContractError("relative_output_dir must be a safe path below self-v1")
        output_dir = root / relative
    output_path = output_dir / "api_benchmark_snapshot.json"

    if immutable and (output_path.exists() or output_path.is_symlink()):
        existing = load_json(output_path)
        if existing != snapshot:
            raise StorageError(f"immutable API benchmark snapshot conflicts with existing content: {output_path}")
    else:
        atomic_write_json(output_path, snapshot, root=root)
    snapshot["output_path"] = str(output_path)
    return snapshot
