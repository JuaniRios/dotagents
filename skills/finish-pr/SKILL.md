---
name: finish-pr
description: >-
  Prepare the PR (description, assignee, code-owner reviewers, kept in draft),
  address existing human and bot feedback, loop with Rain Marvin until it
  approves the exact published head, and only then mark the PR ready for
  review. A Rain Marvin approval with only minor comments ends the fix loop
  unless a comment is underrated. Use when asked to address review
  feedback, drive Rain Marvin, or finish PR review, when an
  active implementation workflow requires it, and always before reporting a
  PR you opened or changed as done. Do not trigger for status-only checks.
---

# Finish PR

Own the review work through verified, published fixes and a final audit.
Do not stop after posting a review request or pushing the last fix unless
a real blocker prevents completion. Report that state
as incomplete, not wrapped up.

## Scope and authority

- Explicit PR URLs or a previously agreed PR list define the scope.
  Otherwise use the current PR. `stack` includes its connected open stack;
  `current` includes the current PR and descendants.
- Announce the target PRs. Discover stack order from base/head links.
  Do not include unrelated open PRs or assume the trunk is named master.
- Invocation authorizes normal in-scope fixes, tests, commits, restacks,
  pushes, PR descriptions, assignee and reviewer changes, draft/ready
  toggles, review requests, factual replies, and resolution of addressed
  human and bot threads. Do not request approval for each normal step.
- Ask before rejecting substantive feedback, materially changing the
  requested solution, deferring substantive work, or expanding scope.
  Investigate first and bring evidence, a recommendation, and one clear
  question. Ordinary implementation details do not need a decision.
- Do not merge, deploy, release, change branch protection, dismiss human
  reviews, enable paid review capacity, or create issues without authority.
- Follow repository instructions and the graphite skill for version control.
  Use write-as-me for published replies. Preserve unrelated local changes.
  Stage explicit paths, never all dirty files.

## 0. Prepare the PR

Do this for every in-scope PR before touching feedback.

1. **Draft.** The PR stays a draft until section 6. If it is open and not a
   draft, convert it with `gh pr ready --undo <url>` and verify `isDraft`.
2. **Description.** Run pr-description on the PR so it has a real title and
   merge brief, not a placeholder or `WIP`. pr-description preserves
   user-authored content. Run it again before section 6 if later fixes
   changed what the brief claims. Only pr-description writes the body:
   never patch or append to it by hand with `gh pr edit --body-file` after
   a review round, and never follow a section list from a caller's prompt
   in place of the merge brief.
3. **Assignee.** Assign the person who opened the PR: read
   `gh pr view <url> --json author --jq .author.login` and run
   `gh pr edit <url> --add-assignee <login>`. Juan sometimes prepares other
   people's PRs, so never default to the acting user when the PR exists. If
   the branch has no PR yet, it is not pushed: open it through the graphite
   skill first, and assign `JuaniRios`. Remove no other assignee without
   asking.
4. **Reviewers.** Request the code owners of the changed files, minus the
   PR author and bots. Keep existing requests.
   - **Code owners.** Read the first file that exists among
     `.github/CODEOWNERS`, `CODEOWNERS`, and `docs/CODEOWNERS` on the PR
     base branch (`gh api 'repos/<owner>/<repo>/contents/<path>?ref=<base>'
     --jq .content | base64 -d`). List the changed files with
     `gh pr view <url> --json files --jq '.files[].path'`. For each file,
     the last matching pattern wins, as on GitHub; a matching line with no
     owners means that file has no owner. Request each owner: a user as
     `<login>`, a team `@org/team` as `org/team`.
   - **Pseudo owners.** If there is no CODEOWNERS file, or a changed file
     has no owner, also request the repository's pseudo owners from
     `~/Github/dotagents-private/data/pr-reviewers/<owner>/<repo>.json`.
     Run `~/Github/dotagents-private/scripts/data-sync.sh pull` before you
     read it. The file holds
     `{"owners": ["<login>", ...], "source": "contributions" | "manual",
     "updated": "<YYYY-MM-DD>", "evidence": "<one line>"}`. Juan may edit
     it by hand (`"source": "manual"`); never overwrite a manual file.
   - **No file yet.** Derive the pseudo owners from contributions to the
     default branch over the last 180 days: count non-merge commits per
     author login
     (`gh api 'repos/<owner>/<repo>/commits?since=<date>&per_page=100'
     --paginate --jq '.[] | select(.parents | length == 1) |
     .author.login'`), and add one per review given on merged PRs in that
     window. Drop bots (`[bot]` logins, `rain-marvin`, `coderabbitai`) and
     null logins. Keep the top 3 people with at least 3 contributions; if
     fewer than 2 people qualify, recount over the full history. Write
     the file with `"source": "contributions"` and evidence such as
     `commits+reviews since 2026-04-28: a=41, b=17, c=6`, then run
     `data-sync.sh save "pr-reviewers: <owner>/<repo>"
     data/pr-reviewers/<owner>/<repo>.json`.
   - If GitHub rejects a login (no repository access), drop it from the
     request. If it came from a `contributions` file, remove it from that
     file and save. If no reviewer remains after removing the author,
     report it rather than inventing one.
