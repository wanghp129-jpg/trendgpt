# Candidate Resolver — identity adjudication and merge

## Purpose

Candidate Resolver implements Lesson 14's post-collection step:

1. recognize actual game names from raw source records and YouTube video clues;
2. merge only entities whose identity is supported by stable IDs or an explicitly approved adjudication;
3. normalize Unicode, punctuation and symbol variants for comparison;
4. retain ambiguous records for review;
5. produce a new resolved candidate snapshot without modifying the original collection output.

The resolver is deliberately conservative. Similar names, shared words, matching thumbnails, channel names, or a YouTube video ID are not sufficient identity proof.

## Current implementation boundary

- No LLM/API call is made by this module.
- prepare-resolution creates a deterministic review plan containing the original clue, description, channel/video evidence, exact phrase suggestions and hash-bound evidence references.
- ChatGPT or a human reviewer can inspect that plan and fill decisions.
- resolve-candidates applies only decisions with approval_status=approved and a non-empty reviewed_by and reason.
- Pending or unresolved decisions remain in unparsed_items.
- Original candidate_keywords.json is read-only and its SHA-256 is checked before and after resolution.

This separation means an LLM can suggest a name or link, but cannot silently mutate entity identity.

## Identity rules

### Stable platform IDs

- Steam AppID identifies a Steam app.
- Roblox universeId identifies a Roblox experience.
- YouTube video_id identifies a video only. It is never inserted into platform_ids as a game ID.

The collection merge already deduplicates repeated records by stable platform identity within a source/platform.

### Exact-name suggestions

normalize_entity_key applies Unicode NFKC, case folding, punctuation/symbol normalization and whitespace collapse. It is used for comparison and alias de-duplication only.

The plan may suggest a candidate when its full normalized name or alias occurs as a phrase in the YouTube title/description. Suggestions are advisory. They do not approve a link or merge.

Short names are omitted from automatic phrase suggestions to reduce false positives.

### Approved actions

Each clue decision uses one of:

- link_existing: attach the YouTube evidence to an existing Steam/Roblox candidate. This does not change the target's platform IDs.
- create_candidate: create a reviewed-name candidate from a YouTube clue. It has no platform ID and is marked quality tier C / review required until a stable game-platform ID is established.
- not_game: mark a clue as reviewed non-game content. The original clue remains in the audit list.
- unresolved: leave the clue untouched for later review.

Cross-candidate merges are a separate merges array. A merge requires explicit approval, reviewer, reason and evidence references. Conflicting IDs for the same platform are rejected. A cross-platform merge preserves both platform IDs; because the first-seen ledger currently auto-confirms only a single stable platform ID, such a merged entity remains in the ledger review queue rather than being silently confirmed.

Every approved decision must reference evidence already present in the source snapshot. The resolver verifies the referenced file still exists and its SHA-256 matches.

## Candidate quality tiers

These are identity/evidence quality labels, not trend or commercial scores:

- A: exactly one stable platform ID and at least two independent source IDs.
- B: exactly one stable platform ID and fewer than two independent source IDs.
- C: reviewer-approved name or explicit cross-platform merge, but not one unambiguous platform ID for the ledger.
- REVIEW: identity/platform evidence remains insufficient.

No tier means a keyword is suitable for building. KD, DataForSEO, Google Trends and domain checks belong to trends-valid.

## Workflow

Run inside the isolated project environment with the existing virtualenv.

### 1. Prepare a review plan

    trendgpt prepare-resolution \
      --input /approved/path/self-v1/runs/<run>/candidate_keywords.json \
      --output-root /approved/path/self-v1

The command writes:

    identity-resolution/<date>/<run-hash>/resolution-plan.json

It reports the number of unresolved clues and exact phrase suggestions. No decision is applied.

### 2. Review the plan with ChatGPT or a human

Use prompts/candidate-resolution.md as the review instruction. Provide the plan and available source evidence excerpts to ChatGPT or a human reviewer. The reviewer should inspect the actual linked HTML/JSON evidence where available, not infer identity from a title alone. The prompt requires all suggestions to remain pending until the operator approves them.

For each clue, fill the decision fields:

    "action": "link_existing | create_candidate | not_game | unresolved",
    "approval_status": "approved | pending",
    "reviewed_by": "reviewer identifier",
    "reason": "evidence-backed explanation"

For link_existing, also provide target_candidate_id. For create_candidate, provide canonical_name and optional aliases. Keep evidence_refs limited to references already present in the plan.

To merge two existing platform candidates, add an approved object to merges with primary_candidate_id, secondary_candidate_id, reviewed_by, reason and references from both candidates.

Do not approve uncertain or title-only guesses. Leave them pending.

### 3. Apply approved decisions to a new artifact

    trendgpt resolve-candidates \
      --input /approved/path/self-v1/runs/<run>/candidate_keywords.json \
      --plan /approved/path/self-v1/identity-resolution/<date>/<run-hash>/resolution-plan.json \
      --output-root /approved/path/self-v1

Outputs:

- identity-resolution/<date>/<run-hash>/resolved-candidate_keywords.json
- identity-resolution/<date>/<run-hash>/resolution-report.json

Existing output paths are never overwritten. The plan is tied to the exact original input SHA-256; a stale plan is rejected.

### 4. Validate and record first-seen history

    trendgpt validate --kind candidate --input <resolved-candidate_keywords.json>
    trendgpt record-first-seen --input <resolved-candidate_keywords.json> --output-root /approved/path/self-v1

The ledger confirms candidates with one stable platform ID and a valid observed timestamp. YouTube-only reviewed-name candidates and cross-platform merged candidates with multiple platform IDs are sent to review; they are not assigned fake IDs.

## Safety and non-goals

- No network access, browser, CDP, API credentials or paid service is used.
- No automatic fuzzy matching or title-only merge.
- No YouTube video ID is treated as a game ID.
- No TrendOracle call, KD check, trend validation, domain lookup, Feishu write or website dispatch.
- No timer or production Skill installation.
- The resolver does not claim YouTube's relative published_time_text is an absolute publication timestamp.
