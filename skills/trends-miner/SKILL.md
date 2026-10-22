---
name: trends-miner
description: Discover candidate games from bounded public source adapters, preserve evidence, and write isolated self-v1 candidate snapshots. Does not validate KD/trends or dispatch websites.
---

# trends-miner — current implementation contract

## Status

The Python source adapters and bounded multi-source collector are implemented in this repository, but live source accessibility and completeness have not yet been verified on the target server. Do not enable a timer until that verification is complete.

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

## Rules

- The source collector only discovers and normalizes; it does not run KD, Google Trends, domain checks, Feishu writes or website dispatch.
- Preserve source records and partial/failure statuses. A parse with zero results is not proof of an empty source.
- The current HTML adapters may report partial because they cannot prove full pagination.
- Video titles are unresolved clues, not game names, unless a separate identity-resolution step supplies candidate_name.
- The collector does not mark API-independence eligibility true. That requires a later evidence-backed benchmark exposure adjudication.
- Never write to the existing API output, state, claim, automatic queue or site.json.
