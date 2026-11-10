"""Evidence-backed candidate identity resolution.

The resolver never calls an LLM or external service. It prepares a review plan
for ChatGPT/human adjudication, then applies only explicitly approved decisions.
Exact-name suggestions are advisory; they never merge candidates automatically.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError, validate_candidate_snapshot
from .normalize import normalize_entity_key

PLAN_SCHEMA = "self-candidate-resolution-plan-v1"
RESOLVER_VERSION = "candidate-resolver-v1"
ACTIONS = {"unresolved", "link_existing", "create_candidate", "not_game"}
APPROVALS = {"pending", "approved"}
VIDEO_SOURCE = "youtube"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        key = normalize_entity_key(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result


def _search_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _clue_id(run_id: str, item: dict[str, Any], index: int) -> str:
    raw = item.get("raw_record") if isinstance(item.get("raw_record"), dict) else {}
    key = {
        "run_id": run_id,
        "index": index,
        "source_id": item.get("source_id"),
        "source_record_id": item.get("source_record_id"),
        "query": raw.get("query"),
        "fetched_at": item.get("fetched_at"),
    }
    return hashlib.sha256(_stable_json(key).encode("utf-8")).hexdigest()[:24]


def _evidence_refs(item: dict[str, Any]) -> list[dict[str, str]]:
    refs = item.get("raw_evidence_refs")
    if not isinstance(refs, list):
        return []
    result = []
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("sha256"), str):
            result.append({"path": ref["path"], "sha256": ref["sha256"]})
    return result


def _suggest_matches(raw_record: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    haystacks = {
        "title": _search_text(raw_record.get("title")),
        "description_snippet": _search_text(raw_record.get("description_snippet")),
    }
    suggestions: list[dict[str, str]] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        names = [candidate.get("canonical_name"), *(candidate.get("aliases") or [])]
        for name in _unique_strings(names):
            needle = _search_text(name)
            # Short names create excessive false positives; keep them for human search only.
            if len(needle) < 5:
                continue
            for field, haystack in haystacks.items():
                if haystack and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
                    suggestions.append({
                        "candidate_id": str(candidate_id),
                        "candidate_name": str(candidate.get("canonical_name", "")),
                        "matched_field": field,
                        "matched_name": name,
                        "match_type": "exact_normalized_phrase_in_text",
                    })
                    break
    return suggestions


def prepare_resolution_plan(snapshot: dict[str, Any], *, input_path: str, input_sha256: str) -> dict[str, Any]:
    """Create a deterministic, review-only plan; no decision is pre-approved."""
    validate_candidate_snapshot(snapshot)
    candidates = snapshot["candidates"]
    decisions: list[dict[str, Any]] = []
    for index, item in enumerate(snapshot.get("unparsed_items", [])):
        if not isinstance(item, dict):
            continue
        raw = item.get("raw_record") if isinstance(item.get("raw_record"), dict) else {}
        decisions.append({
            "clue_id": _clue_id(snapshot["run_id"], item, index),
            "source_id": item.get("source_id"),
            "source_record_id": item.get("source_record_id"),
            "query": raw.get("query"),
            "query_role": raw.get("query_role"),
            "title": raw.get("title"),
            "description_snippet": raw.get("description_snippet"),
            "channel_name": raw.get("channel_name"),
            "channel_id": raw.get("channel_id"),
            "video_url": raw.get("url"),
            "published_time_text": raw.get("published_time_text"),
            "fetched_at": item.get("fetched_at"),
            "raw_evidence_refs": _evidence_refs(item),
            "matching_suggestions": _suggest_matches(raw, candidates),
            "action": "unresolved",
            "approval_status": "pending",
            "target_candidate_id": None,
            "canonical_name": None,
            "aliases": [],
            "reason": None,
            "reviewed_by": None,
        })
    return {
        "schema": PLAN_SCHEMA,
        "resolver_version": RESOLVER_VERSION,
        "run_id": snapshot["run_id"],
        "date": snapshot["date"],
        "input_path": str(Path(input_path).absolute()),
        "input_sha256": input_sha256,
        "candidate_index": [
            {
                "candidate_id": candidate.get("candidate_id"),
                "canonical_name": candidate.get("canonical_name"),
                "aliases": list(candidate.get("aliases", [])),
                "platforms": list(candidate.get("platforms", [])),
                "platform_ids": dict(candidate.get("platform_ids", {})) if isinstance(candidate.get("platform_ids"), dict) else {},
                "source_ids": sorted({
                    source.get("source_id") for source in candidate.get("sources", [])
                    if isinstance(source, dict) and isinstance(source.get("source_id"), str)
                }),
                "discovery_reasons": list(candidate.get("discovery_reasons", [])),
                "raw_evidence_refs": _evidence_refs(candidate),
            }
            for candidate in candidates
        ],
        "instructions": {
            "automatic_merging": False,
            "exact_name_matches_are_suggestions_only": True,
            "video_id_is_not_a_game_id": True,
            "only_approved_decisions_are_applied": True,
            "allowed_actions": sorted(ACTIONS),
            "reviewed_by_required_for_approval": True,
        },
        "decisions": decisions,
        "merges": [],
    }


def _require_nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_refs(refs: object, allowed: list[dict[str, str]], name: str) -> list[dict[str, str]]:
    if not isinstance(refs, list):
        raise ContractError(f"{name} must be an array")
    allowed_set = {(ref["path"], ref["sha256"]) for ref in allowed}
    normalized: list[dict[str, str]] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise ContractError(f"{name}[{index}] must be an object")
        path = _require_nonempty(ref.get("path"), f"{name}[{index}].path")
        digest = _require_nonempty(ref.get("sha256"), f"{name}[{index}].sha256")
        if (path, digest) not in allowed_set:
            raise ContractError(f"{name}[{index}] is not present in the source evidence")
        evidence_path = Path(path)
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise ContractError(f"{name}[{index}] evidence file is missing or is a symlink")
        if file_sha256(evidence_path) != digest:
            raise ContractError(f"{name}[{index}] evidence SHA-256 does not match the source snapshot")
        normalized.append({"path": path, "sha256": digest})
    if not normalized:
        raise ContractError(f"{name} must contain at least one source evidence reference")
    return normalized


def _timestamp_or_none(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _append_unique(target: list, values: list) -> None:
    seen = {_stable_json(value) for value in target}
    for value in values:
        marker = _stable_json(value)
        if marker not in seen:
            target.append(value)
            seen.add(marker)


def _supplementary_evidence(clue: dict[str, Any], decision: dict[str, Any], refs: list[dict[str, str]]) -> dict[str, Any]:
    raw = clue.get("raw_record") if isinstance(clue.get("raw_record"), dict) else {}
    return {
        "source_id": "youtube",
        "source_record_id": str(clue.get("source_record_id")),
        "video_url": raw.get("url"),
        "title": raw.get("title"),
        "channel_name": raw.get("channel_name"),
        "channel_id": raw.get("channel_id"),
        "query": raw.get("query"),
        "query_role": raw.get("query_role"),
        "published_time_text": raw.get("published_time_text"),
        "published_at": None,
        "fetched_at": clue.get("fetched_at"),
        "description_snippet": raw.get("description_snippet"),
        "raw_evidence_refs": refs,
        "identity_decision": {
            "action": decision["action"],
            "reason": decision["reason"],
            "reviewed_by": decision["reviewed_by"],
            "clue_id": decision["clue_id"],
        },
    }


def _candidate_quality(candidate: dict[str, Any]) -> dict[str, Any]:
    platform_ids = candidate.get("platform_ids") if isinstance(candidate.get("platform_ids"), dict) else {}
    stable_ids = {
        str(platform): str(value)
        for platform, value in platform_ids.items()
        if isinstance(platform, str) and isinstance(value, (str, int)) and str(value).strip()
    }
    sources = candidate.get("sources") if isinstance(candidate.get("sources"), list) else []
    supplementary = candidate.get("supplementary_evidence") if isinstance(candidate.get("supplementary_evidence"), list) else []
    source_ids = {
        item.get("source_id") for item in sources + supplementary
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    evidence = candidate.get("raw_evidence_refs") if isinstance(candidate.get("raw_evidence_refs"), list) else []
    resolution = candidate.get("entity_resolution") if isinstance(candidate.get("entity_resolution"), dict) else {}
    if len(stable_ids) == 1 and evidence:
        tier = "B" if len(source_ids) < 2 else "A"
        status = "stable_platform_identity"
    elif resolution.get("status") in {"reviewed_name_only", "human_adjudicated_cross_platform_merge"}:
        tier = "C"
        status = "reviewed_name_without_single_platform_identity"
    else:
        tier = "REVIEW"
        status = "identity_or_platform_review_required"
    return {
        "tier": tier,
        "identity_status": status,
        "stable_platform_id_count": len(stable_ids),
        "independent_source_count": len(source_ids),
        "evidence_ref_count": len(evidence),
        "requires_review": tier in {"C", "REVIEW"} or len(stable_ids) != 1,
    }


def _merge_candidate_records(primary: dict[str, Any], secondary: dict[str, Any], merge: dict[str, Any]) -> None:
    primary_ids = primary.get("platform_ids") if isinstance(primary.get("platform_ids"), dict) else {}
    secondary_ids = secondary.get("platform_ids") if isinstance(secondary.get("platform_ids"), dict) else {}
    combined_ids = dict(primary_ids)
    for platform, platform_id in secondary_ids.items():
        if platform in combined_ids and str(combined_ids[platform]) != str(platform_id):
            raise ContractError(
                f"cannot merge candidates with conflicting {platform} IDs: "
                f"{combined_ids[platform]} vs {platform_id}"
            )
        combined_ids[platform] = platform_id

    old_primary_name = primary.get("canonical_name")
    old_secondary_name = secondary.get("canonical_name")
    canonical = merge.get("canonical_name") or old_primary_name
    if not isinstance(canonical, str) or not canonical.strip():
        raise ContractError("merge canonical_name must be a non-empty string")
    aliases = _unique_strings([
        *(primary.get("aliases") or []),
        *(secondary.get("aliases") or []),
        old_primary_name,
        old_secondary_name,
        *(merge.get("aliases") or []),
    ])
    aliases = [alias for alias in aliases if normalize_entity_key(alias) != normalize_entity_key(canonical)]

    for key in ("raw_titles", "sources", "origin_events", "raw_evidence_refs", "source_metadata", "supplementary_evidence", "discovery_reasons", "platform_signals", "missing_fields", "merged_candidate_ids"):
        primary.setdefault(key, [])
        secondary_values = secondary.get(key, [])
        if isinstance(secondary_values, list):
            _append_unique(primary[key], secondary_values)

    primary["canonical_name"] = canonical.strip()
    primary["aliases"] = [alias for alias in aliases if normalize_entity_key(alias) != normalize_entity_key(canonical)]
    primary["platform_ids"] = combined_ids
    merge_refs = merge.get("evidence_refs", [])
    primary.setdefault("raw_evidence_refs", [])
    _append_unique(primary["raw_evidence_refs"], merge_refs)
    primary["platforms"] = sorted(set(primary.get("platforms", [])) | set(secondary.get("platforms", [])) | set(combined_ids.keys()))
    primary["merged_candidate_ids"] = sorted(set(primary.get("merged_candidate_ids", [])) | {secondary["candidate_id"]} | set(secondary.get("merged_candidate_ids", [])))
    primary["entity_resolution"] = {
        "status": "human_adjudicated_cross_platform_merge",
        "method": "approved_candidate_resolution_plan",
        "confidence": 1.0,
        "reviewed_by": merge["reviewed_by"],
        "reason": merge["reason"],
    }
    primary["candidate_quality"] = _candidate_quality(primary)


def validate_resolution_plan(plan: Any, snapshot: dict[str, Any], *, input_sha256: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ContractError("unsupported candidate resolution plan schema")
    if plan.get("resolver_version") != RESOLVER_VERSION:
        raise ContractError("unsupported resolver version")
    if plan.get("run_id") != snapshot.get("run_id"):
        raise ContractError("resolution plan run_id does not match candidate snapshot")
    if plan.get("input_sha256") != input_sha256:
        raise ContractError("resolution plan input_sha256 does not match the original candidate file")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list):
        raise ContractError("resolution plan decisions must be an array")
    clues = snapshot.get("unparsed_items", [])
    clue_map = {
        _clue_id(snapshot["run_id"], clue, index): clue
        for index, clue in enumerate(clues) if isinstance(clue, dict)
    }
    seen: set[str] = set()
    candidate_ids = {item.get("candidate_id") for item in snapshot["candidates"]}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ContractError(f"decisions[{index}] must be an object")
        clue_id = _require_nonempty(decision.get("clue_id"), f"decisions[{index}].clue_id")
        if clue_id not in clue_map:
            raise ContractError(f"decisions[{index}] references an unknown clue_id")
        if clue_id in seen:
            raise ContractError(f"duplicate decision for clue_id {clue_id}")
        seen.add(clue_id)
        action = decision.get("action")
        if action not in ACTIONS:
            raise ContractError(f"decisions[{index}].action is invalid")
        approval = decision.get("approval_status", "pending")
        if approval not in APPROVALS:
            raise ContractError(f"decisions[{index}].approval_status is invalid")
        if approval != "approved":
            continue
        reviewed_by = _require_nonempty(decision.get("reviewed_by"), f"decisions[{index}].reviewed_by")
        _require_nonempty(decision.get("reason"), f"decisions[{index}].reason")
        clue = clue_map[clue_id]
        if clue.get("source_id") != VIDEO_SOURCE:
            raise ContractError("only YouTube clues may be adjudicated by this resolver version")
        raw = clue.get("raw_record") if isinstance(clue.get("raw_record"), dict) else {}
        if not _require_nonempty(raw.get("video_id"), f"clue {clue_id}.video_id"):
            raise ContractError("YouTube clue requires a video_id")
        _validate_refs(decision.get("evidence_refs", _evidence_refs(clue)), _evidence_refs(clue), f"decisions[{index}].evidence_refs")
        if action == "link_existing":
            target = _require_nonempty(decision.get("target_candidate_id"), f"decisions[{index}].target_candidate_id")
            if target not in candidate_ids:
                raise ContractError(f"decisions[{index}] target_candidate_id does not exist")
        elif action == "create_candidate":
            _require_nonempty(decision.get("canonical_name"), f"decisions[{index}].canonical_name")
        elif action == "not_game":
            pass
        elif action == "unresolved":
            raise ContractError("an unresolved decision cannot be approved")
    if seen != set(clue_map):
        missing = sorted(set(clue_map) - seen)
        extra = sorted(seen - set(clue_map))
        raise ContractError(f"resolution plan must cover every clue exactly once; missing={missing}, extra={extra}")

    merges = plan.get("merges", [])
    if not isinstance(merges, list):
        raise ContractError("resolution plan merges must be an array")
    for index, merge in enumerate(merges):
        if not isinstance(merge, dict):
            raise ContractError(f"merges[{index}] must be an object")
        if merge.get("approval_status", "pending") != "approved":
            continue
        primary = _require_nonempty(merge.get("primary_candidate_id"), f"merges[{index}].primary_candidate_id")
        secondary = _require_nonempty(merge.get("secondary_candidate_id"), f"merges[{index}].secondary_candidate_id")
        if primary == secondary or primary not in candidate_ids or secondary not in candidate_ids:
            raise ContractError(f"merges[{index}] candidate IDs are invalid")
        _require_nonempty(merge.get("reviewed_by"), f"merges[{index}].reviewed_by")
        _require_nonempty(merge.get("reason"), f"merges[{index}].reason")
        primary_candidate = next(item for item in snapshot["candidates"] if item["candidate_id"] == primary)
        secondary_candidate = next(item for item in snapshot["candidates"] if item["candidate_id"] == secondary)
        allowed = _evidence_refs(primary_candidate) + _evidence_refs(secondary_candidate)
        _validate_refs(merge.get("evidence_refs"), allowed, f"merges[{index}].evidence_refs")
    return plan


def resolve_candidate_snapshot(snapshot: dict[str, Any], plan: dict[str, Any], *, input_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply approved decisions to a copy; preserve all source clues for audit."""
    validate_candidate_snapshot(snapshot)
    validate_resolution_plan(plan, snapshot, input_sha256=input_sha256)
    resolved = copy.deepcopy(snapshot)
    original_clues = resolved.get("unparsed_items", [])
    clue_map = {
        _clue_id(resolved["run_id"], clue, index): clue
        for index, clue in enumerate(original_clues) if isinstance(clue, dict)
    }
    candidate_map = {item["candidate_id"]: item for item in resolved["candidates"]}
    id_redirects: dict[str, str] = {}
    applied = {"linked": 0, "created": 0, "excluded_not_game": 0, "merged": 0}
    pending = 0

    for decision in plan["decisions"]:
        clue = clue_map[decision["clue_id"]]
        if decision.get("approval_status", "pending") != "approved":
            clue["resolution_status"] = "pending_review"
            pending += 1
            continue
        action = decision["action"]
        refs = _validate_refs(decision.get("evidence_refs", _evidence_refs(clue)), _evidence_refs(clue), "decision.evidence_refs")
        evidence = _supplementary_evidence(clue, decision, refs)
        if action == "link_existing":
            target_id = id_redirects.get(decision["target_candidate_id"], decision["target_candidate_id"])
            target = candidate_map.get(target_id)
            if target is None:
                raise ContractError(f"approved link target no longer exists: {target_id}")
            target.setdefault("supplementary_evidence", [])
            _append_unique(target["supplementary_evidence"], [evidence])
            aliases = _unique_strings(decision.get("aliases", []))
            target_keys = {normalize_entity_key(target.get("canonical_name", "")), *(normalize_entity_key(item) for item in target.get("aliases", []))}
            for alias in aliases:
                alias_key = normalize_entity_key(alias)
                if not alias_key or alias_key in target_keys:
                    continue
                conflicts = [
                    other for other in resolved["candidates"]
                    if other is not target and alias_key in {
                        normalize_entity_key(other.get("canonical_name", "")),
                        *(normalize_entity_key(item) for item in other.get("aliases", [])),
                    }
                ]
                if conflicts:
                    raise ContractError(f"approved alias {alias!r} conflicts with another candidate; use an explicit merge decision")
            target["aliases"] = _unique_strings([*(target.get("aliases") or []), *aliases])
            target.setdefault("discovery_reasons", [])
            reason = f"YouTube clue linked after review: {decision['reason']}"
            if reason not in target["discovery_reasons"]:
                target["discovery_reasons"].append(reason)
            target["raw_evidence_refs"] = target.get("raw_evidence_refs", [])
            _append_unique(target["raw_evidence_refs"], refs)
            clue["resolution_status"] = "linked_to_candidate"
            clue["resolved_candidate_id"] = target_id
            applied["linked"] += 1
        elif action == "create_candidate":
            canonical = _require_nonempty(decision.get("canonical_name"), "decision.canonical_name")
            canonical_key = normalize_entity_key(canonical)
            if any(
                canonical_key in {
                    normalize_entity_key(item.get("canonical_name", "")),
                    *(normalize_entity_key(alias) for alias in item.get("aliases", [])),
                }
                for item in resolved["candidates"]
            ):
                raise ContractError("new candidate name already matches an existing candidate; link or explicitly merge instead")
            aliases = _unique_strings(decision.get("aliases", []))
            clue_id = decision["clue_id"]
            candidate_id = hashlib.sha256(
                f"{resolved['run_id']}:youtube:{clue_id}:{normalize_entity_key(canonical)}".encode("utf-8")
            ).hexdigest()[:24]
            if candidate_id in candidate_map:
                raise ContractError(f"new candidate ID collision: {candidate_id}")
            observed_at = _timestamp_or_none(clue.get("fetched_at"))
            if observed_at is None:
                raise ContractError("cannot create a YouTube-derived candidate without an absolute fetched_at timestamp")
            candidate = {
                "candidate_id": candidate_id,
                "entity_id": f"provisional:{candidate_id}",
                "canonical_name": canonical,
                "aliases": [alias for alias in aliases if normalize_entity_key(alias) != normalize_entity_key(canonical)],
                "raw_titles": [canonical],
                "entity_resolution": {
                    "status": "reviewed_name_only",
                    "method": "approved_youtube_identity_resolution",
                    "confidence": 1.0,
                    "reviewed_by": decision["reviewed_by"],
                },
                "platforms": [],
                "platform_ids": {},
                "discovery_origin": "self_discovered",
                "origin_events": [{
                    "origin": "self_discovered",
                    "source_id": "youtube",
                    "observed_at": observed_at,
                    "run_id": resolved["run_id"],
                }],
                "first_discovered_at": observed_at,
                "first_self_discovered_at": observed_at,
                "independent_eligibility": {
                    "eligible": None,
                    "reason": "YouTube identity was reviewed but no stable game-platform ID is available",
                },
                "sources": [],
                "source_metadata": [],
                "supplementary_evidence": [evidence],
                "platform_signals": [],
                "discovery_reasons": [decision["reason"]],
                "raw_evidence_refs": refs,
                "missing_fields": ["stable_platform_id"],
                "candidate_quality": {
                    "tier": "C",
                    "identity_status": "reviewed_name_without_stable_platform_id",
                    "stable_platform_id_count": 0,
                    "independent_source_count": 1,
                    "evidence_ref_count": len(refs),
                    "requires_review": True,
                },
            }
            resolved["candidates"].append(candidate)
            candidate_map[candidate_id] = candidate
            clue["resolution_status"] = "promoted_to_reviewed_name_candidate"
            clue["resolved_candidate_id"] = candidate_id
            applied["created"] += 1
        elif action == "not_game":
            clue["resolution_status"] = "excluded_not_game"
            clue["resolution_reason"] = decision["reason"]
            clue["reviewed_by"] = decision["reviewed_by"]
            applied["excluded_not_game"] += 1
        else:
            clue["resolution_status"] = "pending_review"
            pending += 1

    for merge in plan.get("merges", []):
        if merge.get("approval_status", "pending") != "approved":
            continue
        primary_id = id_redirects.get(merge["primary_candidate_id"], merge["primary_candidate_id"])
        secondary_id = id_redirects.get(merge["secondary_candidate_id"], merge["secondary_candidate_id"])
        if primary_id == secondary_id:
            raise ContractError("merge resolves both candidate IDs to the same entity")
        primary = candidate_map.get(primary_id)
        secondary = candidate_map.get(secondary_id)
        if primary is None or secondary is None:
            raise ContractError("merge references a missing candidate after a previous merge")
        _merge_candidate_records(primary, secondary, merge)
        resolved["candidates"].remove(secondary)
        candidate_map.pop(secondary_id)
        id_redirects[secondary_id] = primary_id
        applied["merged"] += 1

    for clue in original_clues:
        resolved_id = clue.get("resolved_candidate_id") if isinstance(clue, dict) else None
        if isinstance(resolved_id, str):
            clue["resolved_candidate_id"] = id_redirects.get(resolved_id, resolved_id)

    for candidate in resolved["candidates"]:
        candidate["candidate_quality"] = _candidate_quality(candidate)

    resolved["counts"] = dict(resolved.get("counts", {}))
    resolved["counts"]["entities"] = len(resolved["candidates"])
    resolved["resolution"] = {
        "schema": "self-candidate-resolution-result-v1",
        "resolver_version": RESOLVER_VERSION,
        "plan_input_sha256": input_sha256,
        "applied": applied,
        "pending_clues": pending,
        "remaining_unparsed": sum(
            1 for clue in original_clues
            if clue.get("resolution_status") in {None, "pending_review"}
        ),
        "source_clues_preserved": len(original_clues),
        "automatic_merges": 0,
        "review_required_for_platformless_candidates": True,
    }
    validate_candidate_snapshot(resolved)
    report = {
        "schema": "self-candidate-resolution-report-v1",
        "run_id": resolved["run_id"],
        "input_sha256": input_sha256,
        "resolver_version": RESOLVER_VERSION,
        "applied": applied,
        "pending_clues": pending,
        "remaining_unparsed": resolved["resolution"]["remaining_unparsed"],
        "candidate_count_before": len(snapshot["candidates"]),
        "candidate_count_after": len(resolved["candidates"]),
        "quality_tiers": {
            tier: sum(1 for item in resolved["candidates"] if item.get("candidate_quality", {}).get("tier") == tier)
            for tier in ("A", "B", "C", "REVIEW")
        },
        "note": "Only approved, evidence-bound decisions were applied. YouTube video IDs were never written as game platform IDs.",
    }
    return resolved, report
