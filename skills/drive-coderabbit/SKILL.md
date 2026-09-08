---
name: drive-coderabbit
allowed-tools: Bash(gh:*), Bash(gt:*), Bash(git:*), Bash(jq:*), Bash(python3:*), Bash(date:*), Bash(mktemp:*), Bash(rm:*), Bash(test:*), Bash(cat:*), Bash(sleep:*), Bash(seq:*), Bash(cargo:*), Bash(grep:*), Bash(wc:*), Read, Edit, Write, Grep, Glob
description: Drive bounded CodeRabbit convergence across an entire Graphite stack in parallel. Use only when the user explicitly asks to run or drive CodeRabbit across the stack, or an active implementation workflow requires it. Uses one full first review, automatic or regular incremental follow-ups, batches fixes, and never waits for intermediate CI.
argument-hint: [current]
---

Trigger an initial CodeRabbit review on every PR in the stack, wait for all of
them concurrently, then autonomously apply findings and run at most two lean
incremental follow-up rounds.
This is the "I just pushed a stack, get CodeRabbit's pass folded in without
me babysitting it" button.

**Scope (default whole stack):** every branch from trunk to the top of the
current stack that has an open PR. Pass `current` to limit to the current
branch and everything stacked above it.

**Why two phases.** Graphite mutates one shared worktree, so the git work
(checkout, amend, restack) MUST be serial — concurrent `gt modify`/`gt ss`
corrupts the stack. The slow part is waiting on CodeRabbit (minutes per PR,
plus rate-limit waits of tens of minutes) and analyzing findings; that fans
out. So Phase 1 fans out the wait+analysis (no git mutation), Phase 2
serializes the fast git apply. This runs **autonomous, no prompts mid-run** —
you opted into letting it fix, amend, and restack on its own.

**CI boundary.** This skill never runs or waits for full CI. It uses compile
and affected-test gates for fixes. GitHub CI triggered by an intermediate push
may run or be cancelled in the background; the calling workflow owns the one
final CI wait after convergence.

**The handle is `@coderabbitai`** (bot login `coderabbitai[bot]`). A comment
addressed to `@coderabbit` does NOT fire the bot. Use `@coderabbitai full
review` only when the PR has no prior completed CodeRabbit review; use
`@coderabbitai review` for every later round.

**Bound:** one initial round plus at most two follow-up rounds. A round with no
new actionable findings converges that PR. If the last allowed round finds
valid issues, fix and resolve them but do not request a fourth review; report
that terminal delta explicitly. Never turn probabilistic nit discovery into
an unbounded loop.

Follow these steps precisely.

## 1. Enumerate the stack's PRs

Reconstruct the stack from base→head linkage (deterministic JSON, no `gt log`
parsing). List your open PRs and chain them from trunk upward:

```bash
gh pr list --author @me --state open \
  --json number,title,url,headRefName,baseRefName,isDraft
```

Build the ordered chain: start from the PR whose `baseRefName` is trunk
(`master`), then follow each PR whose base is the previous PR's head, up to the
top. This gives **bottom-up order**, which Phase 2 relies on.

- Default: keep the whole chain.
- `current` arg: keep only the current branch (`git branch --show-current`)
  and PRs stacked above it.

If no open PR matches the current stack, stop and tell the user. Print the
ordered list of PRs you're about to drive.

## 2. Review round — fan out one background agent per PR

Launch one isolated child per PR in a single parallel batch so they
run concurrently. Each child is fully self-contained (it does NOT
share your context). Give each this prompt,
substituting the PR number and branch:

