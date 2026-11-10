"""Command-line interface for local validation and explicit source collection."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .benchmark import compare_snapshots
from .benchmark_snapshot import read_archived_api_snapshot
from .contracts import ContractError, validate_file, load_json
from .ingest_reader import read_api_ingest_morning_batch
from .entity_ledger import EntityFirstSeenLedger
from .rule_replay import replay_rules
from .rules import evaluate_feature_groups
from .sources import SourceRequest, SourceResult, merge_source_results
from .storage import StorageError, atomic_write_json


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trendgpt", description="Isolated Lesson 14 discovery tools")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate one self-v1 JSON artifact")
    validate.add_argument("--kind", choices=("candidate", "verified", "benchmark", "run-result", "state"), required=True)
    validate.add_argument("--input", required=True)

    snapshot = sub.add_parser("snapshot-api", help="read an archived API raw file; never calls the API")
    snapshot.add_argument("--input", required=True, help="path to an already archived raw JSON file")
    snapshot.add_argument("--output-root", required=True, help="explicit path ending in self-v1")
    snapshot.add_argument("--acquired-at", required=True, help="RFC3339 timestamp with timezone")

    ingest_snapshot = sub.add_parser(
        "snapshot-api-ingest",
        help="read the earliest successful local TrendOracle morning ingest for a Shanghai date; no network access",
    )
    ingest_snapshot.add_argument("--ingest-root", required=True, help="local trendoracle-ingest Skill root")
    ingest_snapshot.add_argument("--date", required=True, help="Shanghai business date YYYY-MM-DD")
    ingest_snapshot.add_argument("--output-root", required=True, help="explicit path ending in self-v1")

    first_seen = sub.add_parser("record-first-seen", help="record stable platform-ID first-seen history across self-v1 runs")
    first_seen.add_argument("--input", required=True, help="candidate_keywords.json from one completed self-discovery run")
    first_seen.add_argument("--output-root", required=True, help="explicit path ending in self-v1")

    fetch = sub.add_parser("fetch-source", help="fetch one bounded page from a configured public source")
    fetch.add_argument("--source", choices=("steam", "roblox", "youtube"), required=True)
    fetch.add_argument("--scope-json", required=True, help="JSON object defining list_type/query and source scope")
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--fetched-at", required=True, help="RFC3339 timestamp with timezone")
    fetch.add_argument("--output-root", required=True, help="explicit path ending in self-v1")
    fetch.add_argument("--cursor")
    fetch.add_argument("--page-limit", type=int, default=50)
    fetch.add_argument("--network-enabled", action="store_true", help="explicit opt-in to a public HTTPS read")

    collect = sub.add_parser("collect", help="collect a bounded multi-source candidate snapshot")
    collect.add_argument("--source-plan", required=True, help="JSON file using config/source-plan.example.json shape")
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--date", required=True, help="YYYY-MM-DD in the configured business timezone")
    collect.add_argument("--slot", required=True, help="caller-supplied run slot, e.g. 00, 04, 08")
    collect.add_argument("--timezone", required=True, help="IANA business timezone")
    collect.add_argument("--started-at", required=True, help="RFC3339 timestamp with timezone")
    collect.add_argument("--output-root", required=True, help="explicit path ending in self-v1")
    collect.add_argument("--max-pages-per-source", type=int, default=3)
    collect.add_argument("--network-enabled", action="store_true", help="explicit opt-in to public HTTPS reads")

    compare = sub.add_parser("compare", help="compare an API benchmark to self-discovery snapshots")
    compare.add_argument("--benchmark", required=True)
    compare.add_argument("--self-snapshot", action="append", default=[])
    compare.add_argument("--cutoff", required=True, help="RFC3339 timestamp with timezone")
    compare.add_argument("--benchmark-disabled", action="store_true")

    evaluate = sub.add_parser("evaluate-rules", help="summarize mature revenue by feature group; never changes rules")
    evaluate.add_argument("--input", required=True, help="JSON array of observation records")
    evaluate.add_argument("--minimum-samples", type=int, default=5)

    replay = sub.add_parser("replay-rules", help="compare two rule versions on frozen candidates without publishing")
    replay.add_argument("--candidates", required=True, help="JSON array of candidate objects")
    replay.add_argument("--baseline-rules", required=True)
    replay.add_argument("--proposed-rules", required=True)
    replay.add_argument("--outcomes", required=True, help="JSON array of candidate outcome records")
    return parser


def _make_adapter(source: str):
    if source == "steam":
        from .adapters.steam import SteamSearchAdapter
        return SteamSearchAdapter()
    if source == "roblox":
        from .adapters.roblox import RobloxChartAdapter
        return RobloxChartAdapter()
    if source == "youtube":
        from .adapters.youtube_search import YouTubeSearchAdapter
        return YouTubeSearchAdapter()
    raise ContractError(f"unknown source: {source}")


def _fetch_source(args: argparse.Namespace) -> dict[str, Any]:
    if not args.network_enabled:
        raise ContractError("source fetch is disabled by default; pass --network-enabled for an explicit public read")
    root = Path(args.output_root).absolute()
    if root.name != "self-v1":
        raise ContractError("output root must end in self-v1")
    scope = load_json(args.scope_json)
    if not isinstance(scope, dict):
        raise ContractError("scope JSON must be an object")
    if args.page_limit < 1 or args.page_limit > 50:
        raise ContractError("page-limit must be between 1 and 50")
    request = SourceRequest(
        run_id=args.run_id, source_id=args.source, fetched_at=args.fetched_at,
        scope=scope, evidence_root=str(root), cursor=args.cursor, page_limit=args.page_limit,
    )
    result = _make_adapter(args.source).fetch(request).validate()
    run_key = sha256(args.run_id.encode("utf-8")).hexdigest()[:16]
    cursor_key = args.cursor or "first"
    output_path = root / "runs" / run_key / f"{args.source}-{cursor_key}.json"
    atomic_write_json(output_path, result.to_dict(), root=root)
    return {
        "status": result.status, "source_id": result.source_id, "items": len(result.items),
        "next_cursor": result.next_cursor, "evidence_refs": result.evidence_refs,
        "errors": result.errors, "output_path": str(output_path), "source_fetch_calls": 1,
    }


def _collect(args: argparse.Namespace) -> dict[str, Any]:
    if not args.network_enabled:
        raise ContractError("collection is disabled by default; pass --network-enabled for explicit public reads")
    root = Path(args.output_root).absolute()
    if root.name != "self-v1":
        raise ContractError("output root must end in self-v1")
    if args.max_pages_per_source < 1 or args.max_pages_per_source > 10:
        raise ContractError("max-pages-per-source must be between 1 and 10")
    try:
        date.fromisoformat(args.date)
        ZoneInfo(args.timezone)
        started = datetime.fromisoformat(args.started_at.replace("Z", "+00:00"))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ContractError("date, timezone, or started-at is invalid") from exc
    if started.tzinfo is None:
        raise ContractError("started-at must include a timezone offset")
    plan = load_json(args.source_plan)
    if not isinstance(plan, dict) or plan.get("schema") != "trendgpt-source-plan-v1" or not isinstance(plan.get("sources"), list):
        raise ContractError("source plan must use schema trendgpt-source-plan-v1 with a sources array")

    run_key = sha256(args.run_id.encode("utf-8")).hexdigest()[:16]
    source_results: list[SourceResult] = []
    source_summary: list[dict[str, Any]] = []
    abort_remaining_sources = False

    for source_index, spec in enumerate(plan["sources"]):
        if abort_remaining_sources:
            break
        if not isinstance(spec, dict) or spec.get("source") not in {"steam", "roblox", "youtube"}:
            raise ContractError(f"source plan entry {source_index} has an invalid source")
        source = spec["source"]
        scope = spec.get("scope")
        if not isinstance(scope, dict):
            raise ContractError(f"source plan entry {source_index} requires a scope object")
        try:
            page_limit = int(spec.get("page_limit", 50))
            configured_max = int(spec.get("max_pages", args.max_pages_per_source))
        except (TypeError, ValueError) as exc:
            raise ContractError(f"source plan entry {source_index} has invalid page limits") from exc
        max_pages = min(configured_max, args.max_pages_per_source)
        if page_limit < 1 or page_limit > 50 or max_pages < 1:
            raise ContractError(f"source plan entry {source_index} has invalid page limits")

        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages: list[SourceResult] = []
        stop_reason = "max_pages_reached"
        adapter = _make_adapter(source)

        for page_number in range(max_pages):
            cursor_key = cursor if cursor is not None else "0"
            if cursor_key in seen_cursors:
                stop_reason = "pagination_cursor_cycle"
                break
            seen_cursors.add(cursor_key)

            request = SourceRequest(
                run_id=f"{args.run_id}-{source_index}",
                source_id=source,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                scope={**scope, "source_plan_index": source_index},
                evidence_root=str(root),
                cursor=cursor,
                page_limit=page_limit,
            )
            result = adapter.fetch(request).validate()
            pages.append(result)

            page_path = root / "runs" / run_key / f"{source}-{source_index}-page-{page_number + 1:02d}.json"
            atomic_write_json(page_path, result.to_dict(), root=root)

            if result.status in {"failed", "blocked"}:
                stop_reason = "source_error"
                if source == "roblox" or any(error.get("retryable") is True for error in result.errors):
                    # Roblox's public Explore host is shared by both boards. If one
                    # board is blocked or errors, stop the remaining Roblox requests
                    # rather than compounding a host-level throttle/challenge.
                    abort_remaining_sources = True
                break
            result_coverage = result.coverage if isinstance(result.coverage, dict) else {}
            if result_coverage.get("overflow_rows", 0):
                stop_reason = "server_exceeded_max_rows"
                # Do not follow an opaque token after truncating an oversized page:
                # the token may skip rows that were not admitted to this snapshot.
                break
            if not result.next_cursor:
                stop_reason = "source_reported_no_next_cursor"
                break

            next_cursor = str(result.next_cursor)
            if next_cursor == cursor_key or next_cursor in seen_cursors:
                stop_reason = "pagination_cursor_cycle"
                break
            cursor = next_cursor
        else:
            if pages and pages[-1].next_cursor:
                stop_reason = "max_pages_reached"
            else:
                stop_reason = "source_reported_no_next_cursor"

        page_starts: list[int] = []
        page_sizes: list[int] = []
        totals: list[int] = []
        pagination_modes: set[str] = set()
        all_pages_complete = bool(pages)
        all_items: list[dict[str, Any]] = []
        all_evidence_refs: list[dict[str, str]] = []
        all_errors: list[dict[str, Any]] = []
        seen_platform_ids: set[str] = set()
        duplicate_ids_across_pages = 0
        raw_rows_seen = 0

        for page_index, page in enumerate(pages):
            coverage = page.coverage if isinstance(page.coverage, dict) else {}
            raw_start = coverage.get("page_start", page.cursor)
            if isinstance(raw_start, int) and not isinstance(raw_start, bool):
                page_starts.append(raw_start)
            raw_size = coverage.get("page_size", page_limit)
            if isinstance(raw_size, int) and not isinstance(raw_size, bool):
                page_sizes.append(raw_size)
            raw_total = coverage.get("total_results")
            if isinstance(raw_total, int) and not isinstance(raw_total, bool):
                totals.append(raw_total)
            pagination_mode = coverage.get("pagination_mode")
            if isinstance(pagination_mode, str) and pagination_mode:
                pagination_modes.add(pagination_mode)
            page_raw_rows = coverage.get("raw_rows")
            if not isinstance(page_raw_rows, int) or isinstance(page_raw_rows, bool) or page_raw_rows < 0:
                page_raw_rows = len(page.items)

            all_pages_complete = all_pages_complete and coverage.get("page_complete") is True
            for position, item in enumerate(page.items):
                page_filter = page.scope.get("filter") or page.scope.get("steam_filter")
                enriched = {
                    **item,
                    "source_page_index": page_index,
                    "source_page_cursor": page.cursor,
                    "source_page_position": position,
                    "source_fetched_at": page.fetched_at,
                }
                if isinstance(page_filter, str) and page_filter:
                    enriched["filter"] = page_filter
                    enriched["steam_filter"] = page_filter
                    enriched["source_filter"] = page_filter
                    enriched["filter_source"] = "request_query_parameter"
                if pagination_mode == "opaque_page_token":
                    local_rank = item.get("source_rank")
                    if isinstance(local_rank, int) and not isinstance(local_rank, bool) and local_rank > 0:
                        enriched["source_rank"] = raw_rows_seen + local_rank
                    else:
                        enriched["source_rank"] = raw_rows_seen + position + 1
                elif isinstance(raw_start, int) and not isinstance(raw_start, bool):
                    enriched["source_rank"] = raw_start + position + 1
                platform_id = enriched.get("platform_id") or enriched.get("source_record_id")
                if isinstance(platform_id, (str, int)):
                    key = str(platform_id)
                    if key in seen_platform_ids:
                        duplicate_ids_across_pages += 1
                    else:
                        seen_platform_ids.add(key)
                all_items.append(enriched)

            raw_rows_seen += page_raw_rows
            for ref in page.evidence_refs:
                if ref not in all_evidence_refs:
                    all_evidence_refs.append(ref)
            for error in page.errors:
                all_errors.append({"page_index": page_index, **error})

        totals_consistent = bool(totals) and len(set(totals)) == 1 and len(totals) == len(pages)
        total_results = totals[0] if totals_consistent else None
        page_size_consistent = bool(page_sizes) and len(set(page_sizes)) == 1 and len(page_sizes) == len(pages)
        page_size_used = page_sizes[0] if page_size_consistent else None
        sequential_pages = (
            page_size_used is not None
            and page_starts == [index * page_size_used for index in range(len(page_starts))]
            and len(page_starts) == len(pages)
        )
        unique_platform_ids = len(seen_platform_ids)
        if pagination_modes == {"opaque_page_token"}:
            # Roblox chart pagination is token-based and does not expose a
            # trustworthy total count. "Complete" means the server supplied no
            # nextPageToken and every returned row was parsed without duplicates;
            # it never means the full Roblox catalog was crawled.
            pagination_complete = (
                stop_reason == "source_reported_no_next_cursor"
                and all_pages_complete
                and raw_rows_seen == len(all_items)
                and unique_platform_ids == len(all_items)
                and duplicate_ids_across_pages == 0
            )
        else:
            pagination_complete = (
                stop_reason == "source_reported_no_next_cursor"
                and all_pages_complete
                and totals_consistent
                and page_size_consistent
                and sequential_pages
                and total_results is not None
                and unique_platform_ids == total_results
                and len(all_items) == unique_platform_ids
                and duplicate_ids_across_pages == 0
            )
        if not pages:
            aggregate_status = "failed"
        elif not all_items and all(page.status == "blocked" for page in pages):
            aggregate_status = "blocked"
        elif not all_items and all(page.status == "failed" for page in pages):
            aggregate_status = "failed"
        else:
            aggregate_status = "complete" if pagination_complete else "partial"
        if duplicate_ids_across_pages:
            all_errors.append({
                "code": "duplicate_platform_ids_across_pages",
                "retryable": False,
                "count": duplicate_ids_across_pages,
            })

        last_page = pages[-1] if pages else None
        aggregate_next_cursor = (
            None if pagination_complete or last_page is None or stop_reason == "server_exceeded_max_rows"
            else last_page.next_cursor
        )
        aggregate_scope = {
            **scope,
            "source_plan_index": source_index,
            "page_limit": page_limit,
            "max_pages": max_pages,
        }
        if pagination_modes:
            aggregate_scope["pagination_mode"] = sorted(pagination_modes)[0] if len(pagination_modes) == 1 else "mixed"
        for scope_key in ("sort_id",):
            values = [page.scope.get(scope_key) for page in pages]
            if values and all(value is not None for value in values) and len(set(values)) == 1:
                aggregate_scope[scope_key] = values[0]
        if source == "roblox":
            # For Roblox, country/device are effective response scope, not the
            # requested query values. Never copy the plan values into these fields.
            aggregate_scope["requested_country"] = scope.get("country")
            aggregate_scope["requested_device"] = scope.get("device")
            for scope_key in ("country", "device"):
                values = [page.scope.get(scope_key) for page in pages]
                aggregate_scope[scope_key] = values[0] if values and len(set(values)) == 1 else None
            verifications = [page.scope.get("scope_verification", "unverified") for page in pages]
            aggregate_scope["scope_verification"] = (
                verifications[0] if verifications and len(set(verifications)) == 1 else "mixed"
            )
            aggregate_scope["response_scope_status"] = (
                "declared" if pages and all(page.scope.get("response_scope_status") == "declared" for page in pages)
                else "unverified"
            )
            if aggregate_scope["scope_verification"] != "matched" and aggregate_status == "complete":
                aggregate_status = "partial"
        page_filters = [
            page.scope.get("filter") or page.scope.get("steam_filter")
            for page in pages
        ]
        if page_filters and all(isinstance(value, str) and value for value in page_filters) and len(set(page_filters)) == 1:
            aggregate_scope["filter"] = page_filters[0]
            aggregate_scope["steam_filter"] = page_filters[0]
            aggregate_scope["filter_source"] = "request_query_parameter"
        page_fetches = [
            {
                "page_index": index,
                "cursor": page.cursor,
                "next_cursor": page.next_cursor,
                "status": page.status,
                "fetched_at": page.fetched_at,
                "url": page.scope.get("url"),
                "sort_id": page.scope.get("sort_id"),
                "list_type": page.scope.get("list_type"),
                "country": page.scope.get("country"),
                "device": page.scope.get("device"),
                "requested_country": page.scope.get("requested_country"),
                "requested_device": page.scope.get("requested_device"),
                "response_scope_status": page.scope.get("response_scope_status"),
                "scope_verification": page.scope.get("scope_verification"),
                "coverage": page.coverage,
                "filter": page.scope.get("filter") or page.scope.get("steam_filter"),
                "filter_source": page.scope.get("filter_source") or (
                    "request_query_parameter"
                    if page.scope.get("filter") or page.scope.get("steam_filter")
                    else None
                ),
                "raw_rows": page.coverage.get("raw_rows") if isinstance(page.coverage, dict) else None,
                "parsed_items": page.coverage.get("parsed_items", len(page.items)) if isinstance(page.coverage, dict) else len(page.items),
            }
            for index, page in enumerate(pages)
        ]
        aggregate_coverage = {
            "pages_fetched": len(pages),
            "page_starts": page_starts,
            "page_size": page_size_used,
            "total_results": total_results,
            "raw_items": len(all_items),
            "raw_rows_seen": raw_rows_seen,
            "unique_platform_ids": unique_platform_ids,
            "pagination_mode": aggregate_scope.get("pagination_mode"),
            "duplicate_platform_ids_across_pages": duplicate_ids_across_pages,
            "all_pages_complete": all_pages_complete,
            "pagination_complete": pagination_complete,
            "stop_reason": stop_reason,
            "page_fetches": page_fetches,
        }
        aggregate = SourceResult(
            source_id=source,
            status=aggregate_status,
            fetched_at=pages[0].fetched_at if pages else datetime.now(timezone.utc).isoformat(),
            scope=aggregate_scope,
            items=all_items,
            cursor="0",
            next_cursor=aggregate_next_cursor,
            coverage=aggregate_coverage,
            evidence_refs=all_evidence_refs,
            errors=all_errors,
        ).validate()
        source_results.append(aggregate)
        source_summary.append({
            "source": source,
            "source_plan_index": source_index,
            "filter": aggregate_scope.get("filter"),
            "steam_filter": aggregate_scope.get("steam_filter"),
            "filter_source": aggregate_scope.get("filter_source"),
            "list_type": aggregate_scope.get("list_type"),
            "sort_id": aggregate_scope.get("sort_id"),
            "country": aggregate_scope.get("country"),
            "device": aggregate_scope.get("device"),
            "requested_country": aggregate_scope.get("requested_country"),
            "requested_device": aggregate_scope.get("requested_device"),
            "response_scope_status": aggregate_scope.get("response_scope_status"),
            "scope_verification": aggregate_scope.get("scope_verification"),
            "pagination_mode": aggregate_scope.get("pagination_mode"),
            "status": aggregate.status,
            "pages": len(pages),
            "items": len(all_items),
            "unique_platform_ids": unique_platform_ids,
            "duplicate_platform_ids_across_pages": duplicate_ids_across_pages,
            "total_results": total_results,
            "next_cursor": aggregate_next_cursor,
            "pagination_complete": pagination_complete,
            "stop_reason": stop_reason,
            "page_fetches": page_fetches,
            "errors": all_errors,
            "evidence_refs": all_evidence_refs,
        })
        if abort_remaining_sources:
            break

    collected_at = datetime.now(timezone.utc).isoformat()
    snapshot = merge_source_results(
        source_results, run_id=args.run_id, run_date=args.date, slot=args.slot,
        timezone=args.timezone, started_at=args.started_at, collected_at=collected_at,
        cutoff_at=collected_at, code_version="0.1.0",
        normalization_version="candidate-normalizer-v1",
        source_policy_version="source-plan-v1",
    )
    candidate_path = root / "runs" / run_key / "candidate_keywords.json"
    atomic_write_json(candidate_path, snapshot, root=root)
    return {
        "status": snapshot["collection_status"],
        "run_id": args.run_id,
        "candidate_count": len(snapshot["candidates"]),
        "unparsed_count": snapshot["counts"]["unparsed_records"],
        "source_summary": source_summary,
        "candidate_path": str(candidate_path),
        "source_fetch_calls": sum(item["pages"] for item in source_summary),
        "note": "partial coverage is retained honestly; no KD, trend decision, API injection, or build dispatch occurs",
    }

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            validate_file(args.kind, args.input)
            _print({"status": "valid", "kind": args.kind, "input": str(Path(args.input).absolute())})
            return 0
        if args.command == "snapshot-api":
            result = read_archived_api_snapshot(args.input, acquired_at=args.acquired_at, output_root=args.output_root)
            _print({
                "status": result["evaluation_status"], "snapshot_id": result["snapshot_id"],
                "record_count": len(result["normalized_records"]), "output_path": result["output_path"],
                "network_requests": 0,
            })
            return 0
        if args.command == "snapshot-api-ingest":
            result = read_api_ingest_morning_batch(
                args.ingest_root, batch_date=args.date, output_root=args.output_root,
            )
            snapshot_path = result.get("output_path")
            _print({
                "status": result["evaluation_status"] if "evaluation_status" in result else result["status"],
                "batch_date": args.date,
                "selected_run_id": result.get("local_fetch_run_id"),
                "snapshot_id": result.get("snapshot_id"),
                "record_count": len(result.get("normalized_records", [])),
                "completeness": result.get("completeness"),
                "batch_alignment_status": result.get("batch_alignment_status"),
                "snapshot_path": snapshot_path,
                "manifest_path": result.get("manifest_path"),
                "read_report_path": result.get("read_report_path"),
                "attempts": result.get("attempts", []),
                "network_requests": 0,
            })
            return 0
        if args.command == "record-first-seen":
            snapshot = load_json(args.input)
            if not isinstance(snapshot, dict):
                raise ContractError("candidate snapshot must be a JSON object")
            result = EntityFirstSeenLedger(args.output_root).record_snapshot(snapshot)
            _print(result)
            return 0
        if args.command == "fetch-source":
            result = _fetch_source(args)
            _print(result)
            return 0 if result["status"] in {"complete", "partial"} else 2
        if args.command == "collect":
            result = _collect(args)
            _print(result)
            return 0 if result["status"] in {"complete", "partial"} else 2
        if args.command == "compare":
            benchmark = load_json(args.benchmark)
            snapshots = [load_json(path) for path in args.self_snapshot]
            result = compare_snapshots(
                benchmark, snapshots, cutoff=args.cutoff,
                benchmark_enabled=not args.benchmark_disabled,
            )
            _print(result)
            return 0 if result["status"] in {"ready", "disabled", "benchmark_not_ready"} else 2
        if args.command == "evaluate-rules":
            observations = load_json(args.input)
            if not isinstance(observations, list):
                raise ContractError("evaluation input must be a JSON array")
            _print(evaluate_feature_groups(observations, minimum_samples=args.minimum_samples))
            return 0
        if args.command == "replay-rules":
            candidates = load_json(args.candidates)
            baseline = load_json(args.baseline_rules)
            proposed = load_json(args.proposed_rules)
            outcomes = load_json(args.outcomes)
            if not isinstance(candidates, list) or not isinstance(outcomes, list):
                raise ContractError("candidates and outcomes must be JSON arrays")
            if not isinstance(baseline, dict) or not isinstance(proposed, dict):
                raise ContractError("baseline and proposed rules must be JSON objects")
            _print(replay_rules(candidates, baseline, proposed, outcomes))
            return 0
        raise AssertionError("unreachable command")
    except (ContractError, StorageError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
