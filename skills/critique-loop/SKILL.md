---
name: critique-loop
description: >
  Cross-critique a plan, spec, ADR, or design doc with a multi-model
  panel, auto-fix verified findings, and re-critique until clean. Use only
  when the user explicitly asks for critique-loop or multi-model critique, or
  when an applicable complex planning workflow explicitly requires it. Do not
  auto-trigger for routine documentation edits or simple plans. The document
  sibling of review-loop; never use on code diffs.
argument-hint: "<doc-path...>"
allowed-tools: Bash(*), Read, Write, Edit
---

# critique-loop

Critique → fix → lean re-critique until a clean pass. Read
`~/Github/dotagents/skills/panel-runtime.md` first (critique lane
table). This file owns document targeting and the decision-changing
override.

## 1. Target

One or more markdown/HTML paths, or a published artifact URL (fetch and
save a working copy). None: ask once.

Copy originals to `$out_dir/originals/`. Fixes go to the real files.

## 2. Context

Stated goal (from the doc and any linked Linear issue). Grounding
sources the doc cites. House style: no em dashes, short paragraphs, no
process narration.

## 3. Panel

Pass 1 and lean re-passes per panel-runtime's **Critique lanes**.
Finding locator is `doc + section + quote`. Schema categories:
consistency | goal | grounding | completeness | feasibility | clarity |
scope | style. Required boolean `decision_changing`.

## 4. Triage

Same severity table as review-loop, with one override:
**`decision_changing: true` is always Discuss**, whatever the
severity. Options: change the document / keep the decision and add the
risk / dismiss.

Out-of-scope-but-real items go to `$out_dir/open-questions.json`. Never
create Linear issues unprompted.

## 5. Fix and style gate

Host editor child. Minimal edits. Never change a recorded decision —
reclassify to Discuss. After every fix pass, zero em dashes; list
paragraphs over ~600 characters; HTML tag balance unchanged vs pass
start.

## 6. Re-critique

Fresh lean panel over the updated docs plus host fix-verifiers. Cap 4.
Never end on a fix. Quorum required.

## Hard rules

1. Never auto-change a recorded decision.
2. Never end on a fix. Quorum required.
3. Wording-preserving fixes. House style is a gate, not a debate.
4. Panel per panel-runtime. No second orchestrator.
5. No Linear / publish / git unless the user asks.
