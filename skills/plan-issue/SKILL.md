---
name: plan-issue
description: >
  Plan a Linear issue with light, standard, or deep review according to risk.
  Use when asked to plan an issue, or when a complex implementation needs a
  published design. Config-only work gets a short self-checked plan; simple
  changes get one independent pass; complex changes get multi-model critique.
  Read-only on the repo.
argument-hint: "<issue-link-or-number>"
allowed-tools: Bash(*), Read, Write
---

# plan-issue

Turn a Linear issue into a reviewed implementation plan attached as a
Linear document titled `<ID> Implementation Plan` (the detection
contract for `implement-issue`). First read
`~/Github/dotagents/skills/issue-thoroughness.md` and select a level.
Read panel-runtime only for deep planning.

Never edit code or mutate git. The Linear document is the only side
effect.

## Thoroughness gate

Use the shared light / standard / deep policy, not a blanket multi-model gate.
An explicit invocation for a small issue produces a small plan without asking
the user to opt into a heavier workflow. Publish the requested Linear plan at
any level; for an inline-only request, return it inline without publishing.
Do not auto-invoke this skill for a routine implementation that needs only
the local plan in implement-issue.

## 1. Read the issue

Use linear-cli and write-as-me. `linear issue view <ID>`.
If `<ID> Implementation Plan` already
exists, ask whether to rewrite or stop.

## 2. Situate

`gt log`, referenced PRs, parent issues, ADRs. Flag stale or already-done
aims in the sign-off section.

## 3. Research

Light and standard: investigate directly; do not spawn exploration children.
Deep: use isolated exploration children for independent call chains when
useful. Every claim about what exists must come from the repo.

## 4. Draft

Light: a few bullets covering the change, affected files, direct validation,
and rollback where relevant. No architecture document or invented decisions.
Standard: a short goal, approach, affected files, tests, and actual open
questions. The host drafts both levels.

Deep: use the planner from panel-runtime's Plan critics section, then draft
Part 1 (human sign-off) in plain language without code identifiers, and
Part 2 (implementer) with files, symbols, tests, sequencing, and rollback.
Record the selected level and reason. Do not restate repository documents.

## 5. Critique

Light: host self-check only. Standard: one independent pass per the shared
policy, then verify corrections without a broad re-review loop.
Deep: run critique-loop on the draft. It owns its panel and convergence;
do not also launch the separate Plan critics panel.

Record the actual review coverage and findings addressed. An unavailable
reviewer or exhausted deep-review budget is incomplete, not approval.
Bring decision-changing findings to the user before publishing them as agreed.

## 6. Publish

```bash
linear document create -t "<ID> Implementation Plan" --issue <ID> -f <path>
```

No `--icon`. Rewrite uses `linear document update`.

## 7. Report

Level and reason, verdict against current state, document URL or inline
plan, actual review coverage, and any sign-off decisions.

## Hard rules

1. No code or git mutation.
2. Title is exactly `<ID> Implementation Plan`.
3. Deep-plan Part 1 has no code identifiers. Use write-as-me for prose.
4. Ground every claim in the repo.
5. Apply the selected level's review, not a mandatory panel at every level.
6. Deep panels follow panel-runtime. Never impersonate a dropped model.
