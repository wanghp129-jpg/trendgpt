"""Command-line interface for local validation and offline evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .benchmark import compare_snapshots
from .contracts import ContractError, validate_file, load_json
from .rules import evaluate_feature_groups


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trendgpt", description="Isolated Lesson 14 discovery tools")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate one self-v1 JSON artifact")
    validate.add_argument("--kind", choices=("candidate", "verified", "benchmark", "run-result", "state"), required=True)
    validate.add_argument("--input", required=True)

    compare = sub.add_parser("compare", help="compare an API benchmark to self-discovery snapshots")
    compare.add_argument("--benchmark", required=True)
    compare.add_argument("--self-snapshot", action="append", default=[])
    compare.add_argument("--cutoff", required=True, help="RFC3339 timestamp with timezone")
    compare.add_argument("--benchmark-disabled", action="store_true")

    evaluate = sub.add_parser("evaluate-rules", help="summarize mature revenue by feature group; never changes rules")
    evaluate.add_argument("--input", required=True, help="JSON array of observation records")
    evaluate.add_argument("--minimum-samples", type=int, default=5)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            artifact = validate_file(args.kind, args.input)
            _print({"status": "valid", "kind": args.kind, "input": str(Path(args.input).absolute())})
            return 0
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
    except (ContractError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