5. Read the PR back and verify title, body, assignee, reviewer requests,
   and draft state. Record them in the checkpoint.
6. **Body gate.** The body fails if it has a `## Why`, `## How`,
   `## What`, `## Implementation`, or `## Rollout steps` heading, a section
   with more than 3 bullets, or more than 500 words of prose (count
   with `gh pr view <url> --json body --jq .body | sed 's/(http[^)]*)//g' |
   wc -w`, and skip any CodeRabbit block). On a fail, rerun pr-description
   to regenerate the brief, then check again. A long runbook belongs in the
   Linear issue or the repository docs, linked from Rollout.

## 1. Inventory existing feedback

Record each PR's head, base, draft state, review status, and checks.
Use durable checkpoints under
`~/Github/dotagents/data/finish-pr/<run-id>/`.

Fetch and paginate all of:

- Review threads, including every thread's reply pages.
- Top-level issue comments.
- Pull-review bodies, including out-of-diff findings.

Keep unresolved threads even when outdated. Recheck their current source.
Use resolved conversations as context, not a new work queue, unless later
feedback reopens the concern or current evidence shows it remains unfixed.

Split review bodies into individual findings. Deduplicate repeated findings
across threads, summaries, and replies. Retain source URLs and thread IDs.
Reconcile substantive concerns in bot summaries (Rain Marvin's, and
CodeRabbit's on older PRs) with the actual fixes and discussions; neither
blindly trust nor silently discard them.
Ignore praise, generic walkthroughs, and optional bot promotion checklists.

Read current code and relevant tests before deciding. Classify each item:

- Accepted: implement and verify automatically.
- Already addressed: verify the published fix, reply, and resolve.
- Factual question: investigate, answer, and resolve when fully answered.
- Decision needed: rejection, material alternative, deferral, conflicting
  requirements, or uncertainty that investigation cannot settle.

Do independent accepted work while collecting decision-needed items.
Never resolve a pending decision or present an unverified fix as complete.

## 2. Fix, publish, reply, and resolve

Work bottom-up through dependencies. Batch related fixes per PR.
Parallel read-only analysis is fine; shared-worktree mutations are serial.

1. Revalidate each finding against the current branch.
2. Make focused fixes and add meaningful regression coverage where needed.
3. Run affected tests and required local gates. Follow ci before Rust or
   Nix pushes; reuse unchanged gate results where that skill permits.
4. Amend, restack, and submit through Graphite. Resolve
   mechanical conflicts using fix-conflicts; ask only when resolution requires
   a product decision.
5. After verifying the remote head, reply with the published commit SHA,
   what changed, and what verification actually passed.
6. Verify the reply is publicly visible in the target conversation and is not
   trapped in a pending review. A drafted or pending reply does not count as
   posted. Prefer the host API operation that publishes a single reply
   immediately; after sending, read the thread back and verify the reply's
   author and body. On GitHub, also verify the acting user's pending-review
   count is zero before resolving any thread.
7. Only after that publication check succeeds, resolve every addressed human
   and bot thread. Verify resolution; do not rely on
   automatic bot resolution. If publishing or read-back verification fails,
   leave the thread unresolved and report the failure. Never resolve first and
   publish later.

For out-of-diff findings, post a concise top-level reply linking the finding.
There is no thread to resolve; record the disposition in the checkpoint.
Avoid duplicate replies. After an ambiguous send timeout, read back before
retrying. A failed push means fixes remain local and are not yet addressed
on the PR.

User-approved alternatives or rejections follow the same reply-and-resolve
path. Do not claim a deferred issue exists before it has been created.

## CodeRabbit is not used

CodeRabbit is not installed or required in any org. Do not post
`@coderabbitai` commands, request its review, or wait for it. CodeRabbit
comments already on an older PR are still feedback: handle them through
sections 1 and 2 like any other review comment.

## 3. Drive Rain Marvin through review and approval

After existing feedback is handled, or immediately if none exists, inspect
Rain Marvin's review history. The handle is `@rain-marvin`.

1. If no Rain Marvin review is queued, running, or confirmed complete for the
   current diff, post `@rain-marvin review` once.
2. Wait for the completed review. An acknowledgement, reaction, status check,
   or command reply does not prove review coverage. Record the trigger time,
   head/base SHAs, completed review, and covered commit or diff range.
3. If the completed review approves (verdict Approve in the review or the
   `rain-marvin/reviewed` check) and its remaining comments are all minor or
   nits, apply the approval rule in section 4 instead of fixing them.
   Otherwise ingest every finding through steps 1 and 2: investigate,
   implement accepted changes, verify, publish, reply, and resolve the
   addressed threads.
4. After fixes are published, use implementation judgment:
   - Request another `@rain-marvin review` when the fixes are substantive,
     touch behavior or contracts, materially change the reviewed diff, or
     leave meaningful uncertainty that another review can resolve.
   - Otherwise post `@rain-marvin approve` and wait for Rain Marvin's approval.
   Rain Marvin's approval of the exact published head is required before
   section 6.
5. Verify approval applies to the exact published head or an unchanged
   parent-relative diff. A command acknowledgement is not approval. If Rain
   Marvin returns findings without approving, process them and repeat this
   section.

Do not duplicate queued or running requests. Poll using the host's wait
mechanism in intervals no longer than 60 seconds. If Rain Marvin is quiet or
stalled, apply the stall rules in section 4. The follow-up
review-versus-approval choice is governed by the implementation judgment
above.

## 4. Drive to convergence

After each completed Rain Marvin review, ingest all new feedback through
steps 1 and 2. After any new fix, obtain the review coverage required by
section 3 and repeat until Rain Marvin approves.

### No round cap

Loop until Rain Marvin has approved the exact published head. There is no
round budget: ignore caller levels and caps (light/standard/deep) for this
loop. Stop early only on a real blocker or the no-progress rule below, and
then report "blocked", never "ready". Record each completed Rain Marvin run
in the checkpoint so a resumed turn does not re-request coverage it already
has.

Never call an unreviewed final fix converged merely because CI passed.

### An approval with minor comments ends the loop

Assess severity independently, but let Rain Marvin's approval end the loop:

- A comment is underrated when it describes funds or safety risk, broken
  behavior on a money path, a broken external contract, or a missing test for
  a critical path, whatever label the bot gave it.
- Anything else a bot labels minor or nit stays minor: work that only runs
  later than needed, rare timing edges with no funds risk, style, and
  optional polish.

When Rain Marvin approves the current head (its Approve verdict) and its
remaining comments are all minor or nits, the fix loop ends. Reply to each
comment with its disposition, resolve the threads, and go to section 5. Do
not push fixes for those comments: every push needs a new review round. List
comments worth tracking in the report as candidate follow-ups, and create an
issue only with the user's authority. Fix before ready only a comment that
independent assessment shows is underrated, and say why in the reply.
Human requests are never dismissed under this rule.

Before any approval, a review with only nits still permits stopping fixes:
reply that optional polish is left out, resolve those threads, and request
approval. Do not make another cosmetic edit that would create an unreviewed
terminal delta.

Poll using the host's wait mechanism, in intervals no longer than 60 seconds,
and keep the user updated. Honor rate-limit retry times, avoid duplicate
commands, and continue useful work on other PRs while waiting.
Do not change billing settings or bypass access restrictions.

Rain Marvin's requested approval must be visible on the current head and
never substitutes for review coverage after a material change.

A quiet or rate-limited service is not convergence. Diagnose a stalled run
after 20 minutes. Retry only when evidence says the previous attempt failed
or retry is allowed. If substantive findings repeat without progress across
three cycles, investigate the cause and ask for the concrete missing
decision instead of blindly editing or retriggering.

Convergence means Rain Marvin approved the current head (or an unchanged
parent-relative diff), with no later push. Any new push after an approval
sends the PR back through the loop.

Persist checkpoints so interrupted work resumes without a new full review.
If permissions, service availability, or a user decision genuinely blocks
progress, report "blocked" with remaining work, never "wrapped up".

## 5. Final verification and handoff

Do not wait for every intermediate remote CI run. Once Rain Marvin approves,
perform the final audit:

- Check current trunk/base compatibility and resolve actual conflicts.
- Run required final verification and wait for CI on the exact published
  head. Use ci-fix for failures; a repair push returns the PR to the loop
  for fresh approvals.
- Treat Graphite's wait-for-parent check as a stack dependency, not a CI
  failure. If CI was skipped, use an explicitly permitted local equivalent
  and disclose it. Missing evidence is not green CI.
- Refresh all feedback sources after final checks. New substantive feedback
  or uncovered changes return to the loop.
- Verify accepted findings from humans and bots have published fixes,
  replies, and resolved threads, and out-of-diff findings have recorded
  answers. For each resolved thread, read back evidence that its reply was
  publicly published before the resolution; a pending review or local reply
  draft fails this audit.
- Report human approvals separately, including stale approvals. Do not
  manufacture approval or wait indefinitely for another person's review.

## 6. Mark ready for review

Only when every condition holds on the exact published head:

- Rain Marvin approved it (section 4).
- The section 5 audit passed: CI green, no conflicts, every addressed thread
  replied to and resolved, no unhandled substantive feedback.
- Section 0 still holds: current description that passes the body gate,
  the PR opener assigned, code owners (or pseudo owners) requested.

Then run `gh pr ready <url>` and read back `isDraft: false`. Re-check the
head SHA immediately before; if it moved, return to the loop. For a stack,
mark PRs ready bottom-up, each only after its own conditions hold. If any
condition fails, leave the PR in draft and report why.

## 7. Report

Report each PR with its link, head, draft/ready state, fixes, Rain Marvin
coverage and approval, remaining nits or decisions, CI, conflicts, and
missing human approvals.
"Ready for review" requires Rain Marvin's approval on the current head, the
final audit, and a verified `gh pr ready`. It does not mean merged,
deployed, or human-approved.
