---
name: keyword-rule-optimizer
description: Produce evidence-backed rule improvement proposals from mature site outcomes and frozen candidate history. Never mutates production rules automatically.
---

# keyword-rule-optimizer — current contract

The current implementation only summarizes mature revenue observations by feature group, requiring explicit currency and equivalent window identifiers. It is descriptive, not causal, and is not yet a rule replay/optimizer.

A future optimizer must:

1. Use frozen candidate, validation, cost and mature site-performance observations.
2. Exclude incomplete revenue days, unverified site links, sites without active ads and other immature observations.
3. Avoid comparing metrics across currencies or non-equivalent time windows.
4. Compare old and proposed rules on the same frozen historical candidates.
5. Report coverage, candidate volume, false-reject review needs, provider cost, discovery delay and uncertainty.
6. Run in shadow mode without dispatch/configuration write access.
7. Require explicit review, versioned publication and rollback before production changes.

Do not adjust a KD threshold, source priority, scan frequency or trend rule based on one or two high-revenue sites.
