---
name: trends-valid
description: Validate self-discovered candidates through KD, trend prefilter, final Google Trends browser review and domain availability. Provider integrations are not yet production-ready.
---

# trends-valid — validation contract

## Status

The provider-injected decision orchestrator exists in src/trendgpt/validation.py. Live Similarweb KD, DataForSEO and candidate-versus-GPTs Google Trends adapters are not yet implemented and verified. Do not treat this Skill as production-ready.

## Required order

1. Read isolated self-v1 state and site/in-flight registry.
2. KD: only a real, valid value strictly below 30 passes.
3. DataForSEO prefilter: complete, trustworthy evidence may reject; missing/error/timeout bypasses to browser review.
4. Google Trends browser review is the final trend decision.
5. Domain availability check.
6. Identity resolution, report confirmation, source policy, global dedupe and explicit authorization are required before any dispatch.

## Safety rules

- Missing data, browser failure and provider errors are needs_review, not keyword rejection.
- KD >= 30 may be rejected according to the current course gate.
- Domain unavailability does not prove the game keyword is bad.
- A validation result of build is not dispatch authorization.
- No paid requests, browser navigation, domain registration, Feishu writes or website dispatch should run until the corresponding adapter and permissions are explicitly verified.
