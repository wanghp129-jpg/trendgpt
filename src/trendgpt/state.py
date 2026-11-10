"""Versioned multi-run state isolated from the existing API production state."""
from __future__ import annotations

import fcntl
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import ContractError, validate_state
from .storage import StorageError, atomic_write_json, reject_symlink_components


class StateConflict(RuntimeError):
    pass


class SelfStateStore:
    """Minimal state store; caller must explicitly provide a self-v1 root."""

    def __init__(self, output_root: str | Path):
        root = Path(output_root).absolute()
        if root.name != "self-v1":
            raise StorageError("output root must end in self-v1; refusing shared production state")
        reject_symlink_components(root)
        self.root = root

    def state_path(self, run_date: str) -> Path:
        date.fromisoformat(run_date)
        return self.root / run_date / "state.json"

    def read(self, run_date: str, timezone: str) -> dict[str, Any]:
        path = self.state_path(run_date)
        if not path.exists():
            return {
                "date": run_date, "timezone": timezone, "revision": 0,
                "seen_keywords": [], "runs": {},
                "extensions": {"self_v1": {"entity_index": {}, "review_queue": [], "dispatch_intents": []}},
            }
        from .contracts import load_json
        return validate_state(load_json(path))

    def record_run(
        self,
        *,
        run_date: str,
        timezone: str,
        slot: str,
        run_id: str,
        input_sha256: str,
        result_ref: dict[str, Any],
        status: str,
        seen_keywords: list[str] | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Record one run under flock; same slot/input is idempotent, conflicts never overwrite."""
        if status not in {"running", "completed", "partial", "failed", "needs_review"}:
            raise ContractError("invalid run status")
        if len(input_sha256) != 64 or any(c not in "0123456789abcdef" for c in input_sha256):
            raise ContractError("input_sha256 must be a lowercase SHA-256 digest")
        if not slot or not run_id:
            raise ContractError("slot and run_id are required")
        path = self.state_path(run_date)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = path.with_suffix(".lock")
        reject_symlink_components(lock_path)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self.read(run_date, timezone)
            if expected_revision is not None and state["revision"] != expected_revision:
                raise StateConflict(f"revision changed: expected {expected_revision}, actual {state['revision']}")
            existing = state["runs"].get(slot)
            if existing:
                if existing.get("input_sha256") == input_sha256 and existing.get("run_id") == run_id:
                    return {"status": "reused", "state": state, "run": existing}
                raise StateConflict(f"slot {slot!r} already has a different input/run; refusing overwrite")
            run = {
                "run_id": run_id, "input_sha256": input_sha256,
                "result_ref": result_ref, "status": status,
            }
            state["runs"][slot] = run
            if seen_keywords:
                known = set(state["seen_keywords"])
                state["seen_keywords"].extend(word for word in seen_keywords if word not in known and not known.add(word))
            state["revision"] += 1
            state.setdefault("extensions", {}).setdefault("self_v1", {})
            validate_state(state)
            atomic_write_json(path, state, root=self.root)
            return {"status": "recorded", "state": state, "run": run}
