"""Read-only site registry matching for the isolated discovery pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
from .normalize import normalize_name


def read_site_registry(path: str | Path) -> dict[str, Any]:
    """Read the existing site.json without mutating or migrating its schema."""
    obj = load_json(path)
    if not isinstance(obj, dict) or not isinstance(obj.get("sites"), list):
        raise ContractError("site registry must be an object containing a sites array")
    domains = set()
    for index, site in enumerate(obj["sites"]):
        if not isinstance(site, dict):
            raise ContractError(f"sites[{index}] must be an object")
        domain = site.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise ContractError(f"sites[{index}].domain is required")
        key = domain.strip().casefold().removeprefix("https://").removeprefix("http://").rstrip("/")
        if key in domains:
            raise ContractError(f"duplicate registered domain: {key}")
        domains.add(key)
    return obj


def lookup_candidate(candidate: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    """Match direct game/topic identity first; do not treat fuzzy or keyword-only collisions as built."""
    target_names = {
        normalize_name(candidate.get("canonical_name", "")),
        *(normalize_name(alias) for alias in candidate.get("aliases", []) if isinstance(alias, str)),
    }
    target_names.discard("")
    direct_matches = []
    keyword_matches = []
    for site in registry.get("sites", []):
        direct = set()
        for field in ("topic_name", "game_name"):
            value = site.get(field)
            if isinstance(value, str) and value.strip():
                direct.add(normalize_name(value))
        if target_names & direct:
            direct_matches.append(site)
            continue
        keywords = site.get("keywords")
        if isinstance(keywords, str):
            keyword_names = {normalize_name(part) for part in keywords.split(",") if part.strip()}
            if target_names & keyword_names:
                keyword_matches.append(site)
    matches = direct_matches if direct_matches else keyword_matches
    if len(matches) == 1 and direct_matches:
        site = matches[0]
        return {"status": "already_built", "match_method": "topic_or_game_name",
                "domain": site.get("domain"), "site_status": site.get("status")}
    if len(matches) == 1 and keyword_matches:
        return {"status": "needs_review", "match_method": "keyword_only",
                "domain": matches[0].get("domain"), "reason": "keyword-only match is not sufficient to block a game"}
    if len(matches) > 1:
        return {"status": "ambiguous", "match_method": "multiple_registry_matches",
                "domains": [site.get("domain") for site in matches]}
    return {"status": "clear", "match_method": "no_direct_registry_match"}
