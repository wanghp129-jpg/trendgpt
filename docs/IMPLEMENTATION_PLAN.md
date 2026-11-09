# Implementation plan

This repository is a staged, portable implementation. A component is not considered complete merely because its interface or folder exists.

## Stage 1 — foundation

- [x] Python package metadata and CLI skeleton.
- [x] Strict JSON loader and first-pass validators for candidate, verification, benchmark, run result, and state records.
- [x] Conservative exact/alias normalization.
- [x] Isolated benchmark comparison with null coverage for an unready benchmark.
- [x] Self-v1 state store with a dedicated root, file lock, revision check, and same-slot conflict protection.
- [x] Descriptive revenue grouping that does not mutate rules.
- [x] Provider-neutral source result contracts and conservative candidate merge.
- [x] Bounded Steam, Roblox chart and YouTube RSS source adapters; raw source text is preserved under the explicit self-v1 evidence root.
- [x] Read-only archived API snapshot conversion; provider freshness/completeness remains unknown by default.
- [x] Original foundation revision had 72 offline tests passing; every subsequent revision requires fresh CI.
- [ ] Validate public source parsers against current live pages in an approved environment.
- [ ] Review contract fields against a real, redacted local snapshot before relying on the schema in production.

## Stage 1.1 — TrendOracle morning archive reader

- [x] Add a read-only reader for the existing trendoracle-ingest tmp/fetch-*/summary.json, response.json, and immutable data/raw/date/morning/hash.json evidence.
- [x] Select the earliest valid successful/duplicate morning run for a requested Shanghai business date; ignore evening snapshots and do not substitute latest.json or observations.jsonl.
- [x] Reconcile summary run ID, date/window, response/raw byte equality, and SHA-256 filename/content.
- [x] Preserve not_open_yet attempts before the first successful morning response.
- [x] Write the sanitized API reference under the independent self-v1/benchmarks/date/snapshot-id namespace; never copy the raw identity field.
- [x] Record the operator-declared 00:00 mining / 08:00 publication schedule separately from provider timestamps.
- [x] Keep source_batch_id, source_updated_at, published_at, collected_at, and ingested_at null when the provider/local summary does not supply them.
- [x] Force batch_alignment_status=operator_declared_unverified and evaluation_status=benchmark_not_ready; do not report coverage from this artifact.
- [x] Add same-batch date/timezone gates to the benchmark comparator.
- [ ] Run the reader on the VPS's real 2026-11-09 archive and inspect its generated manifest before relying on it.
- [ ] Verify the exact deployed trendoracle-ingest source revision matches the public openclaw-config source used to define this reader.

The command is local-only and does not invoke fetch-daily.py:

    trendgpt snapshot-api-ingest \
      --ingest-root /root/.openclaw/skills/trendoracle-ingest \
      --date 2026-11-09 \
      --output-root /root/.openclaw/skills/keyword-feedback-loop/output/self-v1

A successful local morning read is not proof that the provider's returned set is complete or that the provider explicitly identifies the 00:00 batch. The current API payload exposes date and window, but no batch ID, generated/updated timestamp, pagination total, or full-set assertion. The reader therefore records the owner-declared schedule and leaves benchmark evaluation disabled. benchmark_not_ready is an expected safe result, not a script failure.

## Stage 1.2 — cross-day first-seen entity ledger

- [x] Add a persistent entity ledger under the explicit self-v1 root, separate from daily run state and API production memory.
- [x] Use stable platform IDs as the only automatic cross-run identity key.
- [x] Preserve first/last observed timestamps, source IDs, evidence references and idempotent run observations.
- [x] Keep same-title/different-platform-ID records separate; no fuzzy or title-only merge.
- [x] Route missing IDs, multiple platform IDs and missing timestamps into a persistent review queue.
- [x] Enrich a copy of each candidate snapshot with stable entity IDs and ledger-backed first_self_discovered_at; never modify the original input snapshot.
- [x] Add a CLI command and offline tests for first-seen persistence, cross-day continuity, idempotency and ambiguity.
- [ ] Run the ledger on real Self snapshots after the first approved VPS source collection; verify platform IDs and source timestamps before using the values in benchmark comparisons.

Command:

    trendgpt record-first-seen --input candidate_keywords.json --output-root /approved/path/self-v1

The ledger does not infer cross-platform equivalence. A record with zero or multiple platform ID pairs remains needs_review. First-seen time is the source-observed timestamp carried by the candidate, not the TrendOracle mining time or API publication time.

## Stage 1.5 — browser roles and ChatGPT coordination

- [x] Define the browser port registry with 9226/9227 explicitly marked planned, not configured.
- [x] Implement an OS-level shared ChatGPT lock and command wrapper.
- [x] Implement a durable self-v1 ChatGPT queue with idempotency, lease tokens, hash-verified artifacts, and conservative stale-run recovery.
- [x] Add offline tests for lock exclusion, queue idempotency, lease checks, and safe failure handling.
- [ ] Configure and verify 9226 and 9227 on the target VPS without altering existing browser instances.
- [ ] Select the actual shared lock path and integrate it into every code_before ChatGPT stage.
- [ ] Implement the Playwright/CDP ChatGPT cleaner worker and validate its output schema.
- [ ] Run an end-to-end shadow batch; verify task ownership, screenshot/evidence, output correctness, and no cross-task contamination.

## Stage 2.1 — Steam Recent Releases / Popular New Releases pilot implementation

- [x] Recognize Steam search_result_row markup as well as the legacy search_result fixture shape.
- [x] Extract and reconcile numeric AppIDs from the app URL and data-ds-appid when present.
- [x] Apply Steam's Games category filter (category1=998); reject package/bundle paths and AppID mismatches.
- [x] Preserve release-date text, price/review metadata, list type, source rank, page cursor and hash-bound raw HTML evidence.
- [x] Read data-total-count when available and reconcile expected rows for each page.
- [x] Keep completeness unknown/partial when the source total is absent, rows mismatch, duplicate IDs occur, or the bounded page cap is reached.
- [x] Add pagination cursor-cycle protection and aggregate page evidence into one source-plan result.
- [x] Add a US-English Steam-only pilot plan bounded to two pages of ten rows for each of Recent Releases and Popular New Releases.
- [ ] Run the bounded live Steam pilot on the VPS; verify current markup, public access, AppIDs, page totals and raw evidence.
- [ ] Verify real Steam candidates through the first-seen ledger; confirm AppID and observed-at semantics.
- [ ] Only after the live pilot passes, consider expanding Steam pagination or adding another Steam discovery endpoint.

See docs/STEAM_PILOT.md. The checked-in pilot plan is a controlled validation scope, not a claim of complete Steam coverage.

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
2. Establish benchmark freshness/completeness rules; the present provider does not expose a confirmed generated_at/updated_at field or a complete-set assertion.
3. Compare independent discoveries, missed records and observed relative discovery timing only after same-date/timezone batch alignment is verified.
4. Link candidates to website task IDs and domains using a separate mapping table.
5. Read approved, date-aligned GSC, GA and Adsterra observations; exclude immature and incomplete windows.
6. Replay candidate rules on frozen history, then run shadow rules.
7. Release rules only with sufficient sample, measured impact, cost/throughput guardrails, explicit approval and rollback.
8. Turn off API benchmark reads independently from any decision to stop the existing API production pipeline.
