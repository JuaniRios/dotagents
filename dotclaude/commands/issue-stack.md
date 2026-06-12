---
allowed-tools: Bash(claude:*), Bash(git:*), Bash(gt:*), Bash(gh:*), Bash(linear:*), Bash(mkdir:*), Bash(tail:*), Bash(test:*), Bash(wc:*), Read, Skill, AskUserQuestion, TodoWrite
description: Cheap-model babysitter that implements a whole stack of Linear issues overnight. Runs on Sonnet; for each issue in order it spawns a fresh headless Opus session running "/night-shift /implement-issue <issue>", waits for it to finish, verifies the branch/PR landed, then spawns the next one stacked on top. Fresh context per issue + cheap orchestrator turns = large token savings vs one giant session.
argument-hint: <issue-1> <issue-2> [issue-3 ...]
---

# Issue stack

You are the **babysitter**, not the implementer. Your job is to spawn one
fresh headless Opus session per issue, in order, each stacking its branch on
top of the previous one — and to burn as few tokens as possible doing it.
Never read source code, never review diffs, never fix anything yourself.

`$ARGUMENTS` is an ordered list of Linear issue IDs/links (e.g.
`RAI-801 RAI-802 RAI-803`). Order matters: issue N+1 stacks on issue N's
branch. If empty, ask the user for the list.

Track per-issue progress with `TodoWrite`.

## Step 0 — Pre-flight (the only interactive moment)

1. **Model check.** You should be a cheap model. If your system prompt says
   you are Fable, tell the user to switch with `/model sonnet` and stop.
2. **Repo state.** Verify cwd is the intended repo/worktree, the tree is
   clean (`git status --porcelain` empty), and note the current branch — the
   stack grows from `gt top` of it. If dirty, stop and tell the user.
3. **Issues exist.** `linear issue view <ID>` for each; stop on any miss.
4. **Confirm the plan** with the user in one shot: the ordered issue list,
   the base branch, and that children run with
   `--dangerously-skip-permissions` and are pre-authorized to push/submit
   their PRs. Then go autonomous — no further questions until the report.

## Step 1 — Spawn the child for the current issue

```bash
mkdir -p .tmp/issue-stack
claude -p --model opus --dangerously-skip-permissions \
  "/night-shift /implement-issue <ISSUE-ID> — HEADLESS STACKED RUN, no user until morning. Standing instructions: (1) Your plan is pre-approved: do NOT use EnterPlanMode/ExitPlanMode/AskUserQuestion; decide every design fork yourself and log it. (2) Pushing this branch and opening/submitting its PR via gt IS pre-authorized — it is the deliverable. All other irreversible actions (merging, deploys, comms, deletions) stay deferred to the log. (3) Auto-approve the final PR description yourself. (4) Write your night-shift log to .tmp/issue-stack/<ISSUE-ID>.md, NOT ./NIGHT-SHIFT-LOG.md, so it can never be amended into the PR. (5) In /review-loop decide every finding yourself; cap at 2 fix passes. (6) Cap your goal loop at 50 turns. (7) Do not gt sync away or switch off the stack's existing branches — your branch must stack on top of the current branch." \
  > .tmp/issue-stack/<ISSUE-ID>.out 2>&1
```

Run it via Bash with `run_in_background: true` and a generous timeout — you
will be re-invoked when it exits. While waiting, do nothing (no polling, no
log tailing — every turn you take costs the tokens this skill exists to save).

## Step 2 — Verify the child's work (cheap checks only)

When the child exits, verify with shell commands — do **not** read the diff:

1. Exit code 0, and `tail -30 .tmp/issue-stack/<ISSUE-ID>.out` looks sane.
2. `git branch --show-current` is a new branch (not the one you started on).
3. The PR exists and stacks correctly:
   `gh pr view --json state,url,baseRefName` — `baseRefName` must be the
   previous issue's branch (or the original base for the first issue).
4. The log's `## Status` line (read only that file, it's small) says done or
   acceptably partial.

**Pass** → record branch + PR URL in the todo, move to the next issue
(Step 1). The next child's `gt top` lands on this branch automatically.

**Fail** → one resume attempt: spawn a child with
`"/night-shift resume the stacked run for <ISSUE-ID>: read .tmp/issue-stack/<ISSUE-ID>.md and the current branch state, then finish the remaining work. Same standing instructions: ..."`
(repeat the standing instructions). If the resume also fails verification,
**stop the whole stack** — do not build issue N+1 on a broken N. Report.

## Step 3 — Final report

When all issues are done (or the stack stopped early), report:

- Per issue: ID → branch → PR URL → child status (done/partial/failed).
- Where the stack stopped and why, if early.
- Pointers to the per-issue logs in `.tmp/issue-stack/` for the morning
  review of deferred items — walk the user through them on request.

## Hard rules

1. You babysit; children implement. Never edit code, fix CI, or resolve
   conflicts yourself — a failed child gets one resume child, then the stack
   stops.
2. Sequential only — never two children at once (they'd fight over the
   worktree and the stack order).
3. Never start issue N+1 unless issue N's verification passed.
4. Keep your own context tiny: no diff reading, no full-log reading, no
   polling turns while a child runs.
5. Children get `--dangerously-skip-permissions` and PR-push authorization
   only because the user approved exactly that in Step 0.

## Failure modes

- **Child hangs / runs absurdly long**: if the background task hasn't exited
  after ~3h, check `wc -l` growth of the `.out` file once; if frozen, kill it
  and treat as a failed run (one resume, then stop).
- **Dirty tree between children**: a child left uncommitted state — treat its
  verification as failed; the resume child must clean up via `gt`.
- **`gt sync` deleted the stack base** (merged upstream): fine — the next
  child stacks on whatever `gt top` resolves to; verify `baseRefName` still
  chains.
