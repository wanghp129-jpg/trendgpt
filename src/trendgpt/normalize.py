"""Deterministic, conservative candidate-name normalization."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable


def normalize_name(value: str) -> str:
    """Normalize Unicode and whitespace while preserving meaningful punctuation."""
    if not isinstance(value, str):
        raise TypeError("candidate name must be a string")
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


def candidate_keys(name: str, aliases: Iterable[str] = ()) -> set[str]:
    return {key for value in [name, *aliases] if value and (key := normalize_name(value))}


def resolve_exact(name: str, candidates: list[dict]) -> dict:
    """Resolve exact/known-alias matches only; never silently fuzzy-merge entities."""
    needle = normalize_name(name)
    matches = []
    for candidate in candidates:
        keys = candidate_keys(candidate.get("canonical_name", ""), candidate.get("aliases", []))
        if needle and needle in keys:
            matches.append(candidate)
    if len(matches) == 1:
        return {"status": "matched", "method": "normalized_exact_or_alias", "candidate": matches[0]}
    if len(matches) > 1:
        return {"status": "ambiguous", "method": "normalized_exact_or_alias", "candidate": None}
    return {"status": "missed", "method": "none", "candidate": None}
