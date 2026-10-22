# Self-v1 data contracts

All schemas in this repository are proposals for the isolated self-v1 pipeline. They do not change the production API payload, existing state files, or website_create contracts.

## Shared conventions

- Timestamps must include a timezone offset; record both local collection time and provider time when the provider actually supplies it.
- Missing values remain null and require a reason; do not convert missing revenue, KD, trend points, or API data to zero.
- Evidence references use an absolute controlled path plus a lowercase SHA-256 digest. Verify the file and digest before relying on evidence.
- Discovery origin is separate from source platform: self_discovered, api_benchmark, manual, external_supplement.
- Keep technical execution status, data completeness, business decision, dispatch authorization, dispatch start, and website delivery as separate facts.
- Raw API snapshots may contain private identity fields. Never copy those fields into self-v1 benchmark artifacts or public reports.

## Candidate snapshot

Required root fields: schema=self-candidate-keywords-v1, run_id, date, slot, timezone, started_at, collected_at, cutoff_at, code_version, normalization_version, source_policy_version, collection_status, completeness, source_runs, candidates.

A candidate records candidate_id, entity_id, canonical_name, aliases, raw_titles, entity_resolution, platforms/platform_ids, discovery_origin, origin_events, first_discovered_at, first_self_discovered_at, independent_eligibility, sources, platform_signals, discovery_reasons, raw_evidence_refs and missing_fields.

Use stable platform identifiers when present. Similar names alone do not prove the same game; ambiguous cross-platform matches remain separate until reviewed.

## Verified snapshot

Each result records the candidate identity, KD evidence, DataForSEO prefilter evidence, final Google Trends status and screenshot, domain availability, final_decision and reasons. A build decision requires identity resolution, real KD below 30, final browser trend approval and at least one currently available domain. It is still not dispatch authorization.

## API benchmark snapshot

Required evidence includes snapshot_id, acquired_at, raw response reference, normalized records, completeness, freshness, update_confirmation and evaluation_status.

The snapshot is ready only when the update is confirmed, the dataset is complete, the eligible record set is non-empty, and usable_for_evaluation is true. If these conditions are not proven, set benchmark_not_ready and keep coverage null.

## Run result and state

Run results track each stage's eligible, attempted, succeeded, failed, skipped and pending-review counts; report receipts; dispatch intents; cost observations; input and output references; code/source/rule versions.

State must be written only under the explicit self-v1 root. Same slot + same run ID + same input hash is idempotent. A conflicting input for an occupied slot must fail instead of overwriting history. Pending review and uncertain dispatch records must survive day boundaries.
