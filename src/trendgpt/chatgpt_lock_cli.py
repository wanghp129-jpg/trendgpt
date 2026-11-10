"""Run an existing command while holding the shared ChatGPT lock."""
from __future__ import annotations

import argparse
import subprocess
import sys

from .chatgpt_coordination import ChatGPTLease, ChatGPTLockTimeout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trendgpt-chatgpt-lease",
        description="Run one command while holding the shared ChatGPT browser lock",
    )
    parser.add_argument("--lock-path", required=True, help="the exact same absolute lock path used by every ChatGPT caller")
    parser.add_argument("--owner", required=True, help="e.g. trendgpt-cleaner or code_before")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run after --")
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    try:
        with ChatGPTLease(
            args.lock_path, owner=args.owner, task_id=args.task_id,
            timeout_seconds=args.timeout_seconds,
        ):
            completed = subprocess.run(command, check=False)
            return completed.returncode
    except ChatGPTLockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 75
    except (OSError, ValueError) as exc:
        print(f"chatgpt lease error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
