# Provider and system interfaces

This file distinguishes implemented offline logic from unverified server integrations. A proposed interface is not evidence that a provider, account, credential, permission, or live page is available.

| Interface | Status in foundation | Expected contract |
| --- | --- | --- |
| API benchmark read | Local archive reader implemented; real VPS archive verification pending | trendgpt snapshot-api-ingest --ingest-root ABS --date YYYY-MM-DD --output-root ABS/self-v1 reads the earliest successful local morning run only. It reconciles summary/response/raw and hashes; never calls the API or ingest script. It records the operator-declared 00:00/08:00 schedule but remains benchmark_not_ready until provider batch identity, freshness and completeness can be proven. |
| Direct raw snapshot conversion | Implemented offline | trendgpt snapshot-api --input RAW --acquired-at RFC3339 --output-root ABS/self-v1; converts one explicitly selected archived raw file and never triggers a network request. |
| Browser registry / ChatGPT coordination | Registry validation, shared OS lock, durable queue and generic worker CLI exist | 9226/9227 are planned only; every cooperating ChatGPT caller must use the same real lock path; actual browser cleaner and code_before integration remain pending. |
| Site registry read | Read-only site.json schema check and direct-name lookup exist | Never mutates site.json; keyword-only collisions are review items, not hard duplicates; live in-flight task reconciliation remains pending. |
| Source fetch | Steam, Roblox and YouTube RSS adapters implemented but live access unverified | One bounded page/feed per call, source IDs, pagination hints, partial status, raw evidence and errors. |
| Candidate normalization | Exact name normalization and source-record merge exist | Stable IDs preferred; ambiguous cross-platform matches preserved; unresolved video titles stay unparsed; independence eligibility is not assumed. |
| First-seen entity ledger | Implemented offline; real source ID/timestamp semantics pending VPS validation | trendgpt record-first-seen --input CANDIDATE_JSON --output-root ABS/self-v1. Persists first/last observed times only for one stable platform ID; title-only, missing-ID and multi-platform records enter review. It does not fuzzy-merge entities. |
| KD query | Not implemented | Real Similarweb difficulty plus matching query/market and screenshot evidence. |
| Trend prefilter | Not implemented; dependency unverified | DataForSEO task intent, task ID, aligned series and explicit cost controls. |
| Google Trends verification | Not implemented | Candidate and GPTs comparison from the same request, final curve data and same-time screenshot. |
| Domain availability | Existing server query is not a side-effect-free library call | New adapter must document local writes, interpret all exit branches, and never purchase. |
| Feishu valid report | Not implemented | Candidate blocks, real screenshots, complete readback, no placeholders, resumable checkpoint; existing table writer alone does not prove this contract. |
| Website dispatch | Intent-only artifact gate exists; actual adapter remains unimplemented | Requires a distinct approved self-source policy (explicitly not trendoracle-ready), verified report evidence, clear API/self/inflight dedupe evidence, explicit authorization evidence and task reconciliation. |
| GA/GSC/revenue read | Existing collectors; unified historical reader pending | Read approved archived results first; preserve timezone, completeness, mapping and nulls. |
| Rule evaluation | Descriptive grouping and frozen-candidate replay exist | Frozen inputs, maturity gate, versioned replay and shadow evaluation; no production mutation. |

## API batch semantics

- The business schedule is operator-declared: TrendOracle mines at 00:00 Asia/Shanghai and publishes around 08:00; Self Mining is intended to start at the same 00:00 batch.
- Local ingest run start time is not provider mining time. Run ID, summary-file mtime, and API publication time must not be conflated.
- The current provider payload contains date and window, but no source batch ID, generated/updated timestamp, pagination total, or full-set assertion.
- The reader therefore stores batch_alignment_status=operator_declared_unverified, completeness=unknown (or partial when parsing/count evidence is incomplete), and evaluation_status=benchmark_not_ready.
- The reader selects the earliest successful morning run for the requested date, preserves prior not_open_yet attempts, and never substitutes evening latest.json or the mutable observations.jsonl.
- The comparator requires a verified batch alignment and Self snapshots with the exact same batch_date and timezone before it can calculate coverage.

## Error policy

- Complete, verified evidence may reject a candidate according to a versioned rule.
- Missing data, auth errors, rate limits, timeouts, ambiguous identity and partial source results must remain reviewable.
- Paid asynchronous requests retain their original task ID. An uncertain submit must be reconciled before another paid request.
- Dispatch response uncertainty must be reconciled against the original request/task metadata. Never retry with a new task ID merely because a process timed out.
- The dispatch-intent CLI only writes output/self-v1/dispatch-intents/*.json; it never invokes website_create.
- The repository default branch initially contained only a README. The production OpenClaw runtime is outside this repository, so no server Skill, timer, credential or production file was modified by this work.
