# Provider and system interfaces

This file distinguishes implemented offline logic from unverified server integrations. A proposed interface is not evidence that a provider, account, credential, permission, or live page is available.

| Interface | Status in foundation | Expected contract |
| --- | --- | --- |
| API benchmark read | Offline archive converter and comparison exist | Reads an immutable local raw snapshot; never triggers the production API fetcher; defaults to benchmark_not_ready |
| Browser registry / ChatGPT coordination | Registry validation, shared OS lock, durable queue and generic worker CLI exist | 9226/9227 are planned only; every cooperating ChatGPT caller must use the same real lock path; actual browser cleaner and code_before integration remain pending |
| Site registry read | Read-only site.json schema check and direct-name lookup exist | Never mutates site.json; keyword-only collisions are review items, not hard duplicates; live in-flight task reconciliation remains pending |
| Source fetch | Steam, Roblox and YouTube RSS adapters implemented but live access unverified | One bounded page/feed per call, source IDs, pagination hints, partial status, raw evidence and errors |
| Candidate normalization | Exact name normalization and source-record merge exist | Stable IDs preferred; ambiguous cross-platform matches preserved; unresolved video titles stay unparsed; independence eligibility is not assumed |
| KD query | Not implemented | Real Similarweb difficulty plus matching query/market and screenshot evidence |
| Trend prefilter | Not implemented; dependency unverified | DataForSEO task intent, task ID, aligned series and explicit cost controls |
| Google Trends verification | Not implemented | Candidate and GPTs comparison from the same request, final curve data and same-time screenshot |
| Domain availability | Existing server query is not a side-effect-free library call | New adapter must document local writes, interpret all exit branches, and never purchase |
| Feishu valid report | Not implemented | Candidate blocks, real screenshots, complete readback, no placeholders, resumable checkpoint; existing table writer alone does not prove this contract |
| Website dispatch | Intent-only artifact gate exists; actual adapter remains unimplemented | Requires a distinct approved self-source policy (explicitly not `trendoracle-ready`), verified report evidence, clear API/self/inflight dedupe evidence, explicit authorization evidence and task reconciliation |
| GA/GSC/revenue read | Existing collectors; unified historical reader pending | Read approved archived results first; preserve timezone, completeness, mapping and nulls |
| Rule evaluation | Descriptive grouping and frozen-candidate replay exist | Frozen inputs, maturity gate, versioned replay and shadow evaluation; no production mutation |

## Error policy

- Complete, verified evidence may reject a candidate according to a versioned rule.
- Missing data, auth errors, rate limits, timeouts, ambiguous identity and partial source results must remain reviewable.
- Paid asynchronous requests retain their original task ID. An uncertain submit must be reconciled before another paid request.
- Dispatch response uncertainty must be reconciled against the original request/task metadata. Never retry with a new task ID merely because a process timed out.
- The dispatch-intent CLI only writes `output/self-v1/dispatch-intents/*.json`; it never invokes `website_create`.
- The repository default branch initially contained only a README. The production OpenClaw runtime is outside this repository, so no server Skill, timer, credential or production file was modified by this work.
