"""Safe file helpers for isolated local artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    pass


def reject_symlink_components(path: Path) -> None:
    """Reject symlinks in existing path components to avoid escaping the namespace."""
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise StorageError(f"symlink path component is not allowed: {current}")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_ref(path: str | Path, *, root: str | Path) -> dict[str, str]:
    target = Path(path).absolute()
    base = Path(root).absolute()
    reject_symlink_components(target)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise StorageError("evidence path is outside the configured root") from exc
    if not target.is_file():
        raise StorageError("evidence target must be an existing regular file")
    return {"path": str(target), "sha256": sha256_file(target)}


def _atomic_write_bytes(target: Path, payload: bytes, base: Path) -> None:
    if target == base:
        raise StorageError("target must be a file below the configured root")
    reject_symlink_components(base)
    reject_symlink_components(target)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise StorageError("write target is outside the configured root") from exc
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    reject_symlink_components(target.parent)
    fd, temp_name = tempfile.mkstemp(prefix=".trendgpt-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: str | Path, value: Any, *, root: str | Path) -> None:
    """Atomically write strict JSON only inside an explicit, isolated root."""
    target = Path(path).absolute()
    base = Path(root).absolute()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _atomic_write_bytes(target, payload, base)


def store_text_evidence(text: str, *, output_root: str | Path, relative_path: str, media_type: str) -> dict[str, Any]:
    """Persist raw source text under a self-v1 root and return a hash-bound reference."""
    root = Path(output_root).absolute()
    if root.name != "self-v1":
        raise StorageError("evidence root must end in self-v1")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageError("evidence path must be a safe relative path")
    target = root / relative
    _atomic_write_bytes(target, text.encode("utf-8"), root)
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "media_type": media_type,
        "bytes": target.stat().st_size,
    }
