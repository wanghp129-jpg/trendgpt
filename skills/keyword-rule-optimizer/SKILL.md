---
name: keyword-rule-optimizer
description: Produce evidence-backed rule improvement proposals from mature site outcomes and frozen candidate history. Never mutates production rules automatically.
---

# keyword-rule-optimizer — current contract

The repository contains two offline-only tools:
- descriptive grouping of mature revenue by feature group, currency and equivalent window;
- frozen-candidate rule replay, which compares selection changes and summarizes mature observed outcomes without publishing rules.

These are evaluation primitives, not a complete autonomous optimizer. They do not yet join production site/task history or derive reliable causal estimates.

## Required safeguards

1. Use frozen candidate, validation, cost and mature site-performance observations.
2. Exclude incomplete revenue days, unverified site links, sites without active ads and other immature observations.
3. Avoid comparing metrics across currencies or non-equivalent time windows.
4. Compare baseline and proposed rules on the same frozen candidate set.
5. Report selection changes, observed mature samples, missing outcomes, provider cost, discovery delay and uncertainty.
6. Treat revenue on previously built/selected sites as selection-biased observational evidence; do not assign zero revenue to unbuilt candidates.
7. Run in shadow mode without dispatch/configuration write access.
8. Require explicit review, versioned publication and rollback before production changes.

The CLI command `trendgpt replay-rules` performs local replay only. It does not call providers or mutate production rules.

Do not adjust a KD threshold, source priority, scan frequency or trend rule based on one or two high-revenue sites.
