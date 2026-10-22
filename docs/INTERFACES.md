# Provider and system interfaces

This file distinguishes existing integrations from proposed interfaces. A proposed interface is not evidence that the provider, account, credentials, or permission is available.

| Interface | Status in foundation | Expected contract |
| --- | --- | --- |
| API benchmark read | Offline comparison exists; snapshot reader pending | Read an immutable archived snapshot; do not trigger the production API fetcher |
| Site registry read | Pending server adapter | Read site.json and in-flight task evidence; never mutate site.json |
| Source fetch | Provider-neutral dataclasses exist; live adapters pending | One bounded page per call, original source IDs, pagination, completeness, raw evidence, errors |
| Candidate normalization | Exact name normalization and source-record merge exist | Stable IDs preferred; ambiguity preserved |
| KD query | Not implemented | Real Similarweb difficulty plus matching query/market and screenshot evidence |
| Trend prefilter | Not implemented; dependency unverified | DataForSEO task intent, task ID, aligned series and explicit cost controls |
| Google Trends verification | Not implemented | Candidate and GPTs comparison from the same request, final curve data and same-time screenshot |
| Domain availability | Existing server query is not a side-effect-free library call | New adapter must document local writes, interpret all exit branches, and never purchase |
| Feishu valid report | Not implemented | Candidate blocks, real screenshots, complete readback, no placeholders, resumable checkpoint |
| Website dispatch | Existing API-only adapter; self source not accepted yet | Separate approved self-source policy, global dedupe, authorization reference, task reconciliation |
| GA/GSC/revenue read | Existing collectors; unified historical reader pending | Read approved archived results first; preserve timezone, completeness, mapping and nulls |
| Rule evaluation | Descriptive revenue grouping exists | Frozen inputs, maturity gate, versioned replay and shadow evaluation; no production mutation |

## Error policy

- Complete, verified evidence may reject a candidate according to a versioned rule.
- Missing data, auth errors, rate limits, timeouts, ambiguous identity and partial source results must remain reviewable.
- Paid asynchronous requests retain their original task ID. An uncertain submit must be reconciled before another paid request.
- Dispatch response uncertainty must be reconciled against the original request/task metadata. Never retry with a new task ID merely because a process timed out.
