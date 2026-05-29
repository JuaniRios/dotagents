---
allowed-tools: Bash(gt:*), Bash(gh:*), Bash(git:*), Bash(cargo:*), Read, Edit, Write, Grep, Glob, Skill, TodoWrite
description: Offload heavy verification to remote CI instead of running it locally — amend, submit, then poll the CI run until it finishes.
---

Switch this session into **remote-checks mode**: stop burning local machine time
on slow, heavy verification and let GitHub CI do it instead. Adopt the policy
below for the rest of the session, then run the submit-and-poll cycle.

## Policy for the rest of this session

**Do NOT run heavy checks locally on this machine.** These are slow here and are
exactly what remote CI exists to run:

- `nix run .#ci` and any full CI matrix
- `cargo nextest run --workspace` / `--all-features` (the full test suite)
- `nix develop .#ci-backend -c ...` heavy invocations, nix builds
- dashboard `bun run check` / lint full passes

**Light local checks are still fine and encouraged** for fast iteration feedback:

- `cargo check -p <crate>`
- `cargo clippy -p <crate>`
- targeted `cargo nextest run <specific_test>` (a single test or module)

Use the light checks while iterating; push the heavy stuff to CI.

## The submit-and-poll cycle

Run this whenever the work is ready for a heavy verification pass.

### 1. Amend and submit

Route all version-control mutations through the `/graphite` skill.

1. Amend the current branch with all working-tree changes: `gt modify -a`
   (amend, not a new stacked fix commit — this is the user's standing
   preference).
2. Submit to trigger remote CI: `gt submit --no-interactive`.

If there is nothing to amend (clean tree) but CI hasn't run on HEAD yet, still
submit so CI runs.

### 2. Find the CI run for this HEAD

CI takes a few seconds to register after the push. Capture the pushed SHA and
locate its run:

```bash
git rev-parse HEAD
gh run list --branch "$(git branch --show-current)" --limit 5 \
  --json databaseId,status,conclusion,headSha,createdAt,name
```

Match the run whose `headSha` equals the pushed HEAD. If none appears yet, check
again once or twice before giving up.

### 3. Poll until it finishes (~10 min)

Watch the run in the **background** so you can keep working while CI runs — the
harness re-invokes you when it exits:

```bash
gh run watch <run-id> --exit-status
```

Run this with `run_in_background: true`. Do not block the foreground on it. Tell
the user CI is running (~10 min) and continue with any remaining light work.

### 4. When CI finishes

- **Passed** (`gh run watch` exits 0): tell the user CI is green and report the
  run URL.
- **Failed** (non-zero exit): hand off to `/ci-fix` to fetch the failed logs,
  diagnose, and fix locally — then re-run this cycle (amend + submit + poll).
  Repeat until green.

## Hard rules

1. Never run the full local CI / workspace test suite while in this mode — that
   defeats the purpose. Light per-crate `check`/`clippy` and targeted single
   tests are the only local verification allowed.
2. Always amend with `gt modify -a`, never stack a separate fix commit, unless
   the user asks otherwise.
3. Route every git mutation through `/graphite`; never raw `git commit`/`push`.
4. Poll CI in the background — never block the foreground for 10 minutes.
5. On CI failure, fix and resubmit; do not leave the branch red without telling
   the user.
