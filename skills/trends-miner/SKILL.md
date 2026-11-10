---
name: trends-miner
description: Discover candidate games from bounded public source adapters, preserve evidence, and write isolated self-v1 candidate snapshots. Does not validate KD/trends or dispatch websites.
---

# trends-miner — current implementation contract

## Status

The Python source adapters and bounded multi-source collector are implemented in this repository. Steam has a VPS PASS_WITH_RISK pilot; Roblox dual-board code is fixture-tested and awaits a corrected bounded VPS pilot; YouTube remains unverified. The Roblox pilot now requests global scope (country=all/device=all), records requested and server-declared effective scope separately, caps oversized responses at maxRows, preserves explicit null metadata fields, and accepts timezone-offset plus signs in ledger run IDs. Do not enable a timer or production Skill until each source is separately verified.

## Required inputs

- run_id: unique run identifier
- date, slot and timezone: caller-provided business time context
- started_at: RFC3339 timestamp with timezone
- output_root: explicit absolute path ending in self-v1
- source plan: JSON using config/source-plan.example.json
- explicit operator permission to perform public HTTPS reads

## Execution

Install the package in a virtual environment, review the source plan, and invoke:

    trendgpt collect --source-plan PATH --run-id RUN_ID --date YYYY-MM-DD --slot SLOT --timezone IANA_ZONE --started-at RFC3339 --output-root /approved/path/self-v1 --network-enabled

The command is opt-in and bounded by per-source page limits. It writes raw source evidence, per-page SourceResult artifacts and candidate_keywords.json under the self-v1 namespace.

## Steam pilot

For a small VPS validation, use config/source-plan.steam-validation.json and follow docs/STEAM_PILOT.md. The plan is explicitly US-English and bounded to two pages of 25 rows per Steam list. The internal Recent Releases alias is translated to Steam filter=newreleases; Popular New Releases uses popularnew. Do not treat this pilot as complete source coverage.

## Roblox dual-board pilot

For the controlled VPS validation, use config/source-plan.roblox-validation.json and follow docs/ROBLOX_PILOT.md. It reads the public Explore API for Up-and-Coming and Top Playing Now with country=all/device=all, 50 rows/page and at most two pages per board (four requests maximum). The endpoint is an observed anonymous web contract, not a stable Open Cloud SLA; no cookies, login, proxies or challenge bypasses are used.

The adapter records requested country/device separately from server-declared effective country/device. A mismatch or missing response declaration is never silently replaced with the requested scope. If Roblox returns more than maxRows, only maxRows rows enter candidate normalization, overflow_rows is recorded, the page is partial, and the opaque token is not followed because it may skip unprocessed overflow rows. Every Roblox source record and source_metadata object keeps a fixed set of metadata keys, with missing values represented explicitly as null. The stable identity is universeId; rootPlaceId remains separate. Player count, votes, genre, creator and sponsored state are retained when supplied.

## First-seen ledger

After a candidate snapshot has been written, record stable platform-ID history in the separate self-v1 ledger:

    trendgpt record-first-seen --input PATH/candidate_keywords.json --output-root /approved/path/self-v1

The command writes a separate enriched snapshot under first-seen/YYYY-MM-DD/RUN_ID and updates entity-ledger.json under the same self-v1 root. It never modifies candidate_keywords.json or production state. Only a single stable platform ID is accepted as an automatic cross-run identity key. Missing IDs, multiple platform IDs, and missing/invalid observation timestamps remain in the review queue.

## Rules

- The source collector only discovers and normalizes; it does not run KD, Google Trends, domain checks, Feishu writes or website dispatch.
- Preserve source records and partial/failure statuses. A parse with zero results is not proof of an empty source.
- The current Roblox and YouTube adapters may report partial because they cannot prove full pagination. The Steam adapter maps Recent Releases to the live Steam filter value newreleases and Popular New Releases to popularnew. It uses category1=998, extracts stable AppIDs from Steam app URLs, reconciles raw row counts with data-total-count, and advances pagination by observed raw rows when Steam returns more than the requested count. The actual filter is retained in page response scope, aggregate source scope, source summaries and candidate source records with `filter_source=request_query_parameter`; this records the sent query parameter and does not claim the provider echoed it. It extracts final/original prices, discounts and review tooltip metadata when present. Exact labels such as Very Positive come from visible text or the tooltip label; CSS classes such as positive are preserved separately and never replace the human-readable rating. Each page's fetched_at is preserved on its own candidate rows through aggregation and first-discovery timestamps. Missing values remain null. A bounded multi-page run remains partial when the page cap is reached before the declared total.
- Video titles are unresolved clues, not game names, unless a separate identity-resolution step supplies candidate_name.
- The collector does not mark API-independence eligibility true. That requires a later evidence-backed benchmark exposure adjudication.
- Never write to the existing API output, state, claim, automatic queue or site.json.
