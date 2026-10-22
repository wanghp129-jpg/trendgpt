# TrendGPT — Independent New-Game Discovery

A portable implementation of Lesson 14's new-game discovery pipeline, developed separately from the existing production API-to-website pipeline.

## Safety boundary

- Existing TrendOracle/API production ingestion, state, claims, queue, timer and website dispatch must not be modified by this project.
- New discovery state uses a separate directory ending in `self-v1`; the runtime caller must pass this root explicitly.
- Discovery, validation, dispatch authorization, dispatch start and website delivery are distinct states.
- No production dispatch, domain purchase, scheduled task installation, credential refresh or paid query runs by default.
- Missing data stays unknown; provider failures are not zeroes and are not keyword rejections.
- API benchmark data is an independent comparison set, never injected into self-discovery results. Benchmark comparison can be disabled without disabling self-discovery.

## Foundation implemented in this branch

- Strict JSON loading and initial contract validators.
- Conservative Unicode/name normalization and exact/known-alias matching.
- Provider-neutral source result types and a first candidate merge implementation.
- Bounded, allowlisted HTTPS adapters for Steam search pages, Roblox public chart pages and supplementary YouTube RSS clues. Raw source pages are hash-bound and saved under the explicit self-v1 evidence root.
- Parsers deliberately report partial/blocked status when they cannot prove full source coverage; a YouTube video title is not automatically treated as a game name.
- Pure Lesson 14 decision gates, with missing data sent to review instead of being silently rejected.
- Isolated, lock-protected self-v1 run state.
- Archived API snapshot reader that never calls the API and never copies the private identity field; benchmark readiness remains false without provider update/completeness evidence.
- API benchmark comparison that reports null coverage unless readiness is established.
- Descriptive revenue grouping that requires mature observations and partitions by currency and window; it does not change production rules.
- CLI for artifact validation, archived API snapshots, explicit opt-in source reads, benchmark comparison and descriptive evaluation.
- GitHub Actions unit-test workflow.

## What is not yet production-ready

The public source adapters have not been validated against current live pages in this development environment. Similarweb KD browser automation, DataForSEO task integration, final candidate-vs-GPTs Google Trends browser review, batch domain availability, Feishu valid-report/image writing, the approved self-source adapter for website_create, complete multi-round orchestration, and historical rule replay/shadow evaluation remain staged work. Contracts and prerequisites are documented, but these integrations must not be represented as working until verified.

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
trendgpt snapshot-api --input /private/archive/raw.json --output-root /safe/path/self-v1 --acquired-at 2026-10-22T08:10:00+08:00
trendgpt compare --benchmark /safe/path/api_benchmark_snapshot.json --self-snapshot /safe/path/candidate_keywords.json --cutoff 2026-10-22T08:00:00+08:00
trendgpt evaluate-rules --input /path/to/mature_observations.json --minimum-samples 5
```

Network reads require explicit opt-in. Prepare a JSON scope file first, then call e.g.:

```bash
trendgpt fetch-source --source steam --scope-json /path/to/steam-scope.json --run-id local-review-01 --fetched-at 2026-10-22T08:00:00+08:00 --output-root /safe/path/self-v1 --page-limit 50 --network-enabled
```

Do not run live collection until the source's current accessibility, use limits, server egress and output path have been approved. The comparison command reads local JSON files only; the rules command is descriptive and never modifies a ruleset.

## Documentation

- `docs/ARCHITECTURE.md` — architecture and production boundaries.
- `docs/DATA_CONTRACTS.md` — proposed self-v1 data contracts.
- `docs/INTERFACES.md` — existing vs proposed integration status.
- `docs/IMPLEMENTATION_PLAN.md` — staged build plan.
- `docs/PORTING.md` — safe migration guide.
- `config/example.json` — illustrative configuration only; review all values before use.
