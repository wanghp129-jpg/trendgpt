"""Persistent first-seen ledger for stable self-discovered platform entities.

The ledger intentionally refuses fuzzy/name-only identity merges. A platform ID is
required to carry first-seen timestamps across runs; unresolved records are retained
in a review queue instead of being merged on a title guess.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json, validate_candidate_snapshot
from .storage import StorageError, atomic_write_json, reject_symlink_components

RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class EntityLedgerConflict(StorageError):
    pass


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("candidate first-seen timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("candidate first-seen timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ContractError("candidate first-seen timestamp must include a timezone")
    return parsed


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema": "self-entity-first-seen-ledger-v1",
        "revision": 0,
        "entities": {},
        "runs": {},
        "review_queue": [],
    }


def _validate_ledger(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "self-entity-first-seen-ledger-v1":
        raise ContractError("unsupported entity first-seen ledger schema")
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ContractError("entity ledger revision must be a non-negative integer")
    for key in ("entities", "runs"):
        if not isinstance(value.get(key), dict):
            raise ContractError(f"entity ledger {key} must be an object")
    if not isinstance(value.get("review_queue"), list):
        raise ContractError("entity ledger review_queue must be an array")
    return value


def _stable_platform_keys(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    platform_ids = candidate.get("platform_ids")
    pairs: set[tuple[str, str]] = set()
    if isinstance(platform_ids, dict):
        for platform, platform_id in platform_ids.items():
            if isinstance(platform, str) and platform.strip() and isinstance(platform_id, (str, int)):
                value = str(platform_id).strip()
                if value:
                    pairs.add((platform.strip().casefold(), value))
    if pairs:
        return sorted(pairs)

    # Conservative fallback for imported candidate snapshots that predate platform_ids.
    sources = candidate.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("source_id")
            source_record_id = source.get("source_record_id")
            if source_id in {"steam", "roblox"} and isinstance(source_record_id, (str, int)):
                value = str(source_record_id).strip()
                if value:
                    pairs.add((str(source_id), value))
    return sorted(pairs)


def _candidate_observed_at(candidate: dict[str, Any]) -> datetime:
    value = candidate.get("first_self_discovered_at")
    if value is None:
        events = candidate.get("origin_events")
        if isinstance(events, list):
            self_events = [
                item.get("observed_at") for item in events
                if isinstance(item, dict) and item.get("origin") == "self_discovered"
            ]
            value = next((item for item in self_events if isinstance(item, str)), None)
    return _parse_timestamp(value)


def _source_ids(candidate: dict[str, Any]) -> list[str]:
    sources = candidate.get("sources")
    if not isinstance(sources, list):
        return []
    return sorted({
        item["source_id"] for item in sources
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    })


def _evidence_refs(candidate: dict[str, Any]) -> list[dict[str, str]]:
    refs = candidate.get("raw_evidence_refs")
    if not isinstance(refs, list):
        return []
    result = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        path, digest = item.get("path"), item.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            result.append({"path": path, "sha256": digest})
    return result


class EntityFirstSeenLedger:
    """Lock-protected cross-day first-seen memory inside one explicit self-v1 root."""

    def __init__(self, output_root: str | Path):
        root = Path(output_root).absolute()
        if root.name != "self-v1":
            raise StorageError("entity ledger root must end in self-v1; refusing shared production state")
        reject_symlink_components(root)
        self.root = root
        self.ledger_path = root / "entity-ledger.json"
        self.lock_path = root / "entity-ledger.lock"

    def read(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return _empty_ledger()
        return _validate_ledger(load_json(self.ledger_path))

    def record_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        validate_candidate_snapshot(snapshot)
        if any(candidate.get("discovery_origin") != "self_discovered" for candidate in snapshot["candidates"]):
            raise ContractError("first-seen ledger accepts self_discovered candidates only")
        run_id = snapshot["run_id"]
        run_date = snapshot["date"]
        if not RUN_ID_RE.fullmatch(run_id):
            raise ContractError("run_id contains unsupported path characters")
        input_sha256 = _snapshot_digest(snapshot)
        output_path = self.root / "first-seen" / run_date / run_id / "candidate_keywords.json"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        reject_symlink_components(self.root)

        reject_symlink_components(self.lock_path)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            ledger = self.read()
            previous_run = ledger["runs"].get(run_id)
            if previous_run and previous_run.get("input_sha256") != input_sha256:
                raise EntityLedgerConflict(f"run_id {run_id!r} was already recorded with different input")
            reject_symlink_components(output_path)
            if previous_run and (output_path.exists() or output_path.is_symlink()):
                existing = load_json(output_path)
                marker = existing.get("first_seen_ledger") if isinstance(existing, dict) else None
                if not isinstance(marker, dict) or marker.get("input_sha256") != input_sha256:
                    raise EntityLedgerConflict(f"first-seen output does not match recorded run: {output_path}")
                content_copy = copy.deepcopy(existing)
                content_copy.pop("first_seen_ledger", None)
                if marker.get("content_sha256") != _snapshot_digest(content_copy):
                    raise EntityLedgerConflict(f"first-seen output content hash is invalid: {output_path}")
                return {
                    "status": "reused",
                    "run_id": run_id,
                    "entities_confirmed": previous_run.get("entities_confirmed", 0),
                    "needs_review": previous_run.get("needs_review", 0),
                    "ledger_revision": ledger["revision"],
                    "ledger_path": str(self.ledger_path),
                    "output_path": str(output_path),
                    "input_sha256": input_sha256,
                }
            if previous_run:
                missing_entities = [key for key in previous_run.get("entity_keys", []) if key not in ledger["entities"]]
                recorded_reviews = {
                    item.get("review_id") for item in ledger["review_queue"] if isinstance(item, dict)
                }
                missing_reviews = [key for key in previous_run.get("review_ids", []) if key not in recorded_reviews]
                if missing_entities or missing_reviews:
                    raise EntityLedgerConflict("entity ledger is missing records referenced by an earlier run")

            enriched = copy.deepcopy(snapshot)
            confirmed_count = 0
            review_count = 0
            run_entity_keys: list[str] = []
            run_review_ids: list[str] = []

            for candidate in enriched["candidates"]:
                pairs = _stable_platform_keys(candidate)
                try:
                    observed = _candidate_observed_at(candidate)
                except ContractError:
                    observed = None

                if len(pairs) != 1 or observed is None:
                    reason = (
                        "multiple_platform_ids_require_explicit_cross_platform_mapping"
                        if len(pairs) > 1 else
                        "missing_stable_platform_id" if not pairs else
                        "missing_or_invalid_first_discovery_timestamp"
                    )
                    candidate["first_seen_status"] = "needs_review"
                    candidate["first_seen_reason"] = reason
                    review_id = f"{run_id}:{candidate['candidate_id']}"
                    run_review_ids.append(review_id)
                    if not any(item.get("review_id") == review_id for item in ledger["review_queue"] if isinstance(item, dict)):
                        ledger["review_queue"].append({
                            "review_id": review_id,
                            "run_id": run_id,
                            "date": run_date,
                            "candidate_id": candidate["candidate_id"],
                            "canonical_name": candidate["canonical_name"],
                            "reason": reason,
                        })
                    review_count += 1
                    continue

                platform, platform_id = pairs[0]
                entity_key = f"platform:{platform}:{platform_id}"
                entity_id = entity_key
                observed_at = _utc_iso(observed)
                record = ledger["entities"].get(entity_key)
                if record is None:
                    record = {
                        "entity_key": entity_key,
                        "entity_id": entity_id,
                        "platform": platform,
                        "platform_id": platform_id,
                        "canonical_name": candidate["canonical_name"],
                        "aliases": [],
                        "first_seen_at": observed_at,
                        "last_seen_at": observed_at,
                        "first_run_id": run_id,
                        "last_run_id": run_id,
                        "observation_count": 0,
                        "observed_run_ids": [],
                        "source_ids": [],
                        "evidence_refs": [],
                    }
                    ledger["entities"][entity_key] = record

                previous_name = record.get("canonical_name")
                aliases_before = set(record.get("aliases", []))
                if isinstance(previous_name, str) and previous_name.strip() and previous_name != candidate["canonical_name"]:
                    aliases_before.add(previous_name)
                    if previous_name not in record["aliases"]:
                        record["aliases"].append(previous_name)
                for alias in candidate.get("aliases", []):
                    if isinstance(alias, str) and alias.strip() and alias != record.get("canonical_name") and alias not in record["aliases"]:
                        record["aliases"].append(alias)
                if candidate["canonical_name"] and candidate["canonical_name"] != record.get("canonical_name"):
                    record["canonical_name"] = candidate["canonical_name"]

                first_seen = _parse_timestamp(record["first_seen_at"])
                last_seen = _parse_timestamp(record["last_seen_at"])
                if observed < first_seen:
                    record["first_seen_at"] = observed_at
                    record["first_run_id"] = run_id
                if observed > last_seen:
                    record["last_seen_at"] = observed_at
                    record["last_run_id"] = run_id

                if run_id not in record["observed_run_ids"]:
                    record["observed_run_ids"].append(run_id)
                    record["observation_count"] = len(record["observed_run_ids"])
                record["source_ids"] = sorted(set(record["source_ids"]) | set(_source_ids(candidate)))
                for ref in _evidence_refs(candidate):
                    if ref not in record["evidence_refs"]:
                        record["evidence_refs"].append(ref)

                candidate["entity_id"] = entity_id
                candidate["first_self_discovered_at"] = record["first_seen_at"]
                candidate["first_discovered_at"] = record["first_seen_at"]
                candidate["first_seen_status"] = "confirmed_stable_platform_id"
                candidate["first_seen_entity_key"] = entity_key
                candidate["entity_resolution"] = {
                    "status": "stable_platform_id",
                    "method": "cross_run_platform_id_ledger",
                    "confidence": 1.0,
                }
                candidate["aliases"] = sorted(set(candidate.get("aliases", [])) | aliases_before)
                run_entity_keys.append(entity_key)
                confirmed_count += 1

            if previous_run is None:
                ledger["revision"] += 1
                ledger["runs"][run_id] = {
                    "input_sha256": input_sha256,
                    "date": run_date,
                    "timezone": snapshot["timezone"],
                    "entity_keys": sorted(set(run_entity_keys)),
                    "review_ids": sorted(set(run_review_ids)),
                    "entities_confirmed": confirmed_count,
                    "needs_review": review_count,
                    "ledger_revision": ledger["revision"],
                }
                _validate_ledger(ledger)
                atomic_write_json(self.ledger_path, ledger, root=self.root)
            else:
                expected_entities = previous_run.get("entity_keys", [])
                expected_reviews = previous_run.get("review_ids", [])
                if sorted(set(run_entity_keys)) != expected_entities or sorted(set(run_review_ids)) != expected_reviews:
                    raise EntityLedgerConflict(f"run_id {run_id!r} was previously recorded with different entity resolution")

            content_sha256 = _snapshot_digest(enriched)
            enriched["first_seen_ledger"] = {
                "schema": "self-entity-first-seen-ledger-v1",
                "input_sha256": input_sha256,
                "content_sha256": content_sha256,
                "ledger_revision": previous_run.get("ledger_revision", ledger["revision"]) if previous_run else ledger["revision"],
                "run_id": run_id,
            }
            if output_path.exists() or output_path.is_symlink():
                existing = load_json(output_path)
                if existing != enriched:
                    raise EntityLedgerConflict(f"first-seen output already exists with different content: {output_path}")
            else:
                atomic_write_json(output_path, enriched, root=self.root)

            return {
                "status": "reused" if previous_run else "recorded",
                "run_id": run_id,
                "entities_confirmed": confirmed_count,
                "needs_review": review_count,
                "ledger_revision": ledger["revision"],
                "ledger_path": str(self.ledger_path),
                "output_path": str(output_path),
                "input_sha256": input_sha256,
            }
