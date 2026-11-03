---
name: ship-stack
description: >
  Default workflow for every task that changes code, config, or docs in a
  work repository, whether a Linear issue or a free-text request, even when
  the user does not name this skill. Implements the task without asking,
  finishes its PR with finish-pr, implements every follow-up found along the
  way as a Graphite stack on top (each finished with finish-pr), verifies
  the stack is green and mergeable, and reports what was done and every
  decision made so the user can merge. Not for questions, reviews,
  investigations, or work another skill owns.
argument-hint: "<task | linear-issue-link-or-id>"
allowed-tools: Bash(*), Read, Write, Edit
---

# ship-stack

Take one task, plus the follow-ups the work uncovers, to a stack of PRs that
is ready to merge. The user's arguments are the task: a Linear issue id or
URL, or a free-text description. Empty: use the task already established in
the conversation. If there is none, that is the only question you may ask.

## Autonomy contract

Do not ask the user anything and do not wait for the user. Every helper
skill that would ask or wait (implement-issue design approval, finish-pr's
questions about rejecting feedback, deferring work, or changing scope)
falls back to your own decision instead:

- Investigate, pick the option you would recommend, apply it, and log it
  as a decision with the alternatives and why.
- Mark a decision **serious** only when a reasonable reviewer could reject
  the whole approach: a public API or data-format change, a migration, a
  security or money-handling trade-off, dropping a requested behavior, or
  a large scope change. Still decide and keep going; serious decisions are
  listed first in the final report.
- Stop early only for a real blocker that no decision can get past (missing
  credentials, an outage, a red CI you cannot fix). Then report.

Keep a log at `.tmp/ship-stack/<slug>.md` (gitignored): the PR list, each
follow-up and its source, every decision (serious ones marked), dropped
items with reasons, and the final verification evidence.

## 1. Implement the main task

- Linear issue: run the `implement-issue` flow on it, under the autonomy
  contract.
- Free-text task: follow the same flow without the Linear steps: `graphite`
  skill for version control (`gt sync`, then `gt create`), proportionate
  plan and review, local checks, `gt submit`.

While working, log every follow-up you find: out-of-scope bugs, review
findings that do not belong in this PR, TODOs the change exposes, missing
tests, docs, or cleanups. A follow-up must be concrete. Fix in-scope
findings in the main PR instead.

## 2. Finish the main PR

Run `finish-pr` on the main PR, under the autonomy contract. It is done
when Rain Marvin approved the exact published head, CI is green on it,
every thread has a reply and is resolved, and the PR is ready for review.
Log follow-ups from its review rounds.

## 3. Follow-ups as a stack

Triage the log: drop duplicates, items already fixed, and items too vague
to act on, each with a reason. Order the rest by dependency, then smallest
and safest first.

For each follow-up, in order:

1. `gt checkout` the top of the stack and implement it on a new branch with
   `gt create`. One follow-up per PR; group tiny related items only when
   they touch the same code.
2. Use the same proportionate plan, review, and local checks as
   implement-issue. If the main task came from Linear, reference the parent
   issue in the PR. Do not create Linear issues.
3. `gt submit --no-interactive`, assign the author to the created PR, then
   run `finish-pr` on it. Do not start the next follow-up until this PR is
   ready for review.
4. New follow-ups found here join the end of the queue. Stop when what is
   left is only nits or speculation, or would grow scope beyond what the
   original task touched; log those as not done.

If a lower PR changes after a higher one was finished (restack, review
fix), rerun `finish-pr` on every PR whose head moved. Rain Marvin must
approve each PR's exact current head.

## 4. Verify the stack is merge-ready

Do not merge. The user merges. Verify every PR bottom to top on its exact
published head (`gh pr view <n> --json
headRefOid,isDraft,mergeable,mergeStateStatus,reviewDecision` and
`gh pr checks <n>`):

- `headRefOid` equals `git rev-parse <branch>`; nothing unpushed.
- Not a draft; Rain Marvin approved this head.
- Every non-skipped check passes, review checks such as
  `rain-marvin/reviewed` included.
- No conflicts; no unresolved thread; no outstanding change request.

Fix any failure you can (rerun finish-pr, `ci-fix`, `fix-conflicts`) and
re-verify. Report what you cannot fix, such as a required human approval,
as the exact remaining blocker.

## 5. Report

Write the report so the user can decide to merge from it alone:

1. **Serious decisions**, first: each with what you chose, the
   alternatives, why, and which PR it lives in.
2. **The stack**, bottom to top: Graphite link, one line on what it does,
   state (merge-ready, or the exact blocker).
3. **Other decisions**, briefly.
4. **Not done**: dropped or stopped follow-ups with reasons.
5. **How to merge**: the top PR's Graphite link, to merge the whole stack
   from Graphite. Log path.

Merge-ready means green and approved by Rain Marvin, not merged or
deployed.

## Hard rules

1. Never ask the user or wait for them after the task is known. Decide,
   log, and report.
2. Never merge, deploy, or release. The user merges after reading the
   report.
3. Every PR runs finish-pr to completion before the next starts, and again
   whenever its head moves.
4. Version control through the `graphite` skill. Show Graphite PR links.
5. No admin merges, rule bypasses, dismissed reviews, or branch-protection
   changes.
