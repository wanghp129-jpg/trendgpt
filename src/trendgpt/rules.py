"""Conservative, read-only rule evaluation from mature observations."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any


def evaluate_feature_groups(
    observations: list[dict[str, Any]],
    *,
    feature_field: str = "features",
    revenue_field: str = "revenue",
    minimum_samples: int = 5,
) -> dict[str, Any]:
    """Describe mature-group revenue differences within matching currency/window."""
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least 2")
    groups: dict[str, list[float]] = defaultdict(list)
    excluded = {
        "immature": 0, "missing_revenue": 0, "invalid_revenue": 0,
        "missing_currency_or_window": 0,
    }
    eligible_count = 0
    for item in observations:
        if item.get("maturity") != "eligible":
            excluded["immature"] += 1
            continue
        if item.get("revenue_status") != "complete":
            excluded["missing_revenue"] += 1
            continue
        currency, window_id = item.get("currency"), item.get("window_id")
        if not isinstance(currency, str) or not currency.strip() or not isinstance(window_id, str) or not window_id.strip():
            excluded["missing_currency_or_window"] += 1
            continue
        revenue = item.get(revenue_field)
        if isinstance(revenue, bool) or not isinstance(revenue, (int, float)) or not math.isfinite(revenue) or revenue < 0:
            excluded["invalid_revenue"] += 1
            continue
        features = item.get(feature_field)
        if not isinstance(features, dict) or not features:
            excluded["invalid_revenue"] += 1
            continue
        eligible_count += 1
        for key, value in features.items():
            if isinstance(value, (str, int, float, bool)) and value is not None:
                label = f"currency={currency}|window={window_id}|{key}={value}"
                groups[label].append(float(revenue))

    summary = []
    for label, values in sorted(groups.items()):
        summary.append({
            "feature_group": label,
            "sample_count": len(values),
            "median_revenue": median(values) if len(values) >= minimum_samples else None,
            "status": "descriptive_only" if len(values) >= minimum_samples else "insufficient_data",
        })
    return {
        "status": "descriptive_only" if any(x["status"] == "descriptive_only" for x in summary) else "insufficient_data",
        "eligible_observations": eligible_count,
        "excluded": excluded,
        "minimum_samples": minimum_samples,
        "groups": summary,
        "production_rules_changed": False,
        "limitations": [
            "observational association is not causal evidence",
            "comparisons are partitioned by explicit currency and equivalent window_id",
            "this module does not replay rules, approve releases, or modify production configuration",
        ],
    }
