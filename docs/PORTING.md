# Porting to the existing server

Do not copy this repository over the existing OpenClaw tree wholesale. Port only reviewed files after the stage tests pass. The repository's default `main` initially contained only a README; the production OpenClaw runtime is outside this repository and has not been modified by this branch.

## Current foundation

1. Use Python 3.11+; the package runtime has no third-party dependencies.
2. Review the branch diff and run the test suite in a clean environment.
3. Install in a virtual environment. Do not install dependencies globally.
4. Choose an explicit output root ending in `self-v1`. Never point the state store or evidence writer at the existing production API output directory.
5. Copy no credentials into Git. Configure provider credentials in the destination server's existing protected credential locations only after each provider contract is verified.
6. Do not enable cron/systemd or dispatch websites during the first migration.
7. The Steam, Roblox and YouTube adapters have fixture-tested parsers but have not been verified against current live pages. Start with one bounded, explicitly approved read per source, inspect raw evidence and compare with a manually verified sample before scaling.
8. Do not call the archived API snapshot reader with a live fetcher. It reads an already archived raw file and defaults the benchmark to `benchmark_not_ready` when freshness/completeness cannot be proven.
9. The dispatch-intent CLI creates only an intent record under `self-v1`. It never calls `website_create`; all evidence, policy, global dedupe and authorization gates must be real and hash-verified.

## Current integration gaps

The current foundation has public-source adapters and a provider-injected validation orchestrator, but no live Similarweb KD automation, DataForSEO task integration, final Google Trends browser review, batch domain availability adapter, Feishu valid-report/image writer, in-flight production task reconciler, or approved self-source `website_create` adapter. The existing server's `write-table-doc.sh` does not prove that the required candidate-block/screenshot valid report contract is implemented.

The existing website build entry currently expects an API-specific `trendoracle-ready` approval policy. Do not forge that policy or alter the existing API branch to accept self-discovered candidates. A separately reviewed self-source policy and adapter are required before any real dispatch.

Existing GA/GSC/Adsterra collectors have side effects and authorization boundaries. The future feedback reader should consume approved archived artifacts first, not blindly invoke collectors. Current GA does not provide page views in its collected schema, and GA/GSC/revenue use different time zones. Do not calculate RPM or ROI until equivalent windows and valid denominators/costs are available.

## Rollback

Keep the self-v1 code and data isolated. Disable the new process and stop reading its namespace if issues occur; do not delete state or alter the existing API timers, queues, claims, site.json, or website_create requests. Restore a prior reviewed code revision and retain failed-run evidence.
