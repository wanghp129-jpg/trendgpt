# Porting to the existing server

Do not copy this repository over the existing OpenClaw tree wholesale. Port only reviewed files after the stage tests pass.

## Current foundation

1. Use Python 3.11+; the package has no third-party runtime dependencies.
2. Review the branch diff and run the test suite in a clean environment.
3. Install in a virtual environment or invoke with PYTHONPATH=src. Do not install dependencies globally.
4. Choose an explicit output root ending in `self-v1`. Never point the state store at the existing production API output directory.
5. Copy no credentials into Git. Configure provider credentials in the destination server's existing protected credential locations after each provider's contract is verified.
6. Do not enable cron/systemd or dispatch websites during the first migration.
7. Compare output from one authorized read-only source run with a manually verified sample before scaling.

## Not yet production-ready

The current foundation does not contain live Roblox/Steam/YouTube fetchers, Similarweb KD automation, DataForSEO integration, Google Trends final review, domain batching, Feishu valid-report image upload, or the self-source website_create adapter. Do not represent these as implemented.

Existing GA/GSC/Adsterra collectors have side effects and authorization boundaries. The future feedback reader should consume approved archived artifacts first, not blindly invoke collectors. Current GA does not provide page views in its collected schema, and GA/GSC/revenue use different time zones. Do not calculate RPM or ROI until equivalent windows and valid denominators/costs are available.

## Rollback

Keep the self-v1 code and data isolated. Disable the new process and stop reading its namespace if issues occur; do not delete state or alter the existing API timers, queues, claims, site.json, or website_create requests. Restore a prior reviewed code revision and retain failed-run evidence.
