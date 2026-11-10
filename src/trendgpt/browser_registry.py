"""Validation helpers for browser instance configuration; no browser is started here."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json

ALLOWED_STATUS = {"existing_preserve", "planned_not_configured", "configured_unverified", "verified"}
ALLOWED_CONCURRENCY = {"single_owner"}


def validate_browser_registry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "trendgpt-browser-instances-v1":
        raise ContractError("unsupported browser registry schema")
    instances = value.get("instances")
    if not isinstance(instances, list) or not instances:
        raise ContractError("browser registry instances must be a non-empty array")
    seen_ports: set[int] = set()
    seen_names: set[str] = set()
    seen_roles: set[str] = set()
    for index, item in enumerate(instances):
        if not isinstance(item, dict):
            raise ContractError(f"instances[{index}] must be an object")
        name, role = item.get("name"), item.get("role")
        port, status = item.get("port"), item.get("status")
        if not isinstance(name, str) or not name.strip():
            raise ContractError(f"instances[{index}].name is required")
        if not isinstance(role, str) or not role.strip():
            raise ContractError(f"instances[{index}].role is required")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ContractError(f"instances[{index}].port must be an integer from 1 to 65535")
        if name in seen_names or role in seen_roles or port in seen_ports:
            raise ContractError(f"duplicate browser name, role, or port at instances[{index}]")
        if status not in ALLOWED_STATUS:
            raise ContractError(f"instances[{index}].status is invalid")
        if item.get("concurrency") not in ALLOWED_CONCURRENCY:
            raise ContractError(f"instances[{index}].concurrency must be single_owner")
        if not isinstance(item.get("chatgpt_account"), bool):
            raise ContractError(f"instances[{index}].chatgpt_account must be boolean")
        seen_names.add(name)
        seen_roles.add(role)
        seen_ports.add(port)
    lock = value.get("chatgpt_global_lock")
    if not isinstance(lock, dict) or not isinstance(lock.get("path"), str) or not Path(lock["path"]).is_absolute():
        raise ContractError("chatgpt_global_lock.path must be an absolute path")
    if lock.get("required_for_all_chatgpt_callers") is not True:
        raise ContractError("global ChatGPT lock must be required for all callers")
    return value


def load_browser_registry(path: str | Path) -> dict[str, Any]:
    return validate_browser_registry(load_json(path))


def instance_for_role(registry: dict[str, Any], role: str) -> dict[str, Any]:
    validated = validate_browser_registry(registry)
    matches = [item for item in validated["instances"] if item["role"] == role]
    if len(matches) != 1:
        raise ContractError(f"expected exactly one browser instance for role {role!r}")
    return matches[0]
