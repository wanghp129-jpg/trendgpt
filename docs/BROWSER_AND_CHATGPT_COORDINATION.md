# Browser instances and ChatGPT coordination

## Purpose

This design keeps source collection, ChatGPT cleaning, and existing website-generation work on separate browser instances while serializing ChatGPT submissions across cooperating processes. It does not start Chrome or change the VPS.

## Port registry

`config/browser-instances.example.json` is a plan, not a live inventory.

| Port | Role | State in this repository |
| --- | --- | --- |
| 9221 | Similarweb validation | Existing; preserve |
| 9223 | code_before Clarity-related work | Existing; preserve |
| 9224 | code_before basic information | Existing; preserve |
| 9225 | code_before homepage information | Existing; preserve |
| 9226 | TrendGPT Steam/Roblox source browser | Planned, not configured |
| 9227 | TrendGPT ChatGPT keyword cleaner | Planned, not configured |

Before deployment, inspect the VPS and reconcile this example with the actual launch arguments, login state, and running jobs. A port number in this file is not proof that a browser is listening or available. Do not start or restart existing instances to match the example.

The collector on 9226 should not need a ChatGPT login. The cleaner on 9227 will require a dedicated, valid ChatGPT session if browser-based ChatGPT interaction is used.

## One task at a time per browser

A single CDP-controlled tab must have one owner at a time. Do not run two scripts that navigate, type, click, or read answers from the same tab concurrently. For initial deployment, also serialize ChatGPT submissions across the account even when they use different Chrome ports; separate ports do not guarantee independent account-level rate limits.

## Cross-process ChatGPT lock

`trendgpt.chatgpt_coordination.ChatGPTLease` uses an OS `flock` on a shared absolute lock-file path. The lock must cover the whole browser interaction: navigate/open conversation, submit prompt, wait for completion, extract and validate response, save output, and record the result. Do not release it immediately after submitting a prompt.

Every cooperating ChatGPT caller must use the exact same lock path. The example config intentionally contains a `/CHANGE-ME/` path; choose and create a real shared path during server deployment. A lock protects only programs that cooperate with it. If code_before or another script bypasses the lock, TrendGPT cannot prevent that process from submitting concurrently.

Example wrapper syntax after the real path and caller script have been verified:

```bash
trendgpt-chatgpt-lease \
  --lock-path /ABSOLUTE/SHARED/PATH/chatgpt-global.lock \
  --owner code_before \
  --task-id homepage-example-001 \
  --timeout-seconds 900 \
  -- bash /VERIFIED/PATH/get-homepage-info.sh
```

This is an interface example, not a command to paste as-is. Replace both paths and ensure the wrapped command represents the complete ChatGPT interaction. Never wrap only the prompt-submission step while leaving response polling outside the lock.

## Persistent task queue

The queue writes to `output/self-v1/chatgpt-queue/queue.json` and uses a separate queue-state lock. It supports:

- idempotent enqueue by caller-provided key;
- one running task at a time in this queue;
- lease-token-checked completion/failure;
- SHA-256 verification of input/output JSON files;
- safe retry only when the caller explicitly asserts failure happened before prompt submission;
- uncertain or stale runs moved to `needs_review`, never blindly re-submitted.

Recommended lifecycle:

1. Freeze collected candidate JSON under self-v1.
2. Enqueue one batch-cleaning task referencing that file.
3. A worker acquires the shared ChatGPT lock, claims one task, executes the full browser interaction, writes valid JSON, and records its hash.
4. Verify output schema and counts before marking the task complete.
5. Enqueue the next batch only after the prior result is recorded.

The current generic queue does not itself implement the browser-based ChatGPT cleaner. That worker must be added and validated separately. Do not treat a generic successful subprocess as a correct cleaning result without output-schema validation.

## CLI interface

After installation in a virtual environment:

```bash
trendgpt-queue validate-browser-registry --input config/browser-instances.example.json
trendgpt-queue list --output-root /APPROVED/PATH/output/self-v1
```

`validate-browser-registry` validates configuration only; it does not probe CDP ports. The `run-next` command is for a reviewed worker that reads `TRENDGPT_TASK_JSON`, `TRENDGPT_INPUT_PATH`, `TRENDGPT_OUTPUT_PATH`, `TRENDGPT_TASK_TYPE`, and `TRENDGPT_INSTANCE_ROLE`. It holds the global ChatGPT lock across the worker and marks uncertain failures for review.

## What is not done yet

- No Chrome instance has been configured on 9226 or 9227.
- No VPS process, port, credential, login session, timer, or existing code_before file has been changed.
- The existing code_before scripts have not yet been wired to the shared lock; that is required for cross-system exclusion.
- The actual Playwright/CDP ChatGPT cleaning worker, prompt, response schema checks, and real-page acceptance remain to be implemented.
