"""CLI for the durable ChatGPT task queue and shared browser lease."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .browser_registry import load_browser_registry
from .chatgpt_coordination import ChatGPTLease, ChatGPTLockTimeout
from .chatgpt_queue import ChatGPTTaskQueue
from .contracts import ContractError, load_json
from .storage import StorageError, evidence_ref, reject_symlink_components


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trendgpt-queue")
    sub = parser.add_subparsers(dest="command", required=True)

    registry = sub.add_parser("validate-browser-registry")
    registry.add_argument("--input", required=True)

    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--output-root", required=True)
    enqueue.add_argument("--task-type", required=True)
    enqueue.add_argument("--input-file", required=True)
    enqueue.add_argument("--output-relative", required=True)
    enqueue.add_argument("--idempotency-key", required=True)
    enqueue.add_argument("--instance-role", default="trends_keyword_cleaning")
    enqueue.add_argument("--max-attempts", type=int, default=2)
    enqueue.add_argument("--created-at")

    listing = sub.add_parser("list")
    listing.add_argument("--output-root", required=True)

    claim = sub.add_parser("claim")
    claim.add_argument("--output-root", required=True)
    claim.add_argument("--owner", required=True)
    claim.add_argument("--claimed-at")

    complete = sub.add_parser("complete")
    complete.add_argument("--output-root", required=True)
    complete.add_argument("--task-id", required=True)
    complete.add_argument("--lease-token", required=True)
    complete.add_argument("--output-file", required=True)
    complete.add_argument("--completed-at")

    fail = sub.add_parser("fail")
    fail.add_argument("--output-root", required=True)
    fail.add_argument("--task-id", required=True)
    fail.add_argument("--lease-token", required=True)
    fail.add_argument("--disposition", choices=("safe_retry", "needs_review", "permanent"), required=True)
    fail.add_argument("--error-code", required=True)
    fail.add_argument("--failed-at")

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--output-root", required=True)
    reconcile.add_argument("--now")
    reconcile.add_argument("--max-age-seconds", type=int, default=1800)

    run_next = sub.add_parser("run-next", help="run one queued task under the global ChatGPT lock")
    run_next.add_argument("--output-root", required=True)
    run_next.add_argument("--lock-path", required=True)
    run_next.add_argument("--owner", required=True)
    run_next.add_argument("--timeout-seconds", type=float, default=900)
    run_next.add_argument("worker_command", nargs=argparse.REMAINDER,
                          help="worker command after --; it receives task data via TRENDGPT_TASK_* environment variables")
    return parser


def _queue(root: str) -> ChatGPTTaskQueue:
    return ChatGPTTaskQueue(root)


def _run_next(args: argparse.Namespace) -> int:
    command = list(args.worker_command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ContractError("provide a worker command after --")
    queue = _queue(args.output_root)
    # Hold the same cross-process lock used by code_before for the entire browser interaction.
    with ChatGPTLease(
        args.lock_path, owner=args.owner, task_id="trendgpt-queue-worker",
        timeout_seconds=args.timeout_seconds,
    ):
        claimed = queue.claim_next(owner=args.owner)
        if claimed is None:
            _print({"status": "idle", "reason": "no_queued_task_or_another_task_is_running"})
            return 0
        task = claimed["task"]
        root = Path(args.output_root).absolute()
        output_path = root / task["output_relative"]
        reject_symlink_components(output_path)
        env = os.environ.copy()
        env.update({
            "TRENDGPT_TASK_JSON": json.dumps(task, ensure_ascii=False),
            "TRENDGPT_TASK_ID": task["task_id"],
            "TRENDGPT_TASK_TYPE": task["task_type"],
            "TRENDGPT_INPUT_PATH": task["input_ref"]["path"],
            "TRENDGPT_OUTPUT_PATH": str(output_path),
            "TRENDGPT_INSTANCE_ROLE": task["instance_role"],
            "TRENDGPT_ATTEMPT": str(task["attempts"]),
        })
        completed = subprocess.run(command, env=env, check=False)
        if completed.returncode != 0:
            result = queue.fail(
                task_id=task["task_id"], lease_token=task["lease"]["token"],
                disposition="needs_review", error_code=f"worker_exit_{completed.returncode}",
            )
            _print({"status": result["status"], "task_id": task["task_id"],
                    "worker_exit_code": completed.returncode,
                    "note": "submission may be uncertain; task was not automatically retried"})
            return completed.returncode or 2
        try:
            # Output must be a valid JSON artifact and its hash is recorded after the worker exits.
            load_json(output_path)
            output_ref = evidence_ref(output_path, root=root)
        except (ContractError, OSError, StorageError) as exc:
            result = queue.fail(
                task_id=task["task_id"], lease_token=task["lease"]["token"],
                disposition="needs_review", error_code="worker_output_missing_or_invalid",
            )
            _print({"status": result["status"], "task_id": task["task_id"],
                    "error": str(exc), "note": "task was not automatically retried"})
            return 2
        result = queue.complete(
            task_id=task["task_id"], lease_token=task["lease"]["token"],
            result_ref=output_ref,
        )
        _print({"status": result["status"], "task_id": task["task_id"],
                "output_ref": output_ref, "worker_exit_code": completed.returncode})
        return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-browser-registry":
            registry = load_browser_registry(args.input)
            _print({
                "status": "valid",
                "instances": len(registry["instances"]),
                "planned": [item["port"] for item in registry["instances"] if item["status"] == "planned_not_configured"],
                "note": "validation does not check whether any Chrome instance is running",
            })
            return 0
        if args.command == "enqueue":
            source = Path(args.input_file).absolute()
            result = _queue(args.output_root).enqueue(
                task_type=args.task_type,
                input_ref=evidence_ref(source, root=source.parent),
                output_relative=args.output_relative,
                idempotency_key=args.idempotency_key,
                instance_role=args.instance_role,
                max_attempts=args.max_attempts,
                created_at=args.created_at,
            )
            _print(result)
            return 0
        if args.command == "list":
            _print(_queue(args.output_root).list_tasks())
            return 0
        if args.command == "claim":
            _print(_queue(args.output_root).claim_next(owner=args.owner, claimed_at=args.claimed_at) or {"status": "idle"})
            return 0
        if args.command == "complete":
            output = Path(args.output_file).absolute()
            output_root = Path(args.output_root).absolute()
            ref = evidence_ref(output, root=output_root)
            _print(_queue(args.output_root).complete(
                task_id=args.task_id, lease_token=args.lease_token,
                result_ref=ref, completed_at=args.completed_at,
            ))
            return 0
        if args.command == "fail":
            _print(_queue(args.output_root).fail(
                task_id=args.task_id, lease_token=args.lease_token,
                disposition=args.disposition, error_code=args.error_code, failed_at=args.failed_at,
            ))
            return 0
        if args.command == "reconcile":
            _print(_queue(args.output_root).reconcile_stale_running(
                now=args.now, max_age_seconds=args.max_age_seconds,
            ))
            return 0
        if args.command == "run-next":
            return _run_next(args)
        raise AssertionError("unreachable command")
    except (ContractError, StorageError, ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except ChatGPTLockTimeout as exc:
        print(json.dumps({"status": "lock_timeout", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
