---
name: keyword-feedback-loop
description: Compare immutable self-discovery snapshots with an optional archived API benchmark, report missed candidates and discovery timing, and remain usable when benchmark mode is disabled.
---

# keyword-feedback-loop — benchmark and feedback contract

## Current implementation

- Read an already archived API raw file with trendgpt snapshot-api. This command makes no network request.
- Compare the resulting benchmark with self candidate snapshots using trendgpt compare.
- The current API payload does not prove server generation time, update time or complete-set semantics. Its snapshot therefore remains benchmark_not_ready by default, with null coverage.
- API records are reference-only. Never inject them into candidate_keywords.json or count API/manual additions as independent self discoveries.

## Maturity and exit

API benchmarking is a temporary learning mode. The self-discovery and operations pipeline must continue when benchmark mode is disabled. Turning off benchmark reads is separate from stopping the existing API production pipeline.

Before reporting coverage, require a confirmed update, complete benchmark scope, a non-empty denominator, frozen cutoff and evidence-backed identity matches. Ambiguous aliases are not hits. Missing or stale benchmark data produces null coverage.

## Revenue feedback

Use approved archived GA/GSC/Adsterra records and a separate candidate-to-site/task mapping. Exclude immature, incomplete, unmapped and time-window-mismatched observations. The current evaluator is descriptive only; it does not alter discovery or production rules.
