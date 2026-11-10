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
- [x] Bounded Steam, Roblox chart and YouTube recent-upload search adapters; raw source text is preserved under the explicit self-v1 evidence root.
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
- [x] Map the Recent Releases source-plan alias to Steam's actual public filter value newreleases; keep Popular New Releases as popularnew.
- [x] Apply Steam's Games category filter (category1=998); reject package/bundle paths and AppID mismatches.
- [x] Preserve release-date text, final/original price, discount, exact human-readable review label, review tooltip/class/count/positive percentage, list type, source rank, page cursor and hash-bound raw HTML evidence when present.
- [x] Preserve the actual Steam filter value in page response scope, aggregate source scope, source summaries and candidate source metadata, explicitly labelling it as the request query parameter rather than a provider echo.
- [x] Preserve each page's independent fetch timestamp through page aggregation, per-source records, origin events and first-self-discovered timestamps.
- [x] Reconcile raw result-row count with data-total-count; use visible pagination text as a fallback when the data attribute is absent.
- [x] Advance the next cursor by observed raw result rows, not requested page size or accepted AppID count, so Steam returning 25 rows for count=10 does not stop pagination.
- [x] Keep completeness unknown/partial when the source total is absent, raw rows mismatch, duplicate IDs occur, or the bounded page cap is reached.
- [x] Add pagination cursor-cycle protection and aggregate page evidence into one source-plan result.
- [x] Add a US-English Steam-only pilot plan bounded to two pages of 25 rows for each of Recent Releases and Popular New Releases.
- [x] Complete bounded VPS Steam pilots and isolate real candidate/ledger verification.
- [x] VPS acceptance is PASS_WITH_RISK: Candidate Contract and isolated first-seen ledger passed; Recent Releases provider-side filter effect remains unverifiable.
- [ ] Only after additional provider-side filter evidence exists, consider expanding Steam pagination or adding another Steam discovery endpoint.

See docs/STEAM_PILOT.md. The checked-in pilot plan is a controlled validation scope, not a claim of complete Steam coverage.

## Stage 2.2 — Roblox dual-board remediation after VPS FAIL

- [x] Change the controlled pilot to global scope (country=all/device=all), matching the server-declared effective scope observed in the previous VPS run.
- [x] Preserve requested scope separately from response-declared effective scope; a mismatch or missing declaration is explicit and downgrades source status rather than being mislabeled.
- [x] Enforce maxRows at candidate admission. When the endpoint returns more than requested, preserve the full raw JSON evidence, admit only the first maxRows, record overflow_rows, mark partial and do not follow a token that may skip unprocessed rows.
- [x] Preserve a fixed Roblox source-record and source_metadata field set, including explicit null values for missing player/vote/genre/creator/sponsored fields.
- [x] Accept safe timezone-offset plus signs in first-seen ledger run IDs such as +0800.
- [x] Add offline tests for effective-scope mismatch, oversized responses, null metadata preservation and timezone-offset run IDs.
- [x] Complete the bounded Roblox VPS pilot and verify real candidates, Candidate Contract, isolated first-seen ledger and idempotency.
- [x] VPS acceptance is PASS_WITH_RISK: 2 successful requests, 197 raw rows, 100 admitted rows, 97 overflow rows and 95 unique candidates; effective scope remains unverified and coverage is truncated.

The corrected pilot remains global unless a future endpoint response proves a narrower effective scope. It is still a selected-chart sample, not a crawl of the Roblox catalog.

## Stage 2.3 — YouTube recent-upload supplementary discovery implementation

- [x] Implement anonymous YouTube search HTML parsing using the Lesson 14 recent-upload URL filter sp=EgQIAhAB.
- [x] Add the two course queries: releasedategameplay and upcominggame gameplay.
- [x] Preserve video ID, title, channel identity, description, duration, view-count and relative published-time evidence.
- [x] Keep absolute published_at null when only relative display text is available.
- [x] Keep video titles unresolved; do not turn video IDs or titles into game entities.
- [x] Add bounded one-page-per-query collection, row cap, overflow accounting and hash-bound raw HTML evidence.
- [x] Add offline parser, URL/filter, video identity, unresolved-title and overflow tests.
- [ ] Run the bounded YouTube live pilot on the VPS; verify both search queries, current HTML structure, video/channel IDs, evidence hashes and candidate contract.
- [ ] Design a separate evidence-backed video-to-game identity resolution step; ambiguous titles remain unparsed.

## Stage 2.4 — Candidate Resolver / identity adjudication

- [x] Create deterministic, hash-bound review plans from candidate snapshots and unparsed source clues.
- [x] Suggest exact normalized candidate-name/alias phrases found in YouTube titles or descriptions; suggestions never auto-approve.
- [x] Apply only approved decisions with reviewer, reason and evidence references already present in the original snapshot.
- [x] Link reviewed YouTube clues to existing game candidates without using video IDs as game IDs.
- [x] Create reviewer-approved name-only candidates without fabricated platform IDs; route them to first-seen review.
- [x] Preserve reviewed non-game clues and all original unparsed source evidence for audit.
- [x] Support explicit cross-platform candidate merges, reject conflicting IDs on the same platform, preserve all source/platform evidence and carry forward the earliest observed timestamp.
- [x] Normalize Unicode, punctuation and symbol variants for comparison and alias de-duplication without fuzzy identity merging.
- [x] Add deterministic candidate quality tiers A/B/C/REVIEW based on stable identity and independent source evidence, not trend potential.
- [x] Add CLI commands prepare-resolution and resolve-candidates; write resolved snapshots/reports separately and reject stale input hashes or output overwrites.
- [x] Add prompts/candidate-resolution.md so ChatGPT suggestions remain pending and cannot self-approve.
- [ ] Use the resolver on a real VPS snapshot; review YouTube clues and validate output/ledger behavior before treating identity resolution as operational.

See docs/CANDIDATE_RESOLVER.md. The resolver is offline and does not invoke an LLM; ChatGPT/human review is an explicit plan-editing step. KD/trend validation remains outside this component.

## Stage 2 — source discovery

1. Complete the bounded VPS pilot for Roblox Up-and-Coming and Top Playing Now; verify anonymous access, stable universe IDs, root place IDs, chart metadata, opaque pagination and evidence hashes.
2. Keep the Steam source at its current PASS_WITH_RISK state; the Recent Releases server-side filter effect remains unverifiable until evidence can establish it.
3. Implement and validate YouTube recent-upload supplementary discovery using the Lesson 14 query phrases and upload filter; keep video-title clues separate from confirmed game identity resolution.
4. Improve source-specific pagination completeness evidence without claiming a full Roblox or Steam catalog crawl.
5. Add bounded per-source checkpointing, run snapshots and incremental updates after each adapter passes its live pilot.
6. Normalize and merge records; ambiguous identity must be reviewed, not fuzzy-merged.
7. Run repeated read-only collection snapshots before enabling any schedule or creating a production Skill.

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
