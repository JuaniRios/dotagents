---
name: finish-pr
description: >-
  Prepare the PR (description, assignee, engineer reviewers, kept in draft),
  address existing human and bot feedback, loop with CodeRabbit and Rain
  Marvin until both approve the exact published head, and only then mark the
  PR ready for review. Use when asked to address review feedback, drive
  CodeRabbit or Rain Marvin, or finish PR review, or when an active
  implementation workflow requires it. Do not trigger for status-only checks.
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

1. **Draft.** The PR stays a draft until section 7. If it is open and not a
   draft, convert it with `gh pr ready --undo <url>` and verify `isDraft`.
2. **Description.** Run pr-description on the PR so it has a real title and
   merge brief, not a placeholder or `WIP`. pr-description preserves
   user-authored content. Run it again before section 7 if later fixes
   changed what the brief claims.
3. **Assignee.** Assign the person who opened the PR: read
   `gh pr view <url> --json author --jq .author.login` and run
   `gh pr edit <url> --add-assignee <login>`. Juan sometimes prepares other
   people's PRs, so never default to the acting user when the PR exists. If
   the branch has no PR yet, it is not pushed: open it through the graphite
   skill first, and assign `JuaniRios`. Remove no other assignee without
   asking.
4. **Reviewers.** Request the engineer roster, minus the PR author:
   `agryaznov` (Alex), `ueco-jb` (Jakub), `rouzwelt` (Rouz), and `findolor`
   (`gh pr edit <url> --add-reviewer <login>,...`). Keep existing
   requests. Bots are not part of this list.
5. Read the PR back and verify title, body, assignee, reviewer requests,
   and draft state. Record them in the checkpoint.

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
Reconcile substantive concerns in CodeRabbit's and Rain Marvin's summaries
with the actual fixes and discussions; neither blindly trust nor silently
discard them.
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
7. Only after that publication check succeeds, resolve every addressed human,
   CodeRabbit, and Rain Marvin thread. Verify resolution; do not rely on
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

## 3. Ensure a full CodeRabbit review

After existing feedback is handled, or immediately if none exists, inspect
CodeRabbit's review history. The handle is `@coderabbitai`.

- Reuse a confirmed completed full-PR review as the baseline.
- If no full review is confirmed, request `@coderabbitai full review` once.
  A prior incremental review alone does not establish a full baseline.
- For every subsequent round, use `@coderabbitai review`, never another
  full review merely because the head changed or the branch was restacked.
- Prefer an automatic review already running for the new push. Allow up to
  three minutes for it to start before requesting an incremental review.
  Do not duplicate a queued or running request.

Record trigger time, head/base SHAs, command, review run, and covered commit.
A request acknowledgement, green check, empty COMMENTED review, or reply
saying a thread is fixed does not prove a code review completed.
Check the completed run and its reviewed commit range. CodeRabbit may
report a clean review only in its updated summary rather than a review body.
"Already reviewed" is sufficient only with matching coverage evidence.

A rebase-only SHA change may reuse coverage only after verifying the
parent-relative diff is unchanged and no conflict resolution or relevant
base change altered its meaning. Otherwise request incremental review.

## 4. Drive Rain Marvin through review and approval

After existing feedback is handled, or immediately if none exists, inspect
Rain Marvin's review history. The handle is `@rain-marvin`.

1. If no Rain Marvin review is queued, running, or confirmed complete for the
   current diff, post `@rain-marvin review` once.
2. Wait for the completed review. An acknowledgement, reaction, status check,
   or command reply does not prove review coverage. Record the trigger time,
   head/base SHAs, completed review, and covered commit or diff range.
3. Ingest every finding through steps 1 and 2: investigate, implement accepted
   changes, verify, publish, reply, and resolve the addressed threads.
4. After fixes are published, use implementation judgment:
   - Request another `@rain-marvin review` when the fixes are substantive,
     touch behavior or contracts, materially change the reviewed diff, or
     leave meaningful uncertainty that another review can resolve.
   - Otherwise post `@rain-marvin approve` and wait for Rain Marvin's approval.
   Rain Marvin's approval of the exact published head is required before
   section 7.
5. Verify approval applies to the exact published head or an unchanged
   parent-relative diff. A command acknowledgement is not approval. If Rain
   Marvin returns findings instead, process them and repeat this section.

Do not duplicate queued or running requests. Poll using the host's wait
mechanism in intervals no longer than 60 seconds. If Rain Marvin is quiet or
stalled, apply the same 20-minute diagnosis and blocker rules as CodeRabbit.
The follow-up review-versus-approval choice is governed by the implementation
judgment above.

