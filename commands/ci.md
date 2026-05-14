---
allowed-tools: Bash(nix:*), Bash(cargo:*), Bash(git:*), Bash(gt:*), Bash(cat:*), Bash(grep:*), Bash(tail:*), Bash(wc:*), Bash(test:*), Bash(nixfmt:*), Bash(find:*), Read, Edit, Write, Grep, Glob, TodoWrite, Skill
description: Fast local CI — check, clippy, fmt, nixfmt. Catches most issues in ~3 min. Use /ci-fix for full GitHub CI failures.
argument-hint: "[stack]"
---

Fast local CI verification. Runs the steps most likely to catch issues
locally (~3 min) without the slow steps that real CI handles (nextest,
dashboard, DTO codegen). Fix every issue found, loop until clean.

## What this runs

| Step | Command | Shell | Timeout |
|------|---------|-------|---------|
| 1 | `nixfmt --check` on all `*.nix` files | direct | 60s |
| 2 | `cargo check --workspace --all-features` | `nix develop .#ci-backend -c` | 600s |
| 3 | `cargo clippy --workspace --all-targets --all-features` | `nix develop .#ci-backend -c` | 600s |
| 4 | `cargo fmt -- --check` | `nix develop .#ci-backend -c` | 60s |

**What's intentionally skipped** (real CI catches these):
- `cargo nextest run` — slowest step (~8 min), run manually or let CI do it
- Dashboard steps (genBunNix, st0x-dto, bun lint/check) — only needed
  when dashboard code changes, and CI catches it
- Separate `cargo check --workspace` (without `--all-features`) — the
  `--all-features` variant is a superset

## Stack mode

When invoked as `/ci stack`, run CI on the **entire upstack** — the
current branch and every branch above it in the Graphite stack,
amending each branch's commit as you go.

### Stack flow

1. Record the starting branch: `git branch --show-current`.
2. Run the normal `/ci` flow on the current branch.
3. After CI passes, if any files were modified during the fix loop, use
   `/graphite` to amend the changes into the current branch's commit
   via `gt modify -a`. If no files were modified, skip this step.
4. Attempt to move up the stack. Use `/graphite` to run `gt up`.
   - If `gt up` succeeds (exits 0 and the branch changed), you're on the
     next branch in the stack. Print:
     `"Moving up stack -> <new branch name>"` and repeat from step 2.
   - If `gt up` fails or the branch didn't change, you've reached the top
     of the stack. Print:
     `"Reached top of stack. CI passed on all branches."` and stop.
5. If CI **fails to converge** on any branch (hits the iteration cap),
   stop on that branch. Do NOT continue up the stack — report which
   branch is stuck and follow the normal failure-to-converge flow.
6. When done (success or failure), print a summary of all branches
   visited and their CI result:
   ```
   Stack CI summary:
     branch-a: clean
     branch-b: clean (fixed 2 issues, amended)
     branch-c: stuck (clippy lint -- see above)
   ```

## 1. Preflight

**CRITICAL: Do NOT call `nix run .#ci` as a single monolithic command.**
Run each CI step as a **separate command** via
`nix develop .#ci-backend -c <command>`.

### Verify the ci-backend dev shell exists

```bash
nix eval .#devShells.$(nix eval --impure --expr builtins.currentSystem --raw).ci-backend --apply 'x: "ok"' 2>/dev/null
```

If the working tree is dirty, print a `git status --short` summary.

## 2. Run the steps

**CRITICAL: Run all CI commands directly in the main agent context.** Do
NOT delegate CI to a subagent or Agent tool call.

**CRITICAL: Use `timeout: 600000` (10 minutes) on ALL `nix develop`
commands.** The default 120s timeout causes auto-backgrounding which
breaks the flow. **NEVER use `run_in_background: true`** for CI steps.

### Launch all 4 steps in parallel

Fire all steps simultaneously in a **single message with 4 Bash tool
calls**. This is the fastest approach — total wall-clock time equals the
slowest step (~2-3 min for clippy) instead of the sum of all steps.

