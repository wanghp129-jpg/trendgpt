---
name: chatgpt-browser-coordinator
description: Serialize ChatGPT browser tasks across TrendGPT and cooperating code_before stages, assign each task to a configured browser role, and persist task outcomes safely.
---

# chatgpt-browser-coordinator

## Status

This Skill documents the coordination contract and exposes a generic queue/lock implementation. It does not yet implement the actual Playwright/CDP cleaner or modify the existing code_before runtime. Do not enable automatic scheduling until those integrations are tested.

## Browser roles

Read `config/browser-instances.example.json` and reconcile it with the real VPS before use:
- 9221: existing Similarweb role; preserve.
- 9223: existing code_before Clarity-related role; preserve.
- 9224: existing code_before basic-information role; preserve.
- 9225: existing code_before homepage-information role; preserve.
- 9226: planned TrendGPT source-collection browser; not configured yet.
- 9227: planned TrendGPT ChatGPT-cleaning browser; not configured yet.

Never assume a port is live or available just because it appears in configuration.

## Task lifecycle

1. Save the source batch under the self-v1 root and record its SHA-256.
2. Enqueue one idempotent task with a unique key and the desired browser role.
3. Acquire the single shared ChatGPT lock before any ChatGPT browser interaction.
4. Claim one task; do not let a second worker claim another while a task is running.
5. Submit the prompt, wait for the answer to finish, extract the answer, validate the task-specific output schema, and save the output while still holding the lock.
6. Complete the queue task with the output file's verified SHA-256.
7. Release the lock only after output persistence and task completion are recorded.

## Shared lock rule

All cooperating ChatGPT callers must use the exact same absolute lock path. The lock covers the entire prompt submit/wait/read/save transaction, not just the submit action. Separate CDP ports prevent direct tab collisions but do not eliminate account-level rate limits.

Existing code_before stages must be explicitly wrapped with `trendgpt-chatgpt-lease` or import the same `ChatGPTLease`. Until they do, cross-system serialization is not guaranteed.

## Failure policy

- Failure before prompt submission may be explicitly marked `safe_retry` after evidence supports that conclusion.
- If submission may have happened but the response/output is uncertain, set `needs_review`; do not automatically send the same prompt again.
- A stale running task is moved to review, not silently requeued.
- A successful process exit alone is not proof of a correct cleaning result; the actual worker must validate JSON schema, candidate counts and provenance.

## Scope boundary

This coordinator does not start Chrome, configure CDP, refresh logins, call paid APIs, change code_before files, install timers, dispatch websites, or change production rules.