> You are driving CodeRabbit on PR #<N> (branch `<branch>`) of this repo. Do
> NOT check out, edit, commit, or restack anything — you only post a comment,
> wait, and produce an analysis. All git reads use `git show <branch>:<path>`.
>
> **1. Trigger.** On the initial round, check whether CodeRabbit has already
> completed any review on this PR, choose the command once, then record the
> trigger time and post it:
> ```bash
> PRIOR_REVIEWS=$(gh api repos/{owner}/{repo}/pulls/<N>/reviews --paginate --jq \
>   '[.[] | select(.user.login=="coderabbitai[bot]")
>         | select(.body | contains("Actionable comments posted:"))] | length')
> if [ "$PRIOR_REVIEWS" -eq 0 ]; then
>   REVIEW_COMMAND='@coderabbitai full review'
> else
>   REVIEW_COMMAND='@coderabbitai review'
> fi
> TRIGGER_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
> gh pr comment <N> --body "$REVIEW_COMMAND"
> ```
>
> On a follow-up round, first wait up to 3 minutes for the automatic review
> caused by the preceding push. If a completed review newer than that push
> appears, consume it without posting a command. Otherwise record a new
> trigger time and post `@coderabbitai review`. Never use `full review` on a
> follow-up round.
>
> **2. Wait for the review.** Poll every 60s (cap 20 min for the round). On
> each poll check two things, only counting
> activity with timestamp > `$TRIGGER_ISO`:
>
> - **Done:** a review by `coderabbitai[bot]` whose body contains
>   `Actionable comments posted:`:
>   ```bash
>   gh api repos/{owner}/{repo}/pulls/<N>/reviews --paginate --jq \
>     '[.[] | select(.user.login=="coderabbitai[bot]")
>           | select(.submitted_at > "'"$TRIGGER_ISO"'")
>           | select(.body | contains("Actionable comments posted:"))] | length'
>   ```
>   `>= 1` means the review landed. (`Actionable comments posted: 0` still
>   counts as done — nothing to fix.)
> - **Rate limited:** an issue comment OR review body by `coderabbitai[bot]`
>   after the trigger containing `Review rate limited`, `Review limit
>   reached`, `Rate limit exceeded`, `included review limit`, or `before
>   requesting another review`:
>   ```bash
>   gh api repos/{owner}/{repo}/issues/<N>/comments --paginate --jq \
>     '.[] | select(.user.login=="coderabbitai[bot]")
>          | select(.created_at > "'"$TRIGGER_ISO"'") | .body'
>   ```
>   If the message says usage-based billing will continue the review, keep
>   polling. Otherwise parse the refill time and return `status:
>   "rate_limited"` with that time in `notes`; do not sleep for an hour or
>   repost the command. The controller may retry this PR once later if its
>   refill becomes available while useful work on other PRs is still running.
>
> If neither appears within the cap, return `status: "timeout"`.
>
> **3. Fetch and triage findings.** Once done, fetch the feedback exactly the
> way the `/feedback-review` command does — read
> `~/Github/dotagents/skills/feedback-review/SKILL.md` and follow its
> steps 2–4: unresolved, non-outdated review threads via the paginated GraphQL
> query, PLUS issue comments and pull review bodies (for out-of-diff
> findings). Filter to actionable items only. For each, read the referenced
> source with `git show <branch>:<path>` and form an honest opinion
> (`agree` / `partially agree` / `disagree`) with severity and effort — do not
> parrot CodeRabbit.
>
> **4. Return a fix plan** as JSON (this text IS your return value):
> ```json
> {
>   "pr": <N>, "branch": "<branch>", "status": "reviewed|no_actionable|rate_limited|timeout|error",
>   "rate_limit_retries": <int>,
>   "fixes":   [{"file":"...","locator":"fn/line","finding":"...","severity":"high","change":"precise old->new or surgical instruction"}],
>   "replies": [{"file":"...","finding":"...","reason":"why disagree","comment_url":"..."}],
>   "defers":  [{"finding":"...","reason":"large/out-of-scope","comment_url":"..."}],
>   "notes": "anything the human should know"
> }
> ```
> `fixes` = findings you `agree` with (surgical). `replies` = `disagree`.
> `defers` = `partially agree` + large/out-of-scope. Do NOT post replies,
> create issues, or touch git — that's the main session's job.

Collect every agent's JSON as they finish.

## 3. Phase 2 — apply fixes serially, bottom-up

Record the current branch so you can return to it. Then for each PR **in
bottom-up stack order** that has a non-empty `fixes` list:

