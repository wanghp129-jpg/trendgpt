"""Read the existing TrendOracle ingest archive without making network requests.

The provider's 00:00 mining batch is published around 08:00 Asia/Shanghai.
The current response does not expose a batch ID, generated_at timestamp, or a
complete-set assertion, so local morning evidence is aligned by operator-declared
schedule only and must remain benchmark_not_ready.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .benchmark_snapshot import read_archived_api_snapshot
from .contracts import ContractError, load_json
from .storage import StorageError, atomic_write_json, evidence_ref, reject_symlink_components

BUSINESS_TIMEZONE = "Asia/Shanghai"
MINING_TIME = "00:00:00"
PUBLICATION_TIME = "08:00:00"
RUN_ID_RE = re.compile(r"^fetch-(\d{8}T\d{6}Z)-(\d+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_batch_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ContractError("date must be YYYY-MM-DD")
    return parsed


def _run_started_at(run_id: str) -> str:
    match = RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise ContractError("fetch run ID does not contain a supported UTC start time")
    parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _existing_path_under(value: Any, *, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} path is missing")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ContractError(f"{label} path must be absolute")
    reject_symlink_components(candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ContractError(f"{label} path is missing or outside the approved root") from exc
    if not resolved.is_file():
        raise ContractError(f"{label} must be a regular file")
    return resolved


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _attempt(run_id: str, started_at: str | None, status: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"run_id": run_id, "run_started_at": started_at, "status": status}
    result.update(extra)
    return result


def _inspect_run(summary_path: Path, *, ingest_root: Path, batch_date: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    run_dir = summary_path.parent
    run_id = run_dir.name
    try:
        started_at = _run_started_at(run_id)
    except (ContractError, ValueError):
        return None, _attempt(run_id, None, "invalid_run_id")

    try:
        reject_symlink_components(summary_path)
        summary = load_json(summary_path)
    except (ContractError, OSError, StorageError):
        return None, _attempt(run_id, started_at, "invalid_summary")

    if not isinstance(summary, dict) or summary.get("run_id") != run_id:
        return None, _attempt(run_id, started_at, "run_id_mismatch")
    if summary.get("date") != batch_date:
        return None, None

    status = summary.get("status")
    if status == "unavailable" and summary.get("reason") == "not_open_yet":
        return None, _attempt(
            run_id, started_at, "not_open_yet",
            open_at=summary.get("open_at"),
        )

    if status not in {"success", "duplicate"}:
        return None, _attempt(
            run_id, started_at, "not_usable",
            ingest_status=status,
            failed_step=summary.get("failed_step"),
        )
    if summary.get("exit_code") != 0 or summary.get("window") != "morning":
        return None, _attempt(
            run_id, started_at, "not_usable",
            ingest_status=status,
            window=summary.get("window"),
            exit_code=summary.get("exit_code"),
        )

    try:
        response_path = _existing_path_under(
            summary.get("raw_response"), root=ingest_root / "tmp", label="raw_response"
        )
        expected_response = (run_dir / "response.json").resolve(strict=True)
        if response_path != expected_response:
            raise ContractError("raw_response does not point to this run's response.json")

        raw_root = ingest_root / "data" / "raw"
        raw_path = _existing_path_under(
            summary.get("raw_snapshot"), root=raw_root, label="raw_snapshot"
        )
        relative_raw = raw_path.relative_to(raw_root.resolve(strict=True))
        if relative_raw.parts != (batch_date, "morning", raw_path.name):
            raise ContractError("raw_snapshot path does not match the requested date and morning window")
        digest = raw_path.stem
        if not SHA256_RE.fullmatch(digest):
            raise ContractError("raw_snapshot filename is not a SHA-256 digest")

        raw_bytes = raw_path.read_bytes()
        response_bytes = response_path.read_bytes()
        actual_digest = hashlib.sha256(raw_bytes).hexdigest()
        if actual_digest != digest:
            raise ContractError("raw_snapshot SHA-256 does not match its filename")
        if hashlib.sha256(response_bytes).hexdigest() != actual_digest or response_bytes != raw_bytes:
            raise ContractError("response.json and immutable raw snapshot do not match")

        raw = load_json(raw_path)
        if not isinstance(raw, dict):
            raise ContractError("raw snapshot must be a JSON object")
        if raw.get("ok") is not True or raw.get("available") is not True:
            raise ContractError("raw snapshot is not an available successful API response")
        if raw.get("date") != batch_date or raw.get("window") != "morning":
            raise ContractError("raw snapshot date/window does not match the requested morning batch")
        if summary.get("date") != raw.get("date") or summary.get("window") != raw.get("window"):
            raise ContractError("summary and raw snapshot date/window disagree")

        normalized: list[dict[str, Any]] = []
        bucket_issues: list[str] = []
        unparsed_records = 0
        count_mismatches: list[str] = []
        for bucket in ("words", "bonus_words"):
            items = raw.get(bucket)
            if not isinstance(items, list):
                bucket_issues.append(bucket)
                continue
            reported_count = summary.get(f"{bucket}_count")
            if isinstance(reported_count, int) and not isinstance(reported_count, bool) and reported_count != len(items):
                count_mismatches.append(bucket)
            for position, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("keyword"), str) or not item["keyword"].strip():
                    unparsed_records += 1
                    continue
                record: dict[str, Any] = {
                    "keyword": item["keyword"].strip(),
                    "source_bucket": bucket,
                    "source_position": position,
                }
                platform = item.get("platform")
                if isinstance(platform, str) and platform.strip():
                    record["platform"] = platform.strip()
                normalized.append(record)

        summary_unparsed = _nonnegative_int(summary.get("unparsed_items"))
        summary_bad_buckets = _nonnegative_int(summary.get("unparsed_buckets"))
        unparsed_records = max(unparsed_records, summary_unparsed)
        if summary_bad_buckets:
            bucket_issues.append("summary_reported_invalid_bucket")
        completeness_status = (
            "partial"
            if bucket_issues or count_mismatches or unparsed_records
            else "unknown"
        )
        summary_ref = evidence_ref(summary_path, root=ingest_root)
        response_ref = evidence_ref(response_path, root=ingest_root)
        raw_ref = evidence_ref(raw_path, root=ingest_root)
        return {
            "run_id": run_id,
            "run_started_at": started_at,
            "summary": summary,
            "summary_path": summary_path,
            "summary_ref": summary_ref,
            "response_path": response_path,
            "response_ref": response_ref,
            "raw_path": raw_path,
            "raw_ref": raw_ref,
            "raw_sha256": actual_digest,
            "raw": raw,
            "normalized_records": normalized,
            "unparsed_records": unparsed_records,
            "bucket_issues": sorted(set(bucket_issues)),
            "count_mismatches": count_mismatches,
            "completeness_status": completeness_status,
        }, None
    except (ContractError, OSError, StorageError, ValueError) as exc:
        return None, _attempt(
            run_id, started_at, "invalid_evidence",
            reason=str(exc),
        )


def _write_once(path: Path, value: dict[str, Any], *, root: Path) -> None:
    if path.exists() or path.is_symlink():
        existing = load_json(path)
        if existing != value:
            raise StorageError(f"immutable artifact already exists with different content: {path}")
        return
    atomic_write_json(path, value, root=root)


def read_api_ingest_morning_batch(
    ingest_root: str | Path,
    *,
    batch_date: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """Select the earliest successful local morning ingest for a Shanghai business date.

    This function only reads local files. It never invokes fetch-daily.py, the API,
    systemd, or any production dispatch entry point.
    """
    parsed_date = _parse_batch_date(batch_date)
    source_root = Path(ingest_root).absolute()
    output = Path(output_root).absolute()
    if output.name != "self-v1":
        raise ContractError("output_root must end in self-v1")
    reject_symlink_components(source_root)
    if not source_root.is_dir():
        raise ContractError("ingest_root must be an existing directory")
    source_resolved = source_root.resolve(strict=True)
    output_resolved = output.resolve(strict=False)
    if output_resolved == source_resolved or output_resolved.is_relative_to(source_resolved) or source_resolved.is_relative_to(output_resolved):
        raise ContractError("API ingest root and self-v1 output root must be separate")

    tmp_root = source_resolved / "tmp"
    if not tmp_root.is_dir():
        return {
            "status": "benchmark_not_ready",
            "batch_date": batch_date,
            "timezone": BUSINESS_TIMEZONE,
            "reason": "ingest_tmp_directory_missing",
            "attempts": [],
            "network_requests": 0,
        }

    selected_runs: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for summary_path in sorted(tmp_root.glob("fetch-*/summary.json")):
        run, attempt = _inspect_run(
            summary_path, ingest_root=source_resolved, batch_date=batch_date
        )
        if run is not None:
            selected_runs.append(run)
        if attempt is not None:
            attempts.append(attempt)

    selected_runs.sort(key=lambda item: item["run_started_at"])
    attempts.sort(key=lambda item: (item.get("run_started_at") or "", item["run_id"]))
    if not selected_runs:
        return {
            "status": "benchmark_not_ready",
            "batch_date": batch_date,
            "timezone": BUSINESS_TIMEZONE,
            "scheduled_mining_time": MINING_TIME,
            "expected_publication_time": f"{batch_date}T{PUBLICATION_TIME}+08:00",
            "reason": "no_valid_successful_morning_snapshot",
            "attempts": attempts,
            "network_requests": 0,
        }

    selected = selected_runs[0]
    selected_started = selected["run_started_at"]
    prior_attempts = [
        item for item in attempts
        if item.get("run_started_at") is not None
        and item["run_started_at"] <= selected_started
    ]
    summary = selected["summary"]
    snapshot_metadata = {
        "batch_date": batch_date,
        "timezone": BUSINESS_TIMEZONE,
        "scheduled_mining_time": MINING_TIME,
        "expected_publication_time": f"{batch_date}T{PUBLICATION_TIME}+08:00",
        "published_at": None,
        "source_batch_id": None,
        "source_updated_at": None,
        "collected_at": None,
        "ingested_at": None,
        "local_fetch_run_id": selected["run_id"],
        "local_fetch_run_started_at": selected_started,
        "local_ingest_status": summary.get("status"),
        "local_ingest_exit_code": summary.get("exit_code"),
        "batch_alignment_status": "operator_declared_unverified",
        "batch_alignment": {
            "declared_mining_time": MINING_TIME,
            "declared_publication_time": PUBLICATION_TIME,
            "provider_batch_id": None,
            "provider_generated_at": None,
            "provider_updated_at": None,
            "reason": "the archived provider payload exposes date/window but no batch ID or server generation/update timestamp",
        },
        "ingest_evidence": {
            "summary_ref": selected["summary_ref"],
            "response_ref": selected["response_ref"],
            "raw_snapshot_ref": selected["raw_ref"],
        },
        "completeness": {
            "status": selected["completeness_status"],
            "unparsed_records": selected["unparsed_records"],
            "invalid_buckets": selected["bucket_issues"],
            "summary_count_mismatches": selected["count_mismatches"],
            "provider_full_set_assertion": None,
            "reason": (
                "the provider does not assert that this response is the complete 00:00 batch"
                if selected["completeness_status"] == "unknown"
                else "one or more source buckets or records were incomplete or inconsistent"
            ),
        },
        "update_confirmation": {
            "confirmed": False,
            "method": "operator_declared_schedule_only",
            "evidence_refs": [selected["summary_ref"], selected["response_ref"]],
            "reason": "08:00 publication timing is operator-declared; the response has no server-side publication timestamp or batch ID",
        },
    }

    relative_dir = Path("benchmarks") / batch_date / selected["raw_sha256"][:24]
    snapshot = read_archived_api_snapshot(
        selected["raw_path"],
        acquired_at=selected_started,
        output_root=output,
        snapshot_metadata=snapshot_metadata,
        relative_output_dir=relative_dir,
        immutable=True,
    )
    snapshot_path = Path(snapshot["output_path"])
    manifest_path = snapshot_path.parent / "snapshot-manifest.json"
    report_path = snapshot_path.parent / "read-report.json"
    manifest = {
        "schema": "api-benchmark-manifest-v1",
        "batch_date": batch_date,
        "timezone": BUSINESS_TIMEZONE,
        "scheduled_mining_time": MINING_TIME,
        "expected_publication_time": f"{batch_date}T{PUBLICATION_TIME}+08:00",
        "selected_run_id": selected["run_id"],
        "selected_run_status": summary.get("status"),
        "local_fetch_run_started_at": selected_started,
        "prepublication_attempts": prior_attempts,
        "source_summary_ref": selected["summary_ref"],
        "source_response_ref": selected["response_ref"],
        "source_raw_ref": selected["raw_ref"],
        "raw_sha256": selected["raw_sha256"],
        "batch_alignment_status": "operator_declared_unverified",
        "completeness_status": selected["completeness_status"],
        "evaluation_status": "benchmark_not_ready",
        "network_requests": 0,
    }
    report = {
        "status": "benchmark_not_ready",
        "batch_date": batch_date,
        "selected_run_id": selected["run_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "record_count": len(snapshot["normalized_records"]),
        "completeness": snapshot["completeness"],
        "batch_alignment_status": snapshot["batch_alignment_status"],
        "reason": "provider batch identity and complete-set semantics are not proven",
        "snapshot_path": str(snapshot_path),
        "manifest_path": str(manifest_path),
        "network_requests": 0,
    }
    _write_once(manifest_path, manifest, root=output)
    _write_once(report_path, report, root=output)
    snapshot["manifest_path"] = str(manifest_path)
    snapshot["read_report_path"] = str(report_path)
    snapshot["other_successful_morning_runs"] = [
        {
            "run_id": item["run_id"],
            "run_started_at": item["run_started_at"],
            "raw_sha256": item["raw_sha256"],
            "status": item["summary"].get("status"),
        }
        for item in selected_runs[1:]
    ]
    return snapshot
