# YouTube recent-upload clue pilot — VPS verification

## Purpose

Implement Lesson 14's YouTube role as a supplementary clue source, not a primary game-discovery source. The primary sources remain the Roblox and Steam platform lists.

The two query phrases come from the Lesson 14 course material:

- releasedategameplay
- upcominggame gameplay

The adapter opens YouTube search results using the course's recent-upload URL pattern:

    https://www.youtube.com/results?search_query=<ENCODED_KEYWORD>&sp=EgQIAhAB

This is an anonymous public-page read. It does not use YouTube Data API credentials, browser automation, cookies, login, proxies or CAPTCHA bypass.

## Critical identity rule

A video title is not automatically a game name.

The adapter preserves:
- video ID and canonical watch URL;
- title;
- channel name, channel ID and channel URL when present;
- relative published-time text;
- duration and view-count text;
- description snippet;
- search query and rank;
- raw HTML evidence and SHA-256.

It deliberately does not set candidate_name, name or keyword. The existing candidate normalizer therefore retains these records in unparsed_items instead of incorrectly turning titles such as "NEW UPDATE", creator names, reaction videos or unrelated entertainment into game candidates.

A later identity-resolution step must determine the actual game name from the video title, description and supporting evidence. Ambiguous cases stay unresolved; do not fuzzy-merge them into Steam or Roblox entities.

The visible published-time label (for example, "2 hours ago") is relative text, not an exact publication timestamp. published_at remains null until an authoritative absolute timestamp is available.

## Fixed pilot scope

Use config/source-plan.youtube-validation.json:

- Query 1: releasedategameplay
- Query 2: upcominggame gameplay
- Recent-upload filter: sp=EgQIAhAB
- Maximum 15 accepted video results per query.
- One search result page per query.
- Maximum two public YouTube page requests total.

The adapter reads the initial search page only. It detects whether a continuation is present but does not call the YouTube internal continuation endpoint. This keeps the pilot to two requests and avoids relying on undocumented POST/API-key behavior.

If a page contains more than 15 video renderers, the adapter preserves the full raw HTML, admits at most 15, records overflow_rows and remains partial. It does not claim full search coverage.

## Run on the VPS

Use the existing isolated checkout at /root/trendgpt. Do not install this Skill into OpenClaw.

Run the checked-in source plan once with a fresh run ID and an output root under:

    /root/trendgpt-validation/youtube-pilot/self-v1

Use the existing collect CLI and explicit network opt-in. Record the actual CLI JSON and candidate_path; do not guess the hashed run directory.

Validate candidate_keywords.json with the existing Candidate Contract.

Then inspect unparsed_items. For this source, the expected outcome is that video clues remain unparsed until a separate game-identity step exists. Do not count video IDs as game IDs or video titles as confirmed game entities.

Run record-first-seen only against stable, verified game platform IDs. Do not create game entities from YouTube video IDs.

## Evidence and acceptance

For each query, inspect:

- request URL and exact search_query;
- sp=EgQIAhAB;
- HTTP status;
- original HTML evidence and SHA-256;
- whether ytInitialData and the primary search result section were parsed;
- raw video renderer count, accepted count, overflow count and invalid count;
- video ID and watch URL;
- channel ID/name/URL when supplied;
- title and description snippet;
- relative published-time text and null absolute published_at;
- query role, rank and fetched_at;
- continuation presence and explicit single-page limitation;
- final unparsed_items and source-run evidence references.

PASS:
- both queries return a recognized YouTube search result structure;
- every accepted row has a valid 11-character video ID and non-empty title;
- watch URLs match the video IDs;
- channel evidence is preserved when present;
- exact search terms and recent-upload filter are retained;
- raw HTML evidence exists and SHA-256 matches;
- video clues remain unresolved and are not emitted as game entities;
- Candidate Contract passes;
- no login, cookie, browser, proxy, paid API or website dispatch is used.

PASS_WITH_RISK:
- one query returns verifiable results while the other is empty/blocked/changed;
- a page contains a continuation or exceeds the 15-row cap, so the snapshot is explicitly partial;
- channel metadata or absolute publication time is unavailable while video identity/title remain valid.

FAIL:
- video ID/watch URL mismatch;
- video title is silently promoted to candidate_name/game identity;
- raw evidence hash mismatch;
- response rows exceed the configured limit without overflow accounting;
- invalid renderer rows are silently counted as valid;
- the candidate normalizer creates game candidates directly from YouTube video IDs.

BLOCKED:
- HTTP 403/429, challenge, consent gate, unrecognized HTML or missing ytInitialData prevents reliable parsing. Preserve the response if available and stop; do not retry or bypass.

## Stop boundary

After the one bounded pilot:
- do not add more queries;
- do not follow continuation tokens;
- do not run Roblox or Steam again;
- do not run KD, DataForSEO, Google Trends or domain checks;
- do not install cron/systemd timers;
- do not write production directories;
- do not call website_create or any dispatch tool.

Return a report with query-level results, request count, raw/accepted/overflow counts, unique video IDs, evidence hashes, Candidate Contract, unparsed clue count, blockers and production-isolation check.
