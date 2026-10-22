# Implementation plan

This repository is a staged, portable implementation. A component is not considered complete merely because its interface or folder exists.

## Stage 1 — foundation (current branch)

- [x] Python package metadata and CLI skeleton.
- [x] Strict JSON loader and first-pass validators for candidate, verification, benchmark, run result, and state records.
- [x] Conservative exact/alias normalization.
- [x] Isolated benchmark comparison with null coverage for an unready benchmark.
- [x] Self-v1 state store with a dedicated root, file lock, revision check, and same-slot conflict protection.
- [x] Descriptive revenue grouping that does not mutate rules.
- [ ] Run automated tests in CI and fix all failures.
- [ ] Review contract fields against a real, redacted local snapshot before relying on the schema in production.

## Stage 2 — source discovery

1. Verify the real Roblox Up-and-Coming and Top Playing Now page shapes, stable identifiers, pagination and region/device coverage.
2. Verify Steam recent releases and popular new releases, app IDs, DLC/bundle filtering and pagination.
3. Inspect existing YouTube query implementation for reusable internals; keep known-keyword SEO discovery separate from unknown-game discovery.
4. Implement source adapters that preserve raw evidence, source status, pagination/cursors, and partial failures.
5. Normalize and merge records; ambiguous identity must be reviewed, not fuzzy-merged.
6. Run repeated read-only collection snapshots and compare source completeness before creating the trends-miner Skill.

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
