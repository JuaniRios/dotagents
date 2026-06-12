---
name: enable-remote-checks
description: "Use when the user asks to switch into a remote-checks workflow: minimize expensive local checks, submit with Graphite, watch GitHub CI, and fix failures from CI instead of duplicating the full matrix locally."
---

# enable-remote-checks

Codex-native port of the former Claude slash command `enable-remote-checks`.

This is a session policy for branches where GitHub CI is the source of truth.
Use it when the user wants to avoid long local verification and rely on remote
checks after submitting.

## Session Policy

For the rest of the current task:
- Prefer focused local checks that are cheap and directly relevant to the edit.
- Do not run full workspace CI locally unless the user explicitly asks.
- After edits are ready, amend/commit through Graphite and submit to GitHub.
- Watch the newest CI run for the submitted commit.
- If CI fails, use the `ci-fix` Codex skill to inspect logs, fix locally, amend,
  resubmit, and continue polling.

## Required Companion Skills

- `graphite` for every version-control mutation.
- `ci-fix` when GitHub Actions reports a failure.

## Workflow

1. Record the policy in the conversation so later verification choices are
   explicit: remote CI is authoritative; local checks are scoped.

2. Before mutating version control, verify repository state:
   ```bash
   git status --short
   gt log short
   ```
   If there are unrelated user changes, do not include them in the amend.

3. Run only cheap, targeted local validation:
   - formatter for edited files or the smallest repo formatter command,
   - package-level `cargo check`, `bun test`, or equivalent when the change
     needs a syntax/type gate,
   - narrow tests for the changed behavior.

4. Stage and amend/commit with Graphite:
   ```bash
   gt add <changed-files>
   gt modify
   ```
   Use `gt create <branch-name>` instead when starting a new branch is part of
   the user's request.

5. Submit non-interactively unless the user asked for an interactive flow:
   ```bash
   gt submit --no-interactive --no-edit-description
   ```
   Use `--stack` only when the user asks to submit the whole stack or stack
   policy in the repo requires it.

6. Identify the commit and newest CI run:
   ```bash
   git rev-parse HEAD
   gh run list --branch "$(git branch --show-current)" --limit 10
   ```
   Poll the run until it reaches a terminal state. A long-running poll may use a
   persistent shell session; do not end the task while a required poll is still
   active.

7. On failure:
   - Use `ci-fix`.
   - Fix the root cause locally.
   - Amend with `gt modify`.
   - Resubmit.
   - Poll the new run, not the canceled/stale one.

8. On success, report the branch, commit, PR/run link if available, and the
   checks that passed.

## Hard Rules

- Do not use raw `git commit`, `git push`, `git rebase`, or `git checkout -b`.
- Do not run expensive full local CI after this workflow is enabled unless the
  user explicitly asks.
- Always follow the newest run for the current commit; older canceled runs are
  not authoritative.
- Do not amend unrelated user changes into the branch.
