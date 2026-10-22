"""Command-line interface for local validation and explicit source collection."""
from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from .benchmark import compare_snapshots
from .benchmark_snapshot import read_archived_api_snapshot
from .contracts import ContractError, validate_file, load_json
from .rules import evaluate_feature_groups
from .sources import SourceRequest
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

    compare = sub.add_parser("compare", help="compare an API benchmark to self-discovery snapshots")
    compare.add_argument("--benchmark", required=True)
    compare.add_argument("--self-snapshot", action="append", default=[])
    compare.add_argument("--cutoff", required=True, help="RFC3339 timestamp with timezone")
    compare.add_argument("--benchmark-disabled", action="store_true")

    evaluate = sub.add_parser("evaluate-rules", help="summarize mature revenue by feature group; never changes rules")
    evaluate.add_argument("--input", required=True, help="JSON array of observation records")
    evaluate.add_argument("--minimum-samples", type=int, default=5)
    return parser


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
    if args.source == "steam":
        from .adapters.steam import SteamSearchAdapter
        adapter = SteamSearchAdapter()
    elif args.source == "roblox":
        from .adapters.roblox import RobloxChartAdapter
        adapter = RobloxChartAdapter()
    else:
        from .adapters.youtube_rss import YouTubeRssAdapter
        adapter = YouTubeRssAdapter()
    request = SourceRequest(
        run_id=args.run_id, source_id=args.source, fetched_at=args.fetched_at,
        scope=scope, evidence_root=str(root), cursor=args.cursor, page_limit=args.page_limit,
    )
    result = adapter.fetch(request).validate()
    run_key = sha256(args.run_id.encode("utf-8")).hexdigest()[:16]
    cursor_key = args.cursor or "first"
    output_path = root / "runs" / run_key / f"{args.source}-{cursor_key}.json"
    atomic_write_json(output_path, result.to_dict(), root=root)
    return {
        "status": result.status, "source_id": result.source_id,
        "items": len(result.items), "next_cursor": result.next_cursor,
        "evidence_refs": result.evidence_refs, "errors": result.errors,
        "output_path": str(output_path), "network_requests": 1,
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
        raise AssertionError("unreachable command")
    except (ContractError, StorageError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
