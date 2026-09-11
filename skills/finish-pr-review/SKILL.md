---
name: finish-pr-review
description: >-
  Address existing human and bot feedback, then drive CodeRabbit until the
  latest PR changes have no substantive findings or an explicit review budget
  is reached. Use when asked to address
  review feedback, drive CodeRabbit, or finish PR review, or when an active
  implementation workflow requires it. Do not trigger for status-only checks.
---

# Finish PR review

Own the review work through verified, published fixes and a final audit.
Do not stop after posting a review request or pushing the last fix unless
an explicit round cap or real blocker prevents completion. Report that state
as incomplete, not wrapped up.

## Scope and authority

- Explicit PR URLs or a previously agreed PR list define the scope.
  Otherwise use the current PR. `stack` includes its connected open stack;
  `current` includes the current PR and descendants.
- Announce the target PRs. Discover stack order from base/head links.
  Do not include unrelated open PRs or assume the trunk is named master.
- Invocation authorizes normal in-scope fixes, tests, commits, restacks,
  pushes, review requests, factual replies, and resolution of addressed
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

## 1. Inventory existing feedback

Record each PR's head, base, draft state, review status, and checks.
Use durable checkpoints under
`~/Github/dotagents/data/finish-pr-review/<run-id>/`.

Fetch and paginate all of:

- Review threads, including every thread's reply pages.
- Top-level issue comments.
- Pull-review bodies, including out-of-diff findings.

Keep unresolved threads even when outdated. Recheck their current source.
Use resolved conversations as context, not a new work queue, unless later
feedback reopens the concern or current evidence shows it remains unfixed.

Split review bodies into individual findings. Deduplicate repeated findings
across threads, summaries, and replies. Retain source URLs and thread IDs.
Reconcile substantive concerns in CodeRabbit's risk summary with the actual
fixes and discussions; neither blindly trust nor silently discard them.
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
4. Amend, restack, and submit through Graphite. Resolve mechanical conflicts
   using fix-conflicts; ask only when resolution requires a product decision.
5. After verifying the remote head, reply with the published commit SHA,
   what changed, and what verification actually passed.
6. Resolve every addressed human and CodeRabbit thread after replying.
   Verify resolution; do not rely on automatic bot resolution.

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

## 4. Drive to convergence

After each completed review, ingest all new feedback through steps 1 and 2.
After any new fix, obtain review coverage for that change and repeat while
the round budget permits.

### Round budget

Record the caller's level and cap per PR before requesting reviews. The
issue workflow supplies light = 2 completed rounds, standard/medium = 3,
deep = no fixed cap. Standalone use is uncapped unless the user supplies a
budget. An explicit instruction to continue until converged overrides a
default cap; do not infer that override from an ordinary skill invocation.

Count each distinct completed CodeRabbit code-review run consumed during
this workflow once, whether automatic or manually requested. The initial
full review counts if newly run; a historical baseline reused at entry does
not consume a round. Acknowledgements, failed attempts, rate-limit replies,
and thread-only replies are not completed rounds. Persist counters across
restarts, restacks, and resumed turns; do not reset them to bypass a cap.

At the cap, process the last review's accepted findings: fix, verify, publish,
reply, and resolve addressed threads. Do not request another review. Consume
any already-arrived automatic coverage without retriggering, but do not
initiate another fix/re-review cycle past the budget. Unhandled new findings
remain open and are reported. Do not disable automatic review settings.

Run final checks on published fixes, then report `capped, not converged` if
any substantive feedback or uncovered delta remains. Include the exact head,
last covered head, remaining work, and ask whether to extend the budget.
If the covered result is already clean or nits-only, report that outcome.
Never call an unreviewed final fix converged merely because CI passed.

Without a cap, continue while substantive fixes or verification make progress.

Assess severity independently:

- Bugs, safety, security, behavior, missing necessary tests, and broken
  external contracts are substantive even if CodeRabbit labels them minor.
- Nits are cosmetic or optional style preferences with no correctness or
  operational effect.

If only CodeRabbit nits remain, the user's standing policy permits stopping
the loop: reply that optional polish is left out, resolve those nit threads,
and report "converged with nits", not a clean review. Do not make another
cosmetic edit that would create an unreviewed terminal delta.
Human requests are not silently dismissed under this nit policy.

Poll using the host's wait mechanism, in intervals no longer than 60 seconds,
and keep the user updated. Honor rate-limit retry times, avoid duplicate
commands, and continue useful work on other PRs while waiting.
Do not change billing settings or bypass access restrictions.

A quiet or rate-limited service is not convergence. Diagnose a stalled run
after 20 minutes. Retry only when evidence says the previous attempt failed
or retry is allowed. If substantive findings repeat without progress across
three cycles, investigate the cause and ask for the concrete missing
decision instead of blindly editing or retriggering.

Persist checkpoints so interrupted work resumes without a new full review.
If permissions, service availability, or a user decision genuinely blocks
progress, report "blocked" with remaining work, never "wrapped up".

## 5. Final verification and handoff

Do not wait for every intermediate remote CI run. Once review converges or
reaches its cap, perform the final audit:

- Check current trunk/base compatibility and resolve actual conflicts.
- Run required final verification and wait for CI on the exact published
  head. Use ci-fix for failures and re-review substantive repair changes
  within the budget; uncovered repairs after the cap remain incomplete.
- Treat Graphite's wait-for-parent check as a stack dependency, not a CI
  failure. If CI was skipped, use an explicitly permitted local equivalent
  and disclose it. Missing evidence is not green CI.
- Refresh all feedback sources after final checks. New substantive feedback
  or uncovered changes return to the loop if budget remains; otherwise
  include them in the capped handoff without claiming completion.
- Verify accepted findings have published fixes, replies, and resolved
  threads, and out-of-diff findings have recorded answers.
- Report human approvals separately, including stale approvals. Do not
  manufacture approval or wait indefinitely for another person's review.

Report each PR with its link, head, fixes, CodeRabbit coverage and outcome,
remaining nits or decisions, CI, conflicts, and missing human approvals.
"Review work wrapped up" requires clean or nits-only review coverage,
verified changes, no unhandled substantive feedback, and no unresolved
conflicts. It does not mean merged, deployed, or human-approved.
