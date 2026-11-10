"""Cross-process advisory lock for every ChatGPT browser caller.

All cooperating programs must use the same lock file path. This does not affect a
caller that ignores the lock; code_before must explicitly wrap its ChatGPT actions.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import StorageError, reject_symlink_components


class ChatGPTLockTimeout(TimeoutError):
    pass


class ChatGPTLease:
    """Hold an OS flock over the entire ChatGPT browser interaction."""

    def __init__(
        self,
        lock_path: str | Path,
        *,
        owner: str,
        task_id: str,
        timeout_seconds: float = 900,
        poll_interval: float = 0.25,
    ):
        raw_path = Path(lock_path)
        if not raw_path.is_absolute():
            raise ValueError("lock_path must be an absolute file path")
        self.path = raw_path.absolute()
        self.owner = owner.strip()
        self.task_id = task_id.strip()
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._fd: int | None = None
        if not self.owner or not self.task_id:
            raise ValueError("owner and task_id are required")
        if timeout_seconds < 0 or poll_interval <= 0:
            raise ValueError("timeout must be non-negative and poll_interval positive")
        if not self.path.is_absolute() or self.path.name in {"", ".", ".."}:
            raise ValueError("lock_path must be an absolute file path")

    def acquire(self) -> "ChatGPTLease":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        reject_symlink_components(self.path.parent)
        reject_symlink_components(self.path)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        started = time.monotonic()
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started >= self.timeout_seconds:
                        raise ChatGPTLockTimeout(f"timed out waiting for shared ChatGPT lock: {self.path}")
                    time.sleep(min(self.poll_interval, max(0.01, self.timeout_seconds - (time.monotonic() - started))))
            metadata = {
                "schema": "trendgpt-chatgpt-lease-v1",
                "owner": self.owner,
                "task_id": self.task_id,
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "state": "held",
            }
            payload = (json.dumps(metadata, ensure_ascii=False) + "\n").encode("utf-8")
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload)
            os.fsync(fd)
            self._fd = fd
            return self
        except Exception:
            os.close(fd)
            raise

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            metadata: dict[str, Any] = {
                "schema": "trendgpt-chatgpt-lease-v1",
                "owner": self.owner,
                "task_id": self.task_id,
                "pid": os.getpid(),
                "released_at": datetime.now(timezone.utc).isoformat(),
                "state": "released",
            }
            payload = (json.dumps(metadata, ensure_ascii=False) + "\n").encode("utf-8")
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def __enter__(self) -> "ChatGPTLease":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
