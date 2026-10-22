# Implementation plan

This repository is a staged, portable implementation. A component is not considered complete merely because its interface or folder exists.

## Stage 1 — foundation (current branch)

- [x] Python package metadata and CLI skeleton.
- [x] Strict JSON loader and first-pass validators for candidate, verification, benchmark, run result, and state records.
- [x] Conservative exact/alias normalization.
- [x] Isolated benchmark comparison with null coverage for an unready benchmark.
- [x] Self-v1 state store with a dedicated root, file lock, revision check, and same-slot conflict protection.
- [x] Descriptive revenue grouping that does not mutate rules.
- [x] Provider-neutral source result contracts and conservative candidate merge.
- [x] Bounded Steam, Roblox chart and YouTube RSS source adapters; raw source text is preserved under self-v1 evidence.
- [x] Read-only archived API snapshot conversion; provider freshness/completeness remains unknown by default.
- [ ] Run and review the latest full GitHub Actions test result.
- [ ] Validate public source parsers against current live pages in an approved environment.
- [ ] Review contract fields against a real, redacted local snapshot before relying on the schema in production.

## Stage 1.5 — browser roles and ChatGPT coordination

- [x] Define the browser port registry with 9226/9227 explicitly marked planned, not configured.
- [x] Implement an OS-level shared ChatGPT lock and command wrapper.
- [x] Implement a durable self-v1 ChatGPT queue with idempotency, lease tokens, hash-verified artifacts, and conservative stale-run recovery.
- [x] Add offline tests for lock exclusion, queue idempotency, lease checks, and safe failure handling.
- [ ] Configure and verify 9226 and 9227 on the target VPS without altering existing browser instances.
- [ ] Select the actual shared lock path and integrate it into every `code_before` ChatGPT stage.
- [ ] Implement the Playwright/CDP ChatGPT cleaner worker and validate its output schema.
- [ ] Run an end-to-end shadow batch; verify task ownership, screenshot/evidence, output correctness, and no cross-task contamination.

## Stage 2 — source discovery

1. Validate the Roblox Up-and-Coming and Top Playing Now adapters against current pages, stable identifiers, region/device scope and coverage.
2. Validate Steam recent releases and popular new releases, app IDs, DLC/bundle filtering and pagination.
3. Validate YouTube RSS query behavior and identity-resolution review; keep known-keyword SEO discovery separate from unknown-game discovery.
4. Improve pagination completeness evidence. The current HTML adapters intentionally report partial when full coverage cannot be proven.
5. Implement bounded multi-page collection, per-source checkpointing, run snapshots and incremental updates.
6. Normalize and merge records; ambiguous identity must be reviewed, not fuzzy-merged.
7. Run repeated read-only collection snapshots before creating the trends-miner Skill.

## Stage 3 — validation

1. Confirm Similarweb KD workspace, market/language scope, login state and cost.
2. Confirm DataForSEO endpoint, task schema, account, pricing and query budget.
3. Implement KD query with evidence and caching.
4. Implement DataForSEO prefilter with original task-ID reconciliation; uncertain paid requests must not be resubmitted.
5. Implement Google Trends candidate-versus-GPTs multiline browser review; keep it separate from the existing related-queries script.
6. Implement read-only domain availability adapter while respecting the existing CLI's local-state side effects.
7. Assemble trends-valid only after each component is tested independently.

## Stage 4 — multi-round orchestration and handoff

1. Create isolated self-v1 run snapshots and a review queue.
2. Read site registry and existing in-flight tasks without changing site.json.
3. Add cache fingerprints, budget limits, retry limits and cross-day resume.
4. Add a valid-format Feishu report adapter only after its document/image permissions and write/readback contract are approved.
5. Add a separate, approved self-source adapter to website_create. Never forge the existing trendoracle-ready source policy.
6. Run in shadow mode before any real dispatch. Do not install a timer until explicitly authorized.

## Stage 5 — learning and independent operation

1. Read existing archived API snapshots without triggering the API fetcher.
2. Establish benchmark freshness/completeness rules; the present provider does not expose a confirmed generated_at/updated_at field.
3. Compare independent discoveries, missed records and observed relative discovery timing.
4. Link candidates to website task IDs and domains using a separate mapping table.
5. Read approved, date-aligned GSC, GA and Adsterra observations; exclude immature and incomplete windows.
6. Replay candidate rules on frozen history, then run shadow rules.
7. Release rules only with sufficient sample, measured impact, cost/throughput guardrails, explicit approval and rollback.
8. Turn off API benchmark reads independently from any decision to stop the existing API production pipeline.
