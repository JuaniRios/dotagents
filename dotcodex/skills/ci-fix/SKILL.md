---
name: ci-fix
description: "Use when the user asks to run the former Claude /ci-fix workflow: Fetch the latest GitHub CI run for this branch, diagnose failures, fix them locally, and amend."
---

# ci-fix

Codex adaptation of the Claude slash command `ci-fix`. Follow the workflow below, but use Codex-native tools and normal user questions where the original mentions Claude-only mechanisms.

Compatibility notes:
- Treat `$ARGUMENTS` as the relevant arguments or intent from the user's request.
- Replace `AskUserQuestion` with a concise question to the user when a decision is required.
- Replace Claude `Agent` calls with Codex subagents only when the user explicitly asks for parallel agents; otherwise do the work locally.
- Ignore Claude `allowed-tools`, `argument-hint`, `TodoWrite`, and `Skill` tool references as tool-permission metadata.
- When the workflow mentions another slash command, use the corresponding Codex skill or follow that workflow directly.

Fetch the latest GitHub Actions CI run for the current branch, parse its
failures, fix them locally, verify the fix, and amend. This is for fixing
**real CI failures** — the full pipeline including nextest, dashboard,
nix builds, and anything else CI runs that `the ci skill` skips locally.

## Stack mode

When invoked as `the ci-fix skill stack`, work through the entire upstack:

1. Record the starting branch.
2. Run the normal `the ci-fix skill` flow on the current branch.
3. After fixes pass, if files were modified, use `the graphite skill` to amend
   via `gt modify -a`.
4. Use `the graphite skill` to `gt up`. If it succeeds, repeat from step 2.
   If it fails or branch didn't change, you've reached the top.
5. If any branch is stuck (iteration cap), stop there.
6. Print a summary of all branches and their result.

## 1. Fetch the latest CI run

```bash
gh run list --branch "$(git branch --show-current)" --limit 5 --json databaseId,status,conclusion,name,headSha
```

Find the most recent completed run. If it **passed**, tell the user:
"Latest CI run passed — nothing to fix." and stop.

If it **failed**, get the run ID and fetch details:

```bash
gh run view <run-id> --json jobs
```

Parse which jobs failed. For each failed job, fetch its logs:

```bash
gh run view <run-id> --log-failed 2>&1
```

This gives the actual error output from the failed steps.

## 2. Parse failures

From the log output, identify each distinct failure:

- **Category**: compile error | test failure | clippy lint | formatting |
  nix build | dashboard lint | dashboard check | other
- **File and line(s)** when present
- **Error message** verbatim
- **Which CI step** it came from

Present a summary to the user:

```
Latest CI run: #<run-id> (<conclusion>)
Failed jobs:
  - <job-name>: <N> errors
    1. <category>: <brief description> (<file>:<line>)
    2. ...
```

## 3. Fix the issues

Apply the same fix rules as `the ci skill`:

- Never suppress lints without permission
- Never delete/skip tests
- Never `.unwrap()` in production code
- Use `Edit` for surgical changes
- No drive-by cleanups

### Fix order

1. **Compile errors** first
2. **Test failures** — fix the code, not the assertion (unless the
   assertion is wrong)
3. **Clippy lints**
4. **Formatting** — run `cargo fmt` / `nixfmt`
5. **Dashboard errors** — fix TypeScript/Svelte issues
6. **Nix build errors** — fix nix expressions

### Verify fixes locally

After fixing, **run only the step that failed** to verify locally.
Use the appropriate command:

| CI step | Local verification |
|---------|-------------------|
| cargo check | `nix develop .#ci-backend -c cargo check --workspace --all-features` |
| nextest | `nix develop .#ci-backend -c cargo nextest run --workspace --all-features` |
| clippy | `nix develop .#ci-backend -c cargo clippy --workspace --all-targets --all-features` |
| fmt | `nix develop .#ci-backend -c cargo fmt -- --check` |
| nixfmt | `nixfmt --check $(find . -name '*.nix' -not -path './.tmp/*' -not -path './.direnv/*')` |
| dashboard lint | `nix develop .#ci-dashboard -c bash -c 'cd dashboard && bun install --frozen-lockfile && bun run lint'` |
| dashboard check | `nix develop .#ci-dashboard -c bash -c 'cd dashboard && bun install --frozen-lockfile && bun run check'` |
| dto codegen | `nix run .#st0x-dto -- dashboard/src/lib/api` |
| genBunNix | `nix run .#genBunNix` |

Use `timeout: 600000` on all `nix develop` / `nix run` commands.
**NEVER use `run_in_background: true`.**

Max **8** fix iterations per step. If stuck, stop and ask.

## 4. On success

1. Print modified files.
2. Print which CI failures were fixed.
3. **If files were modified**, use `the graphite skill` to amend via `gt modify -a`.
4. Stop.

## 5. On failure to converge

1. Print the remaining errors.
2. Print fixes attempted.
3. Give your theory on why you're stuck.
4. Ask the user how to proceed.

## Hard rules

1. Never suppress a lint without explicit user permission.
2. Never delete, skip, or `#[ignore]` a test.
3. Never push — amending via `gt modify -a` is allowed when fixes applied.
4. No drive-by cleanups.
5. Never hand-edit whitespace; use formatters.
6. Cap at 8 iterations; stop and ask if stuck.
7. Read project's `CLAUDE.md` / `AGENTS.md` before fixing.
8. Environment-level failures: report and stop.