1. `gt co <branch>`
2. For each fix, in severity order: read the file, **verify the finding is
   still applicable** (code may differ from the agent's read), apply a surgical
   `Edit`. Keep changes minimal — no scope creep.
3. Fast-verify with the owning package's compile gate and the affected tests.
   Never run or wait for full CI inside a CodeRabbit round. If a targeted gate
   breaks, fix it before moving on.
4. `gt modify -a` to amend this branch's commit.

If a `gt modify -a` triggers an upstack restack **conflict**, stop, return to a
clean state if possible, and tell the user to run `/fix-conflicts` — do NOT
guess at conflict resolution.

If the round changed any branch, restack and submit the whole stack once:

```bash
gt ss
```

Then return to the original branch (`gt co <original>`). Reply to each fixed
thread with the fix and verification, and resolve it if CodeRabbit did not
auto-resolve it after the push.

## 4. Convergence controller

Track rounds per PR, not globally:

1. A PR with `no_actionable` converges immediately.
2. After a round that pushed fixes, start a follow-up only for PRs whose diff
   changed. Prefer the automatic review from that push; request regular
   `review` only after the 3-minute grace period.
3. Re-run steps 2–3 with a lean child prompt containing the prior findings so
   already-fixed or dismissed items are not rediscovered as new work.
4. Stop each PR on its first clean follow-up or after two follow-ups. If the
   last allowed round finds valid issues, apply, verify, reply, and resolve
   them, then stop without requesting another review. Report this terminal
   unreviewed delta explicitly.
5. Run a final paginated thread audit. Every accepted/replied-to thread must be
   resolved. Do not launch or wait for CI; return control to the caller for its
   final latest-trunk CI gate.

## 5. Report

Print one consolidated summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
drive-coderabbit — <K> PRs driven
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PR #12 rai-1150  reviewed   fixed 3, deferred 1, skipped 1  (1 rate-limit retry)
PR #13 rai-1151  no_actionable
PR #14 rai-1152  reviewed   fixed 2                          → amended + restacked
PR #15 rai-1160  timeout    CodeRabbit never completed — re-run later

Pushed: gt ss restacked the stack. CodeRabbit auto-resolves its own
resolved suggestions on push.

Needs your call (not auto-actioned):
  Replies to post:  PR #12 #1 (disagree: extract helper) ...
  Defer to issue:   PR #12 #4 (large refactor) ...
```

`replies` and `defers` are **report-only** — posting GitHub replies and
creating Linear issues are outward actions, so surface them here for the user
to action (e.g. via `/feedback-review` on that one PR) rather than doing them
unprompted. Only code fixes + amend + restack are autonomous.

## Hard rules

1. Use the correct `@coderabbitai` handle -- never `@coderabbit`. Post
   `@coderabbitai full review` only for a PR with no completed CodeRabbit
   review; post `@coderabbitai review` for all subsequent rounds.
2. Phase 1 agents NEVER mutate git (no checkout/edit/commit/restack) — they
   read via `git show <branch>:<path>` and return a plan. Only the main
   session mutates git, and only in Phase 2.
3. Git mutation is strictly serial and bottom-up. Never parallelize
   `gt modify`/`gt ss` — it corrupts the stack.
4. Only count CodeRabbit activity with a timestamp after the trigger — never
   mistake a stale prior review for the new one.
5. Verify each finding is still applicable against the checked-out code before
   editing. Keep fixes surgical.
6. Reply to and resolve threads whose fixes were applied. Disagreement and
   deferral replies remain report-only; never create Linear issues unprompted.
7. On a restack conflict, stop and hand off to `/fix-conflicts`. Do not guess.
8. Never run or wait for full CI. The caller owns pre-CodeRabbit and final CI
   gates.
9. Maximum three rounds per PR: one initial plus two follow-ups.

## Failure modes

- **No open PRs in the stack:** Stop and tell the user.
- **CodeRabbit never completes (timeout):** Mark that PR `timeout`, skip its
  fixes, keep driving the rest, surface it in the report.
- **Rate limited without usage-based continuation:** Return `rate_limited`
  with the refill time. Retry once only if capacity returns while other useful
  work is still running; never hold the whole workflow for an hourly reset.
- **`cargo check` fails after a fix:** Fix the breakage before `gt modify`.
  Never amend broken code.
- **Restack conflict:** Stop, report which branch, hand to `/fix-conflicts`.
- **An agent returns `error`:** Surface its `notes`, skip its fixes, continue.
