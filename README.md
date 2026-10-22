# TrendGPT — Independent New-Game Discovery

A portable implementation of Lesson 14's new-game discovery pipeline, developed separately from the existing production API-to-website pipeline.

## Safety boundary

- Existing TrendOracle/API production ingestion, state, claims, queue, timer and website dispatch must not be modified by this project.
- New discovery state uses a separate directory ending in `self-v1`; the runtime caller must pass this root explicitly.
- Discovery, validation, dispatch authorization, dispatch start and website delivery are distinct states.
- No production dispatch, domain purchase, scheduled task installation, credential refresh or paid query is run by default.
- Missing data stays unknown; provider failures are not zeroes and are not keyword rejections.
- API benchmark data is an independent comparison set, never injected into self-discovery results. Benchmark comparison can be disabled without disabling self-discovery.

## Foundation implemented in this branch

- Strict JSON loading and initial contract validators.
- Conservative Unicode/name normalization and exact/known-alias matching.
- Provider-neutral source result types and a first candidate merge implementation.
- Pure Lesson 14 decision gates, with missing data sent to review instead of being silently rejected.
- Isolated, lock-protected self-v1 run state.
- API benchmark comparison that reports null coverage unless completeness and update confirmation are established.
- Descriptive revenue grouping that requires mature observations and partitions by currency and window; it does not change production rules.
- CLI for validating artifacts, comparing archived snapshots and summarizing mature revenue groups.
- GitHub Actions unit-test workflow.

## What is not yet implemented

Live Roblox, Steam and YouTube source adapters; Similarweb KD browser automation; DataForSEO task integration; final candidate-vs-GPTs Google Trends browser review; batch domain availability; Feishu valid-report/image writing; the approved self-source adapter for website_create; complete multi-round orchestration; historical rule replay and shadow evaluation are still staged work. Their contracts and prerequisites are documented, but they must not be represented as working integrations until verified.

## Local use

Requires Python 3.11+; runtime package dependencies are standard library only.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
trendgpt --help
```

Examples:

```bash
trendgpt validate --kind candidate --input /path/to/candidate_keywords.json
trendgpt compare --benchmark /path/to/api_benchmark_snapshot.json --self-snapshot /path/to/candidate_keywords.json --cutoff 2026-10-22T08:00:00+08:00
trendgpt evaluate-rules --input /path/to/mature_observations.json --minimum-samples 5
```

The comparison command reads local JSON files only; it does not call the API. The rules command is descriptive and never modifies a ruleset.

## Documentation

- `docs/ARCHITECTURE.md` — architecture and production boundaries.
- `docs/DATA_CONTRACTS.md` — proposed self-v1 data contracts.
- `docs/INTERFACES.md` — existing vs proposed integration status.
- `docs/IMPLEMENTATION_PLAN.md` — staged build plan.
- `docs/PORTING.md` — safe migration guide.
- `config/example.json` — illustrative configuration only; review all values before use.
