"""Strict, dependency-free JSON contract checks for the self-v1 namespace."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

ORIGINS = {"self_discovered", "api_benchmark", "manual", "external_supplement"}
RUN_STATUSES = {"running", "completed", "partial", "failed", "needs_review"}
DECISIONS = {"build", "drop", "needs_review"}
BENCHMARK_STATUSES = {"ready", "benchmark_not_ready", "disabled"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Input data violates a published contract."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-standard numeric constant is forbidden: {value}")


def load_json(path: str | Path) -> Any:
    """Read strict JSON; reject duplicate keys and NaN/Infinity."""
    source = Path(path)
    if source.is_symlink():
        raise ContractError("input path must not be a symlink")
    try:
        with source.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read strict JSON: {exc}") from exc


def _obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def _str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _arr(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{name} must be an array")
    return value


def _timestamp(value: Any, name: str) -> None:
    text = _str(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{name} must include a timezone offset")


def _date(value: Any, name: str) -> None:
    text = _str(value, name)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{name} must be YYYY-MM-DD") from exc
    if len(text) != 10:
        raise ContractError(f"{name} must be YYYY-MM-DD")


def _evidence(value: Any, name: str) -> None:
    if value is None:
        return
    ref = _obj(value, name)
    path = _str(ref.get("path"), f"{name}.path")
    digest = _str(ref.get("sha256"), f"{name}.sha256")
    if not Path(path).is_absolute():
        raise ContractError(f"{name}.path must be absolute")
    if not SHA256_RE.fullmatch(digest):
        raise ContractError(f"{name}.sha256 must be a lowercase SHA-256 digest")


def validate_candidate_snapshot(value: Any) -> dict[str, Any]:
    obj = _obj(value, "candidate snapshot")
    if obj.get("schema") != "self-candidate-keywords-v1":
        raise ContractError("unsupported candidate schema")
    for key in ("run_id", "slot", "timezone", "code_version", "normalization_version", "source_policy_version"):
        _str(obj.get(key), key)
    _date(obj.get("date"), "date")
    for key in ("started_at", "collected_at", "cutoff_at"):
        _timestamp(obj.get(key), key)
    if obj.get("collection_status") not in {"complete", "partial", "failed"}:
        raise ContractError("collection_status must be complete, partial, or failed")
    if obj.get("completeness") not in {"complete", "partial", "unknown"}:
        raise ContractError("completeness must be complete, partial, or unknown")
    for i, source in enumerate(_arr(obj.get("source_runs"), "source_runs")):
        src = _obj(source, f"source_runs[{i}]")
        _str(src.get("source_id"), f"source_runs[{i}].source_id")
        if src.get("status") not in {"complete", "partial", "failed", "blocked"}:
            raise ContractError(f"source_runs[{i}].status is invalid")
    for i, candidate in enumerate(_arr(obj.get("candidates"), "candidates")):
        c = _obj(candidate, f"candidates[{i}]")
        for key in ("candidate_id", "entity_id", "canonical_name"):
            _str(c.get(key), f"candidates[{i}].{key}")
        if c.get("discovery_origin") not in ORIGINS:
            raise ContractError(f"candidates[{i}].discovery_origin is invalid")
        for key in ("aliases", "raw_titles", "platforms", "sources", "origin_events", "raw_evidence_refs", "missing_fields"):
            if key in c and not isinstance(c[key], list):
                raise ContractError(f"candidates[{i}].{key} must be an array")
        for j, ref in enumerate(c.get("raw_evidence_refs", [])):
            _evidence(ref, f"candidates[{i}].raw_evidence_refs[{j}]")
    return obj


def validate_verified_snapshot(value: Any) -> dict[str, Any]:
    obj = _obj(value, "verified snapshot")
    if obj.get("schema") != "self-verified-keywords-v1":
        raise ContractError("unsupported verified schema")
    for key in ("run_id", "slot", "timezone", "code_version"):
        _str(obj.get(key), key)
    _date(obj.get("date"), "date")
    _timestamp(obj.get("started_at"), "started_at")
    for i, result in enumerate(_arr(obj.get("results"), "results")):
        item = _obj(result, f"results[{i}]")
        if item.get("final_decision") not in DECISIONS:
            raise ContractError(f"results[{i}].final_decision is invalid")
        if item.get("discovery_origin") not in ORIGINS:
            raise ContractError(f"results[{i}].discovery_origin is invalid")
        kd = item.get("kd")
        if kd is not None and (isinstance(kd, bool) or not isinstance(kd, (int, float)) or not math.isfinite(kd) or not 0 <= kd <= 100):
            raise ContractError(f"results[{i}].kd must be null or a finite number from 0 to 100")
        if item.get("final_decision") == "build":
            if kd is None or kd >= 30:
                raise ContractError(f"results[{i}] cannot build without a valid KD below 30")
            if item.get("google_trends_status") != "passed":
                raise ContractError(f"results[{i}] cannot build without final Google Trends approval")
            if item.get("domain_status") != "available":
                raise ContractError(f"results[{i}] cannot build without an available domain")
    return obj


def validate_benchmark_snapshot(value: Any) -> dict[str, Any]:
    obj = _obj(value, "benchmark snapshot")
    if obj.get("schema") != "api-benchmark-snapshot-v1":
        raise ContractError("unsupported benchmark schema")
    _str(obj.get("snapshot_id"), "snapshot_id")
    _timestamp(obj.get("acquired_at"), "acquired_at")
    if obj.get("evaluation_status") not in BENCHMARK_STATUSES:
        raise ContractError("evaluation_status is invalid")
    completeness = _obj(obj.get("completeness"), "completeness")
    update = _obj(obj.get("update_confirmation"), "update_confirmation")
    records = _arr(obj.get("normalized_records"), "normalized_records")
    if obj.get("evaluation_status") == "ready":
        if completeness.get("status") != "complete" or update.get("confirmed") is not True or not records:
            raise ContractError("ready benchmark requires complete data, confirmed update, and non-empty records")
        if obj.get("usable_for_evaluation") is not True:
            raise ContractError("ready benchmark must be marked usable_for_evaluation")
    if obj.get("usable_for_evaluation") is True and obj.get("evaluation_status") != "ready":
        raise ContractError("only a ready benchmark can be usable_for_evaluation")
    return obj


def validate_run_result(value: Any) -> dict[str, Any]:
    obj = _obj(value, "run result")
    if obj.get("schema") != "self-keyword-run-result-v1":
        raise ContractError("unsupported run-result schema")
    _str(obj.get("run_id"), "run_id")
    _date(obj.get("date"), "date")
    if obj.get("status") not in RUN_STATUSES:
        raise ContractError("run status is invalid")
    _timestamp(obj.get("started_at"), "started_at")
    counts = _obj(obj.get("counts"), "counts")
    for key, number in counts.items():
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ContractError(f"counts.{key} must be a non-negative integer")
    return obj


def validate_state(value: Any) -> dict[str, Any]:
    obj = _obj(value, "state")
    _date(obj.get("date"), "date")
    _str(obj.get("timezone"), "timezone")
    revision = obj.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ContractError("revision must be a non-negative integer")
    if not isinstance(obj.get("seen_keywords"), list) or not all(isinstance(x, str) for x in obj["seen_keywords"]):
        raise ContractError("seen_keywords must be an array of strings")
    _obj(obj.get("runs"), "runs")
    return obj


VALIDATORS = {
    "candidate": validate_candidate_snapshot,
    "verified": validate_verified_snapshot,
    "benchmark": validate_benchmark_snapshot,
    "run-result": validate_run_result,
    "state": validate_state,
}


def validate_file(kind: str, path: str | Path) -> dict[str, Any]:
    try:
        validator = VALIDATORS[kind]
    except KeyError as exc:
        raise ContractError(f"unknown contract kind: {kind}") from exc
    return validator(load_json(path))
