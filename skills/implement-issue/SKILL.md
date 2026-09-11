---
name: implement-issue
description: >
  Take a Linear issue from link to finished implementation — skeleton
  Graphite PR, cross-link Linear↔PR, proportionate plan and critique,
  use light checks for low-risk config edits, one independent pass for simple
  changes, or full review loops for complex changes, then submit with final
  CI green. Use when the user wants an issue implemented end to end.
argument-hint: "<issue-link-or-number>"
allowed-tools: Bash(*), Read, Write, Edit
---

# implement-issue

Drive a Linear issue end to end. First read
`~/Github/dotagents/skills/issue-thoroughness.md`. Select light, standard,
or deep from the issue and relevant source before spawning any children.
Load panel-runtime and review-loop only for the deep path.

The user's request is the Linear id or URL. Empty: ask once.

Light and standard work stays with the host except for standard's single
independent reviewer per phase. Deep work may use isolated implementers.

## 1. Read the issue

`linear-cli`: `linear issue view <ID>`. Capture title, why, URL. Inspect the
relevant source and record the thoroughness level before the skeleton or
description steps, so helper skills receive the correct level from the start.

## 2. Skeleton PR

`graphite` skill. `gt sync`, `gt top`, benign change, `gt create
<id>-<kebab-title>`, `gt submit --no-interactive --no-edit-description`.

## 3. Skeleton description

`pr-description` as WIP: Why from the issue (markdown link
`[<ID>](<url>)`), What/How = `WIP`. Auto-approve the skeleton.

## 4. Cross-link

`linear issue link <ID> "$pr_url"`. Assignee `JuaniRios`. Reviewers
`agryaznov` (Alex), `ueco-jb` (Jakub), `rouzwelt` (Rouz), and `findolor`.

## 5. Plan

If `<ID> Implementation Plan` exists, check its scope, level, review evidence,
and freshness against the current source. Reuse an applicable approved plan;
do not repeat its planning pass. Confirm unapproved material decisions, not
every previously approved plan. Reassess depth if the work has changed.

Otherwise write `.tmp/implement-issue/<id>-plan.md`:

- Light: host-written bullets and a direct validation plan; self-check only.
- Standard: host-written short plan and one independent review pass under
  the shared policy. Apply findings and verify corrections.
- Deep: planner per panel-runtime, then critique-loop on the draft. Do not
  additionally launch the separate Plan critics panel. Wait for design
  approval before implementation unless the user already approved it.

Record the level and reason. Light and standard proceed under the user's
implementation request when scope is clear. Ask only for a material choice
or expanded scope, and escalate if investigation changes the risk assessment.

## 6. Implement

Light and standard: implement directly. Deep: use isolated implementers for
concrete independent tasks when useful, with one owner for shared-worktree
mutations. Test the plan's acceptance criteria and keep edits focused.
Stage only the intended files, then amend through Graphite.

## 7. Review and describe

Light: self-review the parent-aware diff and acceptance criteria. No children,
review-loop, or critique-loop.
Standard: one independent reviewer examines the parent-aware diff, relevant
source, tests, and final PR-description draft. Follow the shared one-pass
policy; verify fixes without restarting the broad review.
Deep: run review-loop (current branch, no stack) and resolve material findings.

Use pr-description with the selected issue level. Reuse standard's combined
description review rather than adding a second reviewer. Never let a helper
silently upgrade light work into an independent-review pipeline.

## 8. Verification gate

Every level runs its acceptance checks and mandatory repository checks.
Follow ci before Rust or Nix pushes. For low-risk config or documentation,
use direct schema, parser, reference, formatting, or rendering checks as
applicable; do not invent a full application build unless required.
Batch final local gates and rerun invalidated checks after changes. Deep
review rounds use targeted checks; do not repeatedly wait for full remote CI.

## 9. Feedback and CodeRabbit convergence

1. Submit through Graphite. Inspect existing human and bot feedback at every
   level, and handle it under the shared policy. Light and standard do not
   proactively launch CodeRabbit loops by default.
2. For deep work, explicit CodeRabbit-convergence requests, or substantive
   external feedback needing re-review, run `finish-pr-review` on the exact
   in-scope PR URLs. It addresses existing feedback, ensures a
   full CodeRabbit baseline, and drives incremental reviews until clean or
   nits-only. It owns replies, thread resolution, and final verification.
   Ask only for substantive disagreements, alternatives, or real blockers.
3. Do not separately request CodeRabbit reviews or wait for CI runs started by
   intermediate pushes. Those runs may be cancelled by later pushes.

## 10. Final handoff gate

At every level, verify current mergeability and required CI on the published
head. Resolve conflicts, fix failed checks, and reassess review coverage for
meaningful changes. If finish-pr-review ran, reuse its exact-head evidence;
do not launch another pipeline to duplicate its final gate.
If Graphite skipped CI, use the repository's permitted local equivalent
(such as `nix run .#ci`) and disclose it. Do not report skipped optional
CodeRabbit or multi-model review as converged.

## 11. Report

Issue URL, PR URL, level and reason, actual review coverage, CI, one-line
what changed, and plan path. Distinguish implementation from deployment.

## Hard rules

1. Version control via `gt`.
2. Deep designs need approval; clear light and standard work uses the user's
   implementation authority. Reuse approved plans without redundant prompts.
3. Linear ↔ PR linked both ways.
4. Only deep work requires panels. Follow panel-runtime there and never
   impersonate a dropped model or silently claim missing review coverage.
5. Don't declare done until CI for this HEAD is green (or local full
   CI when Graphite skipped it).
6. Required checks apply at every level. Batch verification and wait for
   final remote CI after the selected review work, not after each edit.
