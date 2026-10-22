# TrendGPT — Independent New-Game Discovery

A portable, isolated implementation of Lesson 14's new-game discovery pipeline. The project is designed to be developed and tested independently before being migrated to the production server.

## Safety boundary

- The existing TrendOracle/API-to-website production pipeline is out of scope and must not be modified by this project.
- New discovery state lives in a separate `self-v1` namespace.
- Discovery, validation, dispatch authorization, dispatch start, and website delivery are separate states.
- No production dispatch, domain purchase, scheduled task installation, credential refresh, or paid query runs by default.
- Missing data remains unknown; provider failures must never be represented as zero or as a rejected keyword.
- API benchmark data is isolated from independent-discovery scores and can be disabled without disabling the self-discovery pipeline.

See `docs/IMPLEMENTATION_PLAN.md` for the staged implementation and `docs/PORTING.md` for migration guidance.
