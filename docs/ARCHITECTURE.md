# Architecture and safety boundaries

## Production isolation

The current API system is a separate production pipeline. TrendGPT must not write into its state, claims, automatic queue, raw/latest artifacts, or dispatch intents. The default runtime namespace for any future deployment is the explicit path ending in `output/self-v1`; callers must pass it explicitly.

## Components

- `trendgpt.contracts`: strict JSON loading and contract checks.
- `trendgpt.normalize`: deterministic Unicode/whitespace normalization and conservative exact/alias matching.
- `trendgpt.benchmark`: optional API comparison. It counts only eligible self-discovered candidates observed before the frozen cutoff.
- `trendgpt.state`: lock-protected state in a dedicated self-v1 directory.
- `trendgpt.rules`: descriptive summaries of mature revenue observations. It never changes production rules.
- `trendgpt.cli`: offline validation and evaluation entry points.
- `trendgpt.browser_registry`: validation of intended CDP port-to-role assignments.
- `trendgpt.chatgpt_coordination`: cross-process `flock` lease; protects only callers that use the same lock path.
- `trendgpt.chatgpt_queue`: durable queue with idempotency, single-running-task state, leases, and conservative recovery.
- `trendgpt.chatgpt_queue_cli`: queue management and serialized worker entry point.

Provider integrations, browser automation, domain checks, Feishu valid-report writing, and website dispatch are not enabled by this foundation. They must be added behind explicit interfaces after credentials, costs, and permissions are verified in the target environment.

## Browser and ChatGPT coordination

Ports 9226 and 9227 are planned roles only, not configured instances. Source collection and ChatGPT cleaning are separate. All ChatGPT callers that may share an account should use the same absolute lock file and hold it for the complete browser interaction. The existing `code_before` scripts are not automatically protected until explicitly wired to that lock. A queue worker must validate its output before completing a task; uncertain submissions go to review, not automatic retry.

## Decision order

1. Same-day state / stage-cache lookup.
2. Existing-site and in-flight task check.
3. KD query; only a real KD below 30 passes.
4. DataForSEO prefilter; complete evidence can block, missing/failed data bypasses to browser review.
5. Google Trends browser verification is the final trend decision.
6. Domain availability check.
7. Report gate and source-specific dispatch authorization.
8. Dispatch intent, actual task reconciliation, and outcome observation.

A candidate passing validation is not itself authorization to dispatch. A started task is not a delivered website.

## API benchmark lifecycle

API snapshots are immutable reference inputs, not discovery candidates. The benchmark comparator returns `benchmark_not_ready` and null coverage unless the snapshot explicitly states complete data, a confirmed update, and evaluation readiness. Disablement returns `disabled`; self-discovery and revenue evaluation remain available.

## Rule optimization

Revenue grouping is descriptive, not causal. Observations are excluded unless maturity is eligible and the revenue window is complete. Rule changes require later historical replay, shadow evaluation, explicit approval, and rollback support; no production rule is changed by this package.
