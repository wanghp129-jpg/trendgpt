"""Durable serialized ChatGPT task queue under the isolated self-v1 namespace."""
from __future__ import annotations

import fcntl
import hashlib
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .contracts import ContractError, load_json
from .storage import StorageError, atomic_write_json, reject_symlink_components, sha256_file

TASK_TYPES = {
    "keyword_cleaning", "basic_info", "homepage_info", "clarity",
    "candidate_review", "other_chatgpt_task",
}
TASK_STATES = {"queued", "running", "completed", "failed", "needs_review"}


class QueueConflict(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _safe_relative(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _verify_ref(ref: Any, *, require_file: bool = True) -> bool:
    if not isinstance(ref, dict):
        return False
    path, digest = ref.get("path"), ref.get("sha256")
    if not isinstance(path, str) or not Path(path).is_absolute():
        return False
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        return False
    return sha256_file(target) == digest


class ChatGPTTaskQueue:
    """A durable queue; only one task can be marked running at a time.

    The queue coordinates callers that use it. For cross-system exclusion, code_before
    and every other ChatGPT browser caller must additionally use the same ChatGPTLease.
    """

    def __init__(self, output_root: str | Path):
        root = Path(output_root).absolute()
        if root.name != "self-v1":
            raise StorageError("ChatGPT queue root must end in self-v1")
        reject_symlink_components(root)
        self.root = root
        self.directory = root / "chatgpt-queue"
        self.state_path = self.directory / "queue.json"
        self.lock_path = self.directory / "queue.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        reject_symlink_components(self.lock_path)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema": "trendgpt-chatgpt-queue-v1",
                "revision": 0,
                "tasks": [],
            }
        state = load_json(self.state_path)
        if not isinstance(state, dict) or state.get("schema") != "trendgpt-chatgpt-queue-v1":
            raise ContractError("invalid ChatGPT queue state schema")
        if not isinstance(state.get("revision"), int) or not isinstance(state.get("tasks"), list):
            raise ContractError("invalid ChatGPT queue state fields")
        for index, task in enumerate(state["tasks"]):
            if not isinstance(task, dict) or task.get("status") not in TASK_STATES:
                raise ContractError(f"invalid task at queue index {index}")
        return state

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        state["revision"] += 1
        atomic_write_json(self.state_path, state, root=self.root)

    def enqueue(
        self,
        *,
        task_type: str,
        input_ref: dict[str, Any],
        output_relative: str,
        idempotency_key: str,
        instance_role: str = "trends_keyword_cleaning",
        max_attempts: int = 2,
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {task_type}")
        if not _verify_ref(input_ref):
            raise ValueError("input_ref must point to an existing file with a matching SHA-256 digest")
        if not _safe_relative(output_relative):
            raise ValueError("output_relative must be a safe relative path")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not isinstance(instance_role, str) or not instance_role.strip():
            raise ValueError("instance_role is required")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        created_at = created_at or _utc_now()
        _parse_time(created_at)
        task_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
        with self._locked():
            state = self._load_unlocked()
            for existing in state["tasks"]:
                if existing.get("idempotency_key") == idempotency_key:
                    if existing.get("input_ref") == input_ref and existing.get("task_type") == task_type:
                        return {"status": "reused", "task": existing, "revision": state["revision"]}
                    raise QueueConflict("idempotency key already exists with different task input")
            task = {
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "task_type": task_type,
                "input_ref": input_ref,
                "output_relative": output_relative,
                "instance_role": instance_role,
                "status": "queued",
                "created_at": created_at,
                "attempts": 0,
                "max_attempts": max_attempts,
                "lease": None,
                "result_ref": None,
                "failure": None,
                "metadata": metadata or {},
            }
            state["tasks"].append(task)
            self._save_unlocked(state)
            return {"status": "queued", "task": task, "revision": state["revision"]}

    def list_tasks(self) -> dict[str, Any]:
        with self._locked():
            state = self._load_unlocked()
            return {"revision": state["revision"], "tasks": state["tasks"]}

    def claim_next(self, *, owner: str, claimed_at: str | None = None) -> dict[str, Any] | None:
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner is required")
        claimed_at = claimed_at or _utc_now()
        _parse_time(claimed_at)
        with self._locked():
            state = self._load_unlocked()
            if any(task["status"] == "running" for task in state["tasks"]):
                return None
            task = next((item for item in state["tasks"] if item["status"] == "queued"), None)
            if task is None:
                return None
            if task["attempts"] >= task["max_attempts"]:
                task["status"] = "needs_review"
                task["failure"] = {"code": "attempt_limit_reached", "retryable": False}
                self._save_unlocked(state)
                return None
            task["status"] = "running"
            task["attempts"] += 1
            task["lease"] = {
                "token": secrets.token_hex(24),
                "owner": owner,
                "claimed_at": claimed_at,
            }
            self._save_unlocked(state)
            return {"task": task, "revision": state["revision"]}

    def _find_lease(self, state: dict[str, Any], task_id: str, lease_token: str) -> dict[str, Any]:
        matches = [item for item in state["tasks"] if item.get("task_id") == task_id]
        if len(matches) != 1:
            raise QueueConflict("task_id must match exactly one task")
        task = matches[0]
        lease = task.get("lease")
        if task.get("status") != "running" or not isinstance(lease, dict) or lease.get("token") != lease_token:
            raise QueueConflict("task is not running under the supplied lease token")
        return task

    def complete(
        self,
        *,
        task_id: str,
        lease_token: str,
        result_ref: dict[str, Any],
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        if not _verify_ref(result_ref):
            raise ValueError("result_ref must point to an existing file with a matching SHA-256 digest")
        completed_at = completed_at or _utc_now()
        _parse_time(completed_at)
        with self._locked():
            state = self._load_unlocked()
            task = self._find_lease(state, task_id, lease_token)
            task.update({
                "status": "completed",
                "completed_at": completed_at,
                "result_ref": result_ref,
                "lease": None,
                "failure": None,
            })
            self._save_unlocked(state)
            return {"status": "completed", "task": task, "revision": state["revision"]}

    def fail(
        self,
        *,
        task_id: str,
        lease_token: str,
        disposition: str,
        error_code: str,
        failed_at: str | None = None,
    ) -> dict[str, Any]:
        """Retry only an explicitly safe pre-submit failure; uncertain submissions go to review."""
        if disposition not in {"safe_retry", "needs_review", "permanent"}:
            raise ValueError("disposition must be safe_retry, needs_review, or permanent")
        if not isinstance(error_code, str) or not error_code.strip():
            raise ValueError("error_code is required")
        failed_at = failed_at or _utc_now()
        _parse_time(failed_at)
        with self._locked():
            state = self._load_unlocked()
            task = self._find_lease(state, task_id, lease_token)
            if disposition == "safe_retry" and task["attempts"] < task["max_attempts"]:
                status = "queued"
            elif disposition == "safe_retry":
                status = "needs_review"
            elif disposition == "needs_review":
                status = "needs_review"
            else:
                status = "failed"
            task.update({
                "status": status,
                "failed_at": failed_at,
                "failure": {
                    "code": error_code,
                    "disposition": disposition,
                    "retryable": status == "queued",
                },
                "lease": None,
            })
            self._save_unlocked(state)
            return {"status": status, "task": task, "revision": state["revision"]}

    def reconcile_stale_running(
        self,
        *,
        now: str | None = None,
        max_age_seconds: int = 1800,
    ) -> dict[str, Any]:
        """Move stale running tasks to needs_review; never resubmit an uncertain prompt."""
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds < 1:
            raise ValueError("max_age_seconds must be a positive integer")
        now = now or _utc_now()
        now_dt = _parse_time(now)
        moved = []
        with self._locked():
            state = self._load_unlocked()
            for task in state["tasks"]:
                lease = task.get("lease")
                if task["status"] != "running" or not isinstance(lease, dict):
                    continue
                try:
                    age = (now_dt - _parse_time(lease["claimed_at"])).total_seconds()
                except (KeyError, ValueError, TypeError):
                    age = max_age_seconds + 1
                if age > max_age_seconds:
                    task["status"] = "needs_review"
                    task["failure"] = {
                        "code": "stale_running_lease",
                        "disposition": "needs_review",
                        "retryable": False,
                        "note": "submission/result may be uncertain; reconcile before retry",
                    }
                    task["lease"] = None
                    moved.append(task["task_id"])
            if moved:
                self._save_unlocked(state)
            return {"moved_to_review": moved, "revision": state["revision"]}
