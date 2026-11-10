# Steam pilot — VPS live-source verification

## Purpose

Verify the existing Steam Recent Releases and Popular New Releases adapters against the current public Steam store pages using a small, bounded read.

This is a research-only pilot. It does not read TrendOracle, does not compare against the API benchmark, does not query KD/Google Trends/domains, does not write Feishu, and does not dispatch websites.

## Fixed pilot scope

The checked-in plan is config/source-plan.steam-validation.json:

- Steam Recent Releases: US / English, 25 results per page, maximum 2 pages. The source-plan alias recentreleases is translated to Steam's public filter value newreleases.
- Steam Popular New Releases: US / English, 25 results per page, maximum 2 pages.
- The previous VPS run observed 25 rows when count=10 was requested. The pilot now explicitly requests 25 so page-size accounting and pagination offsets are consistent.
- Maximum public page requests: 4 total for one run.
- Steam's Games category filter (category1=998) is added by the adapter.
- The adapter advances by the number of raw Steam result rows actually returned, not by the requested count or only by successfully parsed AppIDs.
- Price, original price, discount and review metadata are extracted from Steam's discount blocks and review tooltip attributes when present; missing values remain null.
- No Steam login or account cookie is required or requested.

The US/English values are an explicit pilot scope, not a claim that this is the only relevant market. Preserve them in every source record so later comparisons do not mix regional scopes.

## Run on the VPS

Use the separate checkout at /root/trendgpt. Do not install this Skill into OpenClaw.

    cd /root/trendgpt
    RUN_DATE="$(TZ=Asia/Shanghai date +%F)"
    STARTED_AT="$(TZ=Asia/Shanghai date --iso-8601=seconds)"
    RUN_ID="steam-pilot-$RUN_DATE-$(date -u +%H%M%S)"
    OUTPUT_ROOT="/root/trendgpt-validation/steam-pilot/self-v1"

    PYTHONPATH=/root/trendgpt/src \
    python3 -m trendgpt.cli collect \
      --source-plan /root/trendgpt/config/source-plan.steam-validation.json \
      --run-id "$RUN_ID" \
      --date "$RUN_DATE" \
      --slot steam-pilot \
      --timezone Asia/Shanghai \
      --started-at "$STARTED_AT" \
      --output-root "$OUTPUT_ROOT" \
      --max-pages-per-source 2 \
      --network-enabled

Use the actual CLI JSON result to locate candidate_keywords.json. Do not guess the run directory; it is derived from the run ID hash.

Then validate the candidate snapshot:

    PYTHONPATH=/root/trendgpt/src \
    python3 -m trendgpt.cli validate \
      --kind candidate \
      --input "$CANDIDATE_PATH"

Then record first-seen state in the same isolated pilot root:

    PYTHONPATH=/root/trendgpt/src \
    python3 -m trendgpt.cli record-first-seen \
      --input "$CANDIDATE_PATH" \
      --output-root "$OUTPUT_ROOT"

The ledger writes a separate enriched snapshot under first-seen/. It must not modify the original candidate file.

## Evidence to inspect

For each of the two Steam source-plan entries, inspect:

- requested URL and query parameters: filter, start, count, category1, cc, language;
- number of pages fetched and page starts;
- Steam's data-total-count when present;
- parsed result count and unique AppIDs;
- duplicate AppIDs within/across pages;
- invalid rows and excluded non-App results;
- pagination completeness and stop reason;
- each raw HTML evidence file and its SHA-256;
- page JSON artifacts;
- candidate source metadata, release-date text and discovery reason;
- candidate AppID and first-seen ledger key.

Do not interpret human-readable release-date text as a precise UTC publication timestamp. The adapter deliberately preserves release_date_text and leaves published_at null until a deterministic parser is justified. Review counts, positive percentage, review label, final/original price and discount are only populated when the corresponding Steam row fields are present.

## Acceptance criteria

PASS:
- the Recent Releases request uses Steam filter=newreleases and Popular New Releases uses filter=popularnew;
- both Steam list endpoints return a recognized page;
- each parsed candidate has a numeric Steam AppID and a valid Steam store app URL;
- candidate JSON passes the existing candidate contract;
- raw HTML evidence exists and its SHA-256 matches its reference;
- page starts/cursors progress without a loop;
- source and market scope are preserved;
- first-seen ledger records stable Steam AppIDs and does not alter the source candidate file;
- no API, paid service, browser, domain, Feishu or website-dispatch action occurs.

PASS_WITH_RISK:
- one endpoint is temporarily unavailable or has a partial/changed page, but the other endpoint yields verifiable candidates and all missing coverage is explicitly reported;
- Steam total count is unavailable, so the adapter keeps pagination/completeness partial;
- the two-page cap is reached while more results remain. This is expected for the pilot and must not be reported as full coverage.

FAIL:
- a non-numeric or mismatched AppID is accepted;
- package/bundle paths are accepted as game AppIDs;
- raw evidence is missing or hash-mismatched;
- a cursor loop causes repeated requests;
- a source with incomplete pagination is reported complete;
- original candidate files are rewritten by the ledger;
- output escapes the explicit self-v1 root.

BLOCKED:
- Steam is unreachable, rate-limits, presents a challenge page, or changes its markup so no result rows can be parsed. Preserve the raw response/evidence and stop; do not attempt browser login, proxies, CAPTCHA bypass or repeated retries.

## Stop boundary

After the one bounded pilot:
- do not increase the page cap;
- do not add other Steam endpoints;
- do not run Roblox or YouTube;
- do not run KD, DataForSEO, Google Trends or domain checks;
- do not install cron/systemd timers;
- do not write to production directories;
- do not call website_create or any dispatch tool.

Return a concise acceptance report with the run ID, source summaries, candidate count, unique AppIDs, pagination status, evidence paths/hashes, ledger result, any blockers, and production-isolation check.
