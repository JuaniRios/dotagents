---
name: implement-issue
description: >
  Take a Linear issue from link to finished implementation — skeleton
  Graphite PR, cross-link Linear↔PR, proportionate plan and critique,
  implement via a closing child, converge multi-model and CodeRabbit
  reviews, then submit with final CI green. Use when the user wants an
  issue implemented end to end.
argument-hint: "<issue-link-or-number>"
allowed-tools: Bash(*), Read, Write, Edit
---

# implement-issue

Drive a Linear issue end to end. Read
`~/Github/dotagents/skills/panel-runtime.md` for planner/critics and
`~/Github/dotagents/skills/review-loop/SKILL.md` for the review.

The user's request is the Linear id or URL. Empty: ask once.

Heavy work runs in isolated children that close. The host keeps glue
and checkpoints.

## 1. Read the issue

`linear-cli`: `linear issue view <ID>`. Capture title, why, URL.

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

If a Linear document titled `<ID> Implementation Plan` exists, use it
(confirm with the user) and skip machine planning.

Otherwise, first classify the change:

- **Trivial fast path**: one obvious, low-risk edit such as removing or
  updating an existing config or documentation entry. It must change no logic,
  schema, secrets, migration, dependency, public contract, or specified
  behavior, and its verification must be direct. The host writes a concise
  plan to `.tmp/implement-issue/<id>-plan.md`; skip the planner, critics, and a
  separate approval checkpoint because the user's implementation request
  already authorizes this plan. If scope expands or investigation finds hidden
  coupling, leave the fast path before editing.
- **Standard path**: every other change. Per panel-runtime **Plan critics**:

  - Planner: fable 5.1 if the Claude harness is reachable, else the host
    model. Write `.tmp/implement-issue/<id>-plan.md`.
  - Critics in parallel: opus 5, sol 5.6, grok 4.6. Label the run
    `claude-host` or `portable`.
  - Incorporate critique. Wait for user approval before implementing.

## 6. Implement

One implementer child (host / cheap same-host model). Surgical edits,
tests the plan names, scoped checks. Comment discipline: Rust carries
intent; comments only for non-obvious rationale. Then `gt modify -a`.

Large plans (>~6 tasks): two implementer children by task group.

## 7. Review and describe

For the trivial fast path: self-review the parent-aware diff, run only the
direct checks named in the plan, then update the PR body. Skip `review-loop`
and external reviewers. Escalate to the standard path if review exposes hidden
coupling or operational risk.

For the standard path: run `review-loop` (current branch, no `stack`) per that
skill and panel-runtime. Ambiguous findings: collect, don't mid-loop ask. After
convergence: `gt modify -a`, then `pr-description` for the real body.

## 8. Pre-CodeRabbit CI gate

For the standard path, run `/ci` once after `review-loop` converges. Fix local
failures and repeat only the failed gate until green, then `gt modify -a` if
needed. This is the only full local CI pass; never run it inside review rounds.

On the trivial fast path, keep the existing direct checks and skip full local
CI.

## 9. Feedback and CodeRabbit convergence

1. `gt ss` once so CodeRabbit can review the implementation.
2. Run `finish-pr-review current`. It addresses existing feedback, ensures a
   full CodeRabbit baseline, and drives incremental reviews until clean or
   nits-only. It owns replies, thread resolution, and final verification.
   Ask only for substantive disagreements, alternatives, or real blockers.
3. Do not separately request CodeRabbit reviews or wait for CI runs started by
   intermediate pushes. Those runs may be cancelled by later pushes.

## 10. Final handoff gate

Reuse the exact-head review and CI evidence from `finish-pr-review`; do not
push or launch a second review loop merely to repeat its final gate.
If the head or relevant base changes afterward, return to that skill's
coverage and verification checks. Never declare an unreviewed terminal fix
converged. If Graphite skipped CI, use local `nix run .#ci` and disclose it.

## 11. Report

Issue URL, PR URL, CI, one-line what shipped, plan path.

## Hard rules

1. Version control via `gt`.
2. No standard-path implementation before plan approval (attached plans still
   get a quick confirm). Trivial fast-path plans are auto-approved by the
   implementation request.
3. Linear ↔ PR linked both ways.
4. Panel and critics per panel-runtime. Never impersonate a dropped
   model.
5. Don't declare done until CI for this HEAD is green (or local full
   CI when Graphite skipped it).
6. Full local CI runs once after multi-model convergence; full remote CI is
   awaited only after CodeRabbit convergence and the latest-trunk restack.
