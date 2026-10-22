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
from .rule_replay import replay_rules
from .rules import evaluate_feature_groups
from .sources import SourceRequest, merge_source_results
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
        from .adapters.youtube_rss import YouTubeRssAdapter
        return YouTubeRssAdapter()
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
    source_results = []
    source_summary = []

    for source_index, spec in enumerate(plan["sources"]):
        if not isinstance(spec, dict) or spec.get("source") not in {"steam", "roblox", "youtube"}:
            raise ContractError(f"source plan entry {source_index} has an invalid source")
        source = spec["source"]
        scope = spec.get("scope")
        if not isinstance(scope, dict):
            raise ContractError(f"source plan entry {source_index} requires a scope object")
        page_limit = int(spec.get("page_limit", 50))
        configured_max = int(spec.get("max_pages", args.max_pages_per_source))
        max_pages = min(configured_max, args.max_pages_per_source)
        if page_limit < 1 or page_limit > 50 or max_pages < 1:
            raise ContractError(f"source plan entry {source_index} has invalid page limits")
        cursor = None
        pages = []
        adapter = _make_adapter(source)
        for _page_number in range(max_pages):
            request = SourceRequest(
                run_id=f"{args.run_id}-{source_index}", source_id=source,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                scope={**scope, "source_plan_index": source_index},
                evidence_root=str(root), cursor=cursor, page_limit=page_limit,
            )
            result = adapter.fetch(request).validate()
            pages.append(result)
            source_results.append(result)
            page_name = cursor or "first"
            page_path = root / "runs" / run_key / f"{source}-{source_index}-page-{page_name}.json"
            atomic_write_json(page_path, result.to_dict(), root=root)
            if result.status in {"failed", "blocked"} or not result.next_cursor:
                break
            cursor = result.next_cursor
        source_summary.append({
            "source": source, "source_plan_index": source_index,
            "pages": len(pages), "statuses": [page.status for page in pages],
            "items": sum(len(page.items) for page in pages),
            "last_cursor": pages[-1].cursor if pages else None,
            "next_cursor": pages[-1].next_cursor if pages else None,
        })

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
        "status": snapshot["collection_status"], "run_id": args.run_id,
        "candidate_count": len(snapshot["candidates"]),
        "unparsed_count": snapshot["counts"]["unparsed_records"],
        "source_summary": source_summary, "candidate_path": str(candidate_path),
        "source_fetch_calls": sum(len(item["statuses"]) for item in source_summary),
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
