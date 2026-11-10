# Roblox dual-board pilot — VPS live-source verification

## Purpose

Verify the independent Roblox chart adapter against the two discovery sources prioritized by Lesson 14:

1. Up-and-Coming
2. Top Playing Now

The implementation reads Roblox's public, anonymous Explore chart content endpoint. It does not use Roblox HTML scraping, browser automation, login cookies, CSRF tokens, Open Cloud credentials, third-party proxies or authenticated APIs.

This is a research-only pilot. It does not read or call TrendOracle, does not run KD/Google Trends/domain checks, does not write Feishu, and does not dispatch websites.

## Endpoint and identity semantics

The adapter calls:

    https://apis.roblox.com/explore-api/v1/get-sort-content

with the corresponding public sort IDs:

- up-and-coming
- top-playing-now

The request includes sessionId, sortId, device, country, maxRows and, when continuing, pageToken. sessionId is a generated public correlation ID derived from the run identifier; it is not a Roblox login session.

The endpoint is an observed Roblox web contract, not a stable Open Cloud API/SLA. A schema change, access restriction or rate limit must produce a visible blocked/failed/partial result. Do not use proxies, cookies or challenge bypasses as fallbacks.

The stable platform identity is the Roblox universeId. The game page URL uses rootPlaceId. These are different identifiers and must never be substituted for one another.

The chart response can expose playerCount, totalUpVotes, totalDownVotes, genre and isSponsored. Missing values remain null. Sponsored rows are preserved and flagged; they are not silently discarded.

## Fixed pilot scope

The checked-in plan is config/source-plan.roblox-validation.json:

- Up-and-Coming: US / computer, 50 rows per page, maximum 2 pages.
- Top Playing Now: US / computer, 50 rows per page, maximum 2 pages.
- Maximum public API requests: 4 total for one run.
- Pagination uses the opaque nextPageToken returned by Roblox.
- No detail, votes, thumbnails or secondary metadata endpoint is called in this pilot.

The country/device scope is explicit and must remain in source scope and candidate metadata. Do not mix other countries or devices in the same comparison.

## Run on the VPS

Use the separate checkout at /root/trendgpt. Do not install this Skill into OpenClaw.

Run the one bounded collection described by this source plan, with a fresh run ID and an output root under:

    /root/trendgpt-validation/roblox-pilot/self-v1

Use the project's existing collect CLI and network opt-in. Record the actual CLI JSON result and use its candidate_path rather than guessing the hashed run directory.

Validate the candidate snapshot with the existing candidate contract, then run record-first-seen against the same isolated self-v1 root. The ledger must write an enriched copy and must not rewrite candidate_keywords.json.

## Evidence to inspect

For each board and page, inspect:

- request URL and sortId;
- country and device;
- maxRows and pageToken;
- HTTP result;
- raw JSON evidence and SHA-256;
- payload path used by the parser;
- raw rows, parsed games, invalid rows and duplicate universe IDs;
- nextPageToken presence and whether it was followed;
- page-specific fetched_at;
- universeId and rootPlaceId;
- game name and official Roblox URL when rootPlaceId is present;
- playerCount, votes, genre and isSponsored when present;
- source rank and list type in candidate source records;
- candidate source_metadata and first-seen ledger output.

Do not report a missing playerCount or vote value as zero. Do not report a missing rootPlaceId as a fabricated game URL.

## Acceptance criteria

PASS:
- both public chart IDs return a recognized games array;
- parsed rows have a numeric universeId and non-empty name;
- universeId is retained as the Roblox platform ID;
- rootPlaceId is kept separately and used for the Roblox game URL when present;
- request country/device/sort scope is preserved;
- opaque page tokens progress without a loop;
- raw JSON evidence exists and SHA-256 matches its reference;
- candidate JSON passes the existing candidate contract;
- first-seen ledger records stable Roblox universe IDs and leaves the raw candidate unchanged;
- no API, paid service, browser, domain, Feishu or website-dispatch action occurs.

PASS_WITH_RISK:
- one board is available and yields verifiable candidates while the other is blocked/empty/changed;
- the endpoint omits nextPageToken or exposes a bounded chart sample whose wider catalog coverage cannot be proven;
- a page cap is reached while another page token remains. The source must remain partial and the next cursor must be reported.

FAIL:
- universeId and rootPlaceId are confused;
- invalid IDs or names are accepted;
- page tokens are repeated or lost;
- incomplete pagination is reported complete;
- raw evidence is missing or hash-mismatched;
- candidate source metadata loses board, country/device, rank or page timestamp;
- original candidate files are rewritten by the ledger;
- output escapes the explicit self-v1 root.

BLOCKED:
- Roblox returns 403/429, a challenge, an unrecognized response shape or a network error that prevents reliable parsing. Preserve the raw response when available and stop. Do not use a proxy, cookie, login, browser, CAPTCHA bypass or automatic retry.

## Stop boundary

After the one bounded pilot:
- do not increase page limits;
- do not add more Roblox sorts;
- do not add detail/votes/icon endpoints;
- do not run Steam or YouTube again;
- do not run KD, DataForSEO, Google Trends or domain checks;
- do not install cron/systemd timers;
- do not write to production directories;
- do not call website_create or any dispatch tool.

Return a concise acceptance report with run ID, board summaries, request count, unique universe IDs, pagination state, evidence paths/hashes, candidate contract, ledger result, blockers and production-isolation check.

## References

- Roblox's official Top Playing Now announcement describes the chart as ranked by concurrent users: https://devforum.roblox.com/t/introducing-top-playing-now-on-charts/3529809
- Roblox's official deprecated-endpoints notice points Discover/chart consumers to the Explore API get-sorts and get-sort-content endpoints: https://devforum.roblox.com/t/official-list-of-deprecated-web-endpoints/62889/59
- The current implementation uses get-sort-content directly for the two fixed chart IDs and does not call the deprecated games.roblox.com/v1/games/sorts or games/list endpoints.
