---
name: keyword-feedback-loop
description: Compare immutable self-discovery snapshots with an optional archived API benchmark, report missed candidates and discovery timing, and remain usable when benchmark mode is disabled.
---

# keyword-feedback-loop — benchmark and feedback contract

## Current implementation

- Read the existing local TrendOracle morning archive with trendgpt snapshot-api-ingest --ingest-root ABS --date YYYY-MM-DD --output-root ABS/self-v1. This command only reads tmp/fetch-*/summary.json, each run's response.json, and the matching immutable morning raw file. It never calls the API or fetch-daily.py.
- For one explicitly selected raw file, use trendgpt snapshot-api --input RAW --acquired-at RFC3339 --output-root ABS/self-v1.
- Compare the resulting benchmark with self candidate snapshots using trendgpt compare.
- The business schedule is 00:00 Asia/Shanghai mining and around 08:00 publication. The local morning ingest run start is not the provider mining timestamp.
- The current API payload does not prove server generation time, update time, batch ID, or complete-set semantics. The reader records the operator-declared schedule as operator_declared_unverified and keeps the snapshot at benchmark_not_ready, with null coverage.
- API records are reference-only. Never inject them into candidate_keywords.json or count API/manual additions as independent self discoveries.

## Morning snapshot selection

- Select the earliest valid successful/duplicate morning run for the requested Shanghai business date.
- Reconcile summary run ID, date/window, response path, raw path, byte equality and SHA-256.
- Preserve not_open_yet attempts before the first successful morning response.
- Never use latest.json or observations.jsonl as a substitute for the immutable morning raw; evening ingest can replace latest and observations is a latest-per-platform/keyword ledger, not a history archive.
- Missing/invalid buckets or unparsed records are partial. A clean parse is still only unknown completeness because the provider does not assert a full result set.
- The raw API identity field is never copied to self-v1 output.

## Maturity and exit

API benchmarking is a temporary learning mode. The self-discovery and operations pipeline must continue when benchmark mode is disabled. Turning off benchmark reads is separate from stopping the existing API production pipeline.

Before reporting coverage, require a confirmed update, complete benchmark scope, a non-empty denominator, verified batch alignment, exact batch_date/timezone match, frozen cutoff and evidence-backed identity matches. Ambiguous aliases are not hits. Missing or stale benchmark data produces null coverage.

## Revenue feedback

Use approved archived GA/GSC/Adsterra records and a separate candidate-to-site/task mapping. Exclude immature, incomplete, unmapped and time-window-mismatched observations. The current evaluator is descriptive only; it does not alter discovery or production rules.
