"""Deterministic historical rule replay without production mutation."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any


def _value(candidate: dict[str, Any], path: str) -> Any:
    current: Any = candidate
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _condition_passes(candidate: dict[str, Any], condition: dict[str, Any]) -> bool:
    field = condition.get("field")
    operator = condition.get("operator")
    expected = condition.get("value")
    if not isinstance(field, str) or operator not in {"eq", "ne", "lt", "lte", "gt", "gte", "in"}:
        raise ValueError("invalid rule condition")
    actual = _value(candidate, field)
    if actual is None:
        return False
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if isinstance(actual, bool) or isinstance(expected, bool) or not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return False
    if not math.isfinite(actual) or not math.isfinite(expected):
        return False
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "gt":
        return actual > expected
    return actual >= expected


def selected_ids(candidates: list[dict[str, Any]], ruleset: dict[str, Any]) -> set[str]:
    """Evaluate an all-conditions ruleset against a frozen candidate set."""
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, list):
        raise ValueError("ruleset.conditions must be an array")
    selected = set()
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            continue
        if all(_condition_passes(candidate, condition) for condition in conditions):
            selected.add(candidate_id)
    return selected


def replay_rules(
    candidates: list[dict[str, Any]],
    baseline_rules: dict[str, Any],
    proposed_rules: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare selection changes and mature observed outcomes; does not publish rules."""
    baseline = selected_ids(candidates, baseline_rules)
    proposed = selected_ids(candidates, proposed_rules)
    outcome_by_id = {
        item.get("candidate_id"): item for item in outcomes
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }

    def summarize(selected: set[str]) -> dict[str, Any]:
        eligible = []
        excluded = {"no_outcome": 0, "immature": 0, "incomplete_revenue": 0, "invalid_metric": 0, "missing_currency_window": 0}
        for candidate_id in sorted(selected):
            item = outcome_by_id.get(candidate_id)
            if item is None:
                excluded["no_outcome"] += 1
                continue
            if item.get("maturity") != "eligible":
                excluded["immature"] += 1
                continue
            if item.get("revenue_status") != "complete":
                excluded["incomplete_revenue"] += 1
                continue
            currency, window_id = item.get("currency"), item.get("window_id")
            if not isinstance(currency, str) or not currency or not isinstance(window_id, str) or not window_id:
                excluded["missing_currency_window"] += 1
                continue
            revenue = item.get("revenue")
            if isinstance(revenue, bool) or not isinstance(revenue, (int, float)) or not math.isfinite(revenue) or revenue < 0:
                excluded["invalid_metric"] += 1
                continue
            eligible.append((candidate_id, currency, window_id, float(revenue)))
        buckets: dict[str, list[float]] = defaultdict(list)
        for _, currency, window_id, revenue in eligible:
            buckets[f"{currency}|{window_id}"].append(revenue)
        return {
            "selected_count": len(selected),
            "mature_observed_count": len(eligible),
            "excluded": excluded,
            "revenue_summaries": [
                {"currency_window": key, "sample_count": len(values), "median_revenue": median(values)}
                for key, values in sorted(buckets.items())
            ],
        }

    base_summary, proposed_summary = summarize(baseline), summarize(proposed)
    return {
        "status": "descriptive_replay" if base_summary["mature_observed_count"] or proposed_summary["mature_observed_count"] else "insufficient_data",
        "baseline_rule_id": baseline_rules.get("rule_id"),
        "proposed_rule_id": proposed_rules.get("rule_id"),
        "candidate_count": len(candidates),
        "baseline": base_summary,
        "proposed": proposed_summary,
        "added_candidate_ids": sorted(proposed - baseline),
        "removed_candidate_ids": sorted(baseline - proposed),
        "production_rules_changed": False,
        "limitations": [
            "unbuilt or unobserved candidates do not have known revenue labels",
            "historical selected-site revenue is subject to selection bias and is not causal evidence",
            "revenue is only summarized within matching currency and window identifiers",
            "this replay never publishes, activates or rolls back production rules",
        ],
    }