## 5. Drive to convergence

After each completed CodeRabbit or Rain Marvin review, ingest all new feedback
through steps 1 and 2. After any new fix, obtain the review coverage required
by sections 3 and 4 and repeat until both bots approve.

### No round cap

Loop until **both** CodeRabbit and Rain Marvin have approved the exact
published head. There is no round budget: ignore caller levels and caps
(light/standard/deep) for this loop. Stop early only on a real blocker or
the no-progress rule below, and then report "blocked", never "ready".
Record each completed CodeRabbit and Rain Marvin run in the checkpoint so a
resumed turn does not re-request coverage it already has.

CodeRabbit usage-based reviews are enabled for this environment. A
`Review rate limited` reply is a failed trigger, not a reason to wait for the
hourly included-review allowance or to stop. Verify that no review is queued or
running, honor an explicit retry-after time when present, otherwise wait 10-30
seconds to avoid duplicating the failed request, then post a fresh
`@coderabbitai review`. Repeat until a review is accepted or a different
concrete blocker appears. Do not change billing or subscription settings.
Do not disable automatic review settings.

Never call an unreviewed final fix converged merely because CI passed.

Assess severity independently:

- Bugs, safety, security, behavior, missing necessary tests, and broken
  external contracts are substantive even if CodeRabbit labels them minor.
- Nits are cosmetic or optional style preferences with no correctness or
  operational effect.

If only CodeRabbit nits remain, the user's standing policy permits stopping
the fix loop: reply that optional polish is left out, resolve those nit
threads, and continue to the approval step below. Nits-only still needs
CodeRabbit's approval on the current head. Do not make another
cosmetic edit that would create an unreviewed terminal delta.
Human requests are not silently dismissed under this nit policy.

Poll using the host's wait mechanism, in intervals no longer than 60 seconds,
and keep the user updated. Honor rate-limit retry times, avoid duplicate
commands, and continue useful work on other PRs while waiting.
Do not change billing settings or bypass access restrictions.

After exact-head coverage is clean and every CodeRabbit thread is resolved,
GitHub can still show an older CodeRabbit `CHANGES_REQUESTED` review. In that
case post `@coderabbitai resolve`, then verify that CodeRabbit approved the
current head and that the PR review decision is no longer blocked. This command
only clears resolved review state; it never substitutes for current-head review
coverage. Apply the same evidence standard to Rain Marvin: its requested
approval must be visible on the current head and never substitutes for review
coverage after a material change.

A quiet or rate-limited service is not convergence. Diagnose a stalled run
after 20 minutes. Retry only when evidence says the previous attempt failed
or retry is allowed. If substantive findings repeat without progress across
three cycles, investigate the cause and ask for the concrete missing
decision instead of blindly editing or retriggering.

Convergence means both bots approved the current head: a CodeRabbit
`APPROVED` review and a Rain Marvin approval, each on the exact published
head (or an unchanged parent-relative diff), with no later push. Any new
push after an approval sends that bot back through the loop.

Persist checkpoints so interrupted work resumes without a new full review.
If permissions, service availability, or a user decision genuinely blocks
progress, report "blocked" with remaining work, never "wrapped up".

## 6. Final verification and handoff

Do not wait for every intermediate remote CI run. Once both bots approve,
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
- Verify accepted findings from humans, CodeRabbit, and Rain Marvin have
  published fixes, replies, and resolved threads, and out-of-diff findings have
  recorded answers. For each resolved thread, read back evidence that its reply
  was publicly published before the resolution; a pending review or local
  reply draft fails this audit.
- Report human approvals separately, including stale approvals. Do not
  manufacture approval or wait indefinitely for another person's review.

## 7. Mark ready for review

Only when every condition holds on the exact published head:

- CodeRabbit and Rain Marvin both approved it (section 5).
- The section 6 audit passed: CI green, no conflicts, every addressed thread
  replied to and resolved, no unhandled substantive feedback.
- Section 0 still holds: current description, the PR opener assigned,
  roster reviewers requested.

Then run `gh pr ready <url>` and read back `isDraft: false`. Re-check the
head SHA immediately before; if it moved, return to the loop. For a stack,
mark PRs ready bottom-up, each only after its own conditions hold. If any
condition fails, leave the PR in draft and report why.

## 8. Report

Report each PR with its link, head, draft/ready state, fixes, CodeRabbit
coverage and approval, Rain Marvin coverage and approval, remaining nits or
decisions, CI, conflicts, and missing human approvals.
"Ready for review" requires both bot approvals on the current head, the
final audit, and a verified `gh pr ready`. It does not mean merged,
deployed, or human-approved.