```
Bash: nixfmt --check $(find . -name '*.nix' -not -path './.tmp/*' -not -path './.direnv/*')   timeout: 60000
Bash: nix develop .#ci-backend -c cargo check --workspace --all-features 2>&1                  timeout: 600000
Bash: nix develop .#ci-backend -c cargo clippy --workspace --all-targets --all-features 2>&1   timeout: 600000
Bash: nix develop .#ci-backend -c cargo fmt -- --check 2>&1                                    timeout: 60000
```

### Handle results

When all 4 return, check each result:

- **All passed**: go to section 4 (On success).
- **Some failed**: fix the issues (section 3), then re-run **only the
  failed steps** — again in parallel if multiple failed. Already-passed
  steps are not re-run.

Max **8** fix iterations total. Track which steps have passed.

## 3. Fix issues

Apply fixes in this order:

1. **Compile errors** (`cargo check`). Nothing else matters until it compiles.
2. **Clippy lints**. Often reveal design issues -- address the design, not
   the symptom.
3. **Formatting** -- let `cargo fmt` do the work. Never hand-edit whitespace.

### Rules for fixes

- **Never suppress a lint without explicit user permission.** No
  `#[allow(clippy::*)]`, `#[allow(dead_code)]`, etc.
- **Never delete, skip, or disable tests.**
- **Never `.unwrap()` / `.expect()` in production code.**
- **Never create error variants with `String` values.**
- **Stick to the three-group import pattern**: external -> workspace -> crate.
- **No single-letter variables** except short closures with obvious types.

If a fix would violate any project rule, **stop and ask the user**.

### Specific fix patterns

- **Unused imports/variables**: delete them.
- **`too_many_lines` clippy**: ask user for permission to `#[allow]`.
- **`cognitive_complexity` clippy**: extract focused helpers.
- **`fmt --check` failing**: run `cargo fmt`, done.
- **Feature-gate compile errors**: check if `#[cfg(feature = "...")]` is
  missing.

Use `Edit` for surgical changes. Never touch unrelated files.

### Re-running after fixes

Re-run **only the steps that failed** — in parallel if multiple failed.
If they still fail, loop (max 8 total iterations).

**Exception**: if your fix changed code that could affect compilation
(not just formatting), re-run check and clippy together to catch
regressions.

## 4. On success

When all steps pass:

1. Print a summary of modified files (if any).
2. Print:
   ```
   CI passed clean:
     step 1: nixfmt --check
     step 2: cargo check --workspace --all-features
     step 3: cargo clippy --workspace --all-targets --all-features
     step 4: cargo fmt -- --check
   ```
3. **If any files were modified**, use `/graphite` to amend via
   `gt modify -a`.
4. **If no files were modified**, CI was already clean.
5. Stop.

## 5. On failure to converge

If you hit the iteration cap:

1. Print the latest failure's key errors.
2. Print fixes attempted per iteration.
3. Give your best theory on why you're stuck.
4. Ask the user how to proceed.

## Failure modes

- **A step takes >10 min**: increase timeout to `900000`. **Never use
  `run_in_background`**.
- **Environment issues**: report and stop.
- **`sqlx` database error**: run `sqlx db reset -y` per project docs.
- **Build directory lock**: wait, don't kill processes.

## Hard rules

1. Never suppress a lint without explicit user permission.
2. Never delete, skip, or `#[ignore]` a test to make CI pass.
3. Never push -- the user drives pushes. Amending via `gt modify -a` is
   allowed (and expected) when CI fixes were applied.
4. Never make unrelated changes -- no drive-by cleanups.
5. Never hand-edit whitespace; run `cargo fmt` for formatting.
6. Cap at 8 iterations per step; stop and ask if you don't converge.
7. Read the project's `CLAUDE.md` / `AGENTS.md` before applying fixes.
8. If an environment-level failure is the cause, stop and tell the user.
