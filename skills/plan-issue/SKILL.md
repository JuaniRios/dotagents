---
name: plan-issue
description: >
  Plan a Linear issue with light, standard, or deep review according to risk,
  and publish two Linear documents: a concise human-facing plan summary and
  the detailed implementation plan. Use when asked to plan an issue, or when a
  complex implementation needs a published design. Config-only work gets a
  short self-checked plan; simple changes get one independent pass; complex
  changes get multi-model critique. Read-only on the repo.
argument-hint: "<issue-link-or-number>"
allowed-tools: Bash(*), Read, Write
---

# plan-issue

Turn a Linear issue into a reviewed plan published as two Linear documents
attached to the issue:

- `<ID> Plan summary`: what humans read. Concise, plain language, no code
  identifiers.
- `<ID> Implementation Plan`: all the how, for the implementer. This title is
  the detection contract for `implement-issue`.

First read
`~/Github/dotagents/skills/issue-thoroughness.md` and select a level.
Read panel-runtime only for deep planning.

Never edit code or mutate git. The two Linear documents are the only side
effects.

## Thoroughness gate

Use the shared light / standard / deep policy, not a blanket multi-model gate.
An explicit invocation for a small issue produces a small plan without asking
the user to opt into a heavier workflow. Publish both documents at every
level; for an inline-only request, return both parts inline without publishing.
Do not auto-invoke this skill for a routine implementation that needs only
the local plan in implement-issue.

## 1. Read the issue

Use linear-cli and write-as-me. `linear issue view <ID>`.
If `<ID> Plan summary` or `<ID> Implementation Plan` already exists, ask
whether to rewrite or stop.

## 2. Situate

`gt log`, referenced PRs, parent issues, ADRs. Flag stale or already-done
aims in the summary.

## 3. Research

Light and standard: investigate directly; do not spawn exploration children.
Deep: use isolated exploration children for independent call chains when
useful. Every claim about what exists must come from the repo.

## 4. Draft

Draft both documents at every level.

**Plan summary** (what a human reads to decide). Plain language, no code
identifiers: no file paths, symbols, commands, or config keys. At most about
250 words; about 100 for light. Only these sections, each omitted when empty:

- **Goal**: the outcome in one or two sentences.
- **What changes**: behavior, and which services or repositories change.
- **Security**: new permissions, secrets, trust boundaries, or exposure.
- **Architecture**: new components, dependencies, data flows, or migrations.
- **Decisions needed**: each open decision with its options and your
  recommendation.
- **Risks**: what could go wrong, and how it is rolled back.

End it with a link to the implementation plan. Everything about how goes in
the implementation plan, not the summary.

**Implementation Plan** (all the how), by level:

- Light: a few bullets covering the change, affected files, direct
  validation, and rollback where relevant. No architecture document or
  invented decisions.
- Standard: goal, approach, affected files, tests, sequencing, and actual
  open questions.
- Deep: use the planner from panel-runtime's Plan critics section, then give
  files, symbols, tests, sequencing, and rollback.

The host drafts light and standard. Record the selected level and reason in
the implementation plan. Do not restate repository documents. The summary
must agree with the implementation plan; a change to one updates the other.

## 5. Critique

Light: host self-check only. Standard: one independent pass per the shared
policy, then verify corrections without a broad re-review loop.
Deep: run critique-loop on the draft. It owns its panel and convergence;
do not also launch the separate Plan critics panel.

Review both documents together: the summary must state every decision,
security change, and architecture change the implementation plan contains.
Record the actual review coverage and findings addressed. An unavailable
reviewer or exhausted deep-review budget is incomplete, not approval.
Bring decision-changing findings to the user before publishing them as agreed.

## 6. Publish

```bash
linear document create -t "<ID> Implementation Plan" --issue <ID> -f <implementation-path>
linear document create -t "<ID> Plan summary" --issue <ID> -f <summary-path>
```

Create the implementation plan first so the summary can link to it. No
`--icon`. A rewrite updates both with `linear document update`.

## 7. Report

Level and reason, verdict against current state, both document URLs (or the
inline plan), actual review coverage, and the decisions needed.

## Hard rules

1. No code or git mutation.
2. Publish both documents at every level. Titles are exactly
   `<ID> Plan summary` and `<ID> Implementation Plan`.
3. The summary is concise and has no code identifiers; the how belongs only in
   the implementation plan. Use write-as-me for prose.
4. Ground every claim in the repo.
5. Apply the selected level's review, not a mandatory panel at every level.
6. Deep panels follow panel-runtime. Never impersonate a dropped model.
