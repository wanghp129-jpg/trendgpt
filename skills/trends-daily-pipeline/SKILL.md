---
name: trends-daily-pipeline
description: Future multi-round orchestration for independent game discovery, validation, reports and authorized handoff. Do not schedule or dispatch until all integration gates pass.
---

# trends-daily-pipeline — integration status

This Skill is a design contract, not yet a production runnable orchestrator.

## Intended sequence

1. Run trends-miner and freeze candidate_keywords.json.
2. Record the immutable run and apply same-day seen state.
3. Read site.json and in-flight task evidence; keep this read-only.
4. Run trends-valid using cached stage results where fingerprints remain valid.
5. Preserve needs_review and cross-day retry queues; do not permanently blacklist technical failures.
6. Produce a valid-format report only after the report adapter supports evidence, image readback and checkpoint recovery.
7. Dispatch only through a separately approved self-source adapter that preserves the existing website_create API source policy.
8. Reconcile the original task ID and save run-result.json/state.json under self-v1.

## Required boundaries

- Do not modify the existing TrendOracle/API timer, output, state, claims, automatic queue or API source policy.
- API benchmark mode is optional and can be disabled independently.
- No cron/systemd changes, real dispatch or domain purchase until the user separately authorizes deployment.
- Provider adapters, report writer, self-source dispatch adapter and cross-source global dedupe are not yet all production-ready.
