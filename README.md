# TrendGPT — Independent New-Game Discovery

A portable implementation of Lesson 14's new-game discovery pipeline, developed separately from the existing production API-to-website pipeline.

## Safety boundary

- Existing TrendOracle/API production ingestion, state, claims, queue, timer and website dispatch must not be modified by this project.
- New discovery state uses a separate directory ending in `self-v1`; the runtime caller must pass this root explicitly.
- Discovery, validation, dispatch authorization, dispatch intent, actual dispatch and website delivery are distinct states.
- No production dispatch, domain purchase, scheduled task installation, credential refresh or paid query runs by default.
- Missing data stays unknown; provider failures are not zeroes and are not keyword rejections.
- API benchmark data is an independent comparison set, never injected into self-discovery results. Benchmark comparison can be disabled without disabling self-discovery.

## Implemented in this branch

- Strict JSON loading and first-pass contract validators.
- Conservative Unicode/name normalization and exact/known-alias matching.
- Provider-neutral source result contracts and candidate merging with unresolved-record preservation.
- Bounded, allowlisted HTTPS adapters for Steam search pages, Roblox public chart pages and supplementary YouTube RSS clues. Raw source pages are hash-bound and saved under the explicit self-v1 evidence root.
- A multi-source collect command with explicit network opt-in, bounded pages, isolated candidate snapshots and per-page artifacts.
- Browser instance registry for existing ports and planned 9226/9227 roles.
- Cross-process ChatGPT `flock` lease wrapper and persistent self-v1 queue with idempotency, single-task claims, SHA-256 output checks, and uncertain-run review.
- Pure Lesson 14 decision gates and a provider-injected validation orchestrator. Missing data goes to review rather than silent rejection.
- Read-only site registry matching, isolated lock-protected self-v1 run state and deterministic rule replay.
- Archived API snapshot reader that never calls the API and never copies the private identity field; benchmark readiness remains false without update/completeness evidence.
- API benchmark comparison and a descriptive mature-revenue evaluator that does not change production rules.
- Deny-by-default dispatch-intent gate and CLI. It requires real hash-verified report, source-policy, global-dedupe and authorization evidence; it rejects API-only `trendoracle-ready` policy reuse and never invokes `website_create`.
- CLI for validation, source collection, archived API snapshots, independence adjudication, benchmark comparison, descriptive evaluation and frozen rule replay.
- Initial OpenClaw Skill contracts, migration docs and GitHub Actions unit tests.

## Not yet production-ready

The public source adapters have only been fixture-tested; current live-page accessibility and full pagination are not yet verified. The 9226/9227 Chrome instances are not configured by this repository. The actual Playwright/CDP ChatGPT cleaner worker and strict output-schema validation are still pending. Existing `code_before` scripts have not yet been wired to the shared lock; until they are, the lock cannot prevent those scripts from running concurrently. Similarweb KD browser automation, DataForSEO task integration, final candidate-vs-GPTs Google Trends browser review, batch domain availability, Feishu valid-report/image writing, in-flight production task reconciliation, the approved self-source adapter for website_create, complete multi-round orchestration, site-performance history joins and rule release/shadow scheduling remain staged work.

## Local use

Requires Python 3.11+; runtime package dependencies are standard library only.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
bash scripts/port-check.sh
trendgpt --help
trendgpt-adjudicate --help
trendgpt-dispatch-intent --help
trendgpt-queue --help
trendgpt-chatgpt-lease --help
trendgpt-queue validate-browser-registry --input config/browser-instances.example.json
```

The browser registry command validates the JSON plan only; it does not check whether CDP ports are live. Queue state must be stored under an explicitly selected path ending in `self-v1`.

## Browser and ChatGPT coordination

Read [docs/BROWSER_AND_CHATGPT_COORDINATION.md](docs/BROWSER_AND_CHATGPT_COORDINATION.md) before configuring ports or running the queue. The global lock path must be chosen on the VPS and must be identical for TrendGPT and every cooperating `code_before` ChatGPT stage. The example path is a placeholder. A lock only protects processes that actually acquire it.

Review the sample plan before any live read:

```bash
trendgpt collect --source-plan config/source-plan.example.json --run-id manual-review-01 --date 2026-10-22 --slot 00 --timezone Asia/Shanghai --started-at 2026-10-22T00:00:00+08:00 --output-root /safe/path/self-v1 --network-enabled
```

The example collection command performs public source requests. Do not run it until current source accessibility, use limits, server egress and output path have been approved. Network collection is disabled unless the explicit `--network-enabled` flag is supplied. The API snapshot command reads local raw files only. The benchmark comparator does not call the API. Revenue evaluation and rule replay are offline-only and never modify a ruleset.

## Skills and docs

- `skills/trends-miner/SKILL.md` — source discovery contract.
- `skills/trends-valid/SKILL.md` — validation contract and current dependency gaps.
- `skills/trends-daily-pipeline/SKILL.md` — future orchestration contract.
- `skills/chatgpt-browser-coordinator/SKILL.md` — browser role and cross-system ChatGPT serialization contract.
- `skills/keyword-feedback-loop/SKILL.md` — API comparison and feedback contract.
- `skills/keyword-rule-optimizer/SKILL.md` — rule evaluation and release boundaries.
- `docs/ARCHITECTURE.md` — architecture and production boundaries.
- `docs/DATA_CONTRACTS.md` — proposed self-v1 data contracts.
- `docs/INTERFACES.md` — existing vs proposed integration status.
- `docs/IMPLEMENTATION_PLAN.md` — staged build plan.
- `docs/PORTING.md` — safe migration guide.
- `docs/BROWSER_AND_CHATGPT_COORDINATION.md` — browser roles, global lock, queue lifecycle and safe migration.
- `config/example.json` — illustrative configuration only; review all values before use.
- `config/browser-instances.example.json` — port plan; 9226/9227 are not configured by this file.
