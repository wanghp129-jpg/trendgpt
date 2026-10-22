"""CLI for recording reviewed self-discovery timing against a local API observation."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from .benchmark import adjudicate_independence
from .contracts import ContractError, load_json
from .storage import StorageError, atomic_write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendgpt-adjudicate")
    parser.add_argument("--candidate-snapshot", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--api-observed-at", required=True)
    parser.add_argument("--evidence-ref-json", required=True)
    parser.add_argument("--adjudicated-by", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output-relative", required=True)
    args = parser.parse_args(argv)

    try:
        root = Path(args.output_root).absolute()
        if root.name != "self-v1":
            raise ContractError("output root must end in self-v1")
        relative = Path(args.output_relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError("output-relative must be a safe relative path")
        snapshot = load_json(args.candidate_snapshot)
        evidence = load_json(args.evidence_ref_json)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("candidates"), list):
            raise ContractError("candidate snapshot must contain a candidates array")
        if not isinstance(evidence, dict):
            raise ContractError("evidence reference must be a JSON object")
        matches = [
            i for i, item in enumerate(snapshot["candidates"])
            if isinstance(item, dict) and item.get("candidate_id") == args.candidate_id
        ]
        if len(matches) != 1:
            raise ContractError("candidate-id must match exactly one candidate")
        updated = deepcopy(snapshot)
        index = matches[0]
        updated["candidates"][index] = adjudicate_independence(
            updated["candidates"][index],
            first_api_observed_at=args.api_observed_at,
            evidence_ref=evidence,
            adjudicated_by=args.adjudicated_by,
        )
        updated.setdefault("adjudication_history", []).append({
            "candidate_id": args.candidate_id,
            "adjudicated_by": args.adjudicated_by,
            "api_observed_at": args.api_observed_at,
            "note": "relative to locally observed API snapshot; not provider generation time",
        })
        output_path = root / relative
        atomic_write_json(output_path, updated, root=root)
        print(json.dumps({
            "status": "recorded", "candidate_id": args.candidate_id,
            "independent_eligibility": updated["candidates"][index]["independent_eligibility"],
            "output_path": str(output_path), "input_overwritten": False,
        }, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, StorageError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
