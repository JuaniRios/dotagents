---
name: critique-loop
description: Cross-critique a plan, spec, ADR, or design doc from ten distinct critic perspectives, fix the verified findings in the document, and re-critique until clean. The document-side sibling of a code review loop - use it on SPEC.md changes, ADRs, delivery plans, and architecture docs, never on code diffs.
---

Run a full critique loop on one or more documents: critique -> fix ->
re-critique -> repeat until clean. Use this before a plan, spec, ADR, or
design doc is shared, to catch holes before readers do.

The loop is **automatic by default**: findings that clearly should be fixed
are fixed without asking. The exception is any finding whose fix would
change a decision the document records (an architecture choice, a scope
cut, a sequencing commitment) - those always go to the user first. The
document is the record of the user's decisions, not the critic's.

**Why it loops:** critique is stochastic - each independent pass surfaces
different findings. Converge only when a fresh pass returns no new
actionable findings. Never end on a fix.

## 1. Preflight

1. Resolve the target documents from the request: file paths (markdown or
   HTML). With no target given, ask one concise question.
2. Create a scratch workspace (`.tmp/critiques/<timestamp>/` inside a repo,
   else a temp dir). Copy each target into `originals/` as the untouched
   baseline. Fixes are applied to the real files, never the copies.

## 2. Load context

1. **The stated goal**: extract it from the document (TL;DR, problem
   statement) and any linked issue. Every critique pass judges against it.
2. **Grounding sources**: the repos, code paths, contracts, and documents
   the target cites. Read them when checking a factual claim.
3. **House style**: no em dashes; short paragraphs (one idea each);
   plain language; no process narration (never describe how the document
   came to be - only decisions and considered alternatives).

## 3. Critique pass: ten perspectives

Run the ten critic perspectives below as sequential passes over the full
document set. Keep each perspective's findings separate until dedup. For
each finding record: title, severity (critical | high | medium | low |
nit), doc, section (nearest heading), a short verbatim quote locating it,
category (consistency | goal | grounding | completeness | feasibility |
clarity | scope | style), the finding, why it matters, a concrete
recommended fix, whether it is decision_changing, and confidence (0-100).

1. **Internal consistency** - contradictions between sections: counts vs
   lists, tables vs prose, diagrams vs text, terminology drift, sequencing
   that violates the document's own dependencies.
2. **Goal evaluation** - be adversarial about the stated goal: the gap
   between what the document promises and what following it would produce.
   If a gate claims to prove something, check what passing it actually
   proves.
3. **Failure modes & risks** - read every step assuming it goes wrong:
   missing rollback, irreversible steps not marked, concurrent external
   actors, assumptions that everything happens in the stated order.
4. **Completeness & gaps** - what is missing, not what is wrong: unowned
   dependencies, absent workstreams (deployment, observability,
   operations), questions raised and never answered.
5. **Broad sweep** - holistic read with no category bias: would a competent
   engineer, handed only this document, build the right thing?
6. **Feasibility** - can each step be executed as written and each gate be
   measured? Steps with no actor, criteria that restate the step, and
   sequencing a single implementer cannot follow.
7. **Clarity** - ambiguity a reader could act wrongly on: undefined jargon,
   two-reading sentences where the difference matters, "we/someone" where
   a specific actor matters.
8. **Scope discipline** - content that belongs in another document,
   duplicated responsibilities, work items past the stated scope, missing
   non-goals.
9. **Grounding** - every claim about code, contracts, or external systems
   checked against the actual cited source. Wrong or stale claims that work
   will be built on are critical.
10. **Style** - house-style violations: em dashes (must be zero),
    wall-of-text paragraphs, process narration, redundant restatement that
    can drift, inconsistent naming.

What NOT to flag: style preferences beyond the house rules; decisions the
document explicitly records (flag consequences as risks, do not relitigate
choices); depth delegated to a linked companion document; hypotheticals
with no concrete failure story.

## 4. Verify, dedup, triage

1. **Verify adversarially** before triage: re-read the document at each
   finding's quote (and the cited source, for grounding findings) and
   classify valid | likely | disputed | invalid | out-of-scope. Dismiss
   invalid findings; out-of-scope means real but owned by a system or
   companion document the target does not control.
2. **Dedup** across perspectives by doc + category + overlapping section.
3. **Triage**: critical and verified high/medium findings with confidence
   >= 50 are fixed now; low with confidence >= 75 fixed now; the rest
   dismissed. Two overrides: decision_changing findings are ALWAYS
   discussed with the user first, and real out-of-scope findings go to an
   open-questions list surfaced in the final summary (never silently
   dropped, never turned into issues unprompted).

## 5. Fix pass

For each fix-now finding, in severity order: re-read the section (text may
have moved), apply the minimal edit that resolves it, keep the document's
voice and the house style. Never let an edit change a recorded decision -
reclassify to discuss instead.

**Style gate** after every fix pass, before re-critiquing, as a
deterministic scan per document: em-dash count must be zero; list any
paragraph over ~600 characters; for HTML, tag balance unchanged. Fix
violations immediately.

## 6. Re-critique until clean

Re-run the ten perspectives as a fresh pass over the updated documents,
plus one check per applied fix (does the edit fully resolve the finding
without contradicting nearby text?). Filter findings substantively
identical to ones already fixed or dismissed. Clean = no new actionable
findings and every fix verified. **Cap at 4 passes total**; at the cap,
report per-pass history and stop.

## 7. Summarize

Passes run; findings fixed / dismissed / discussed per pass; the
open-questions list; and where the before/after baseline copies live.

## Hard rules

1. Never auto-change a recorded decision; those findings are always
   discussed first.
2. Never end on a fix - convergence requires a clean independent pass.
3. Fixes edit the minimum text that resolves the finding; no drive-by
   rewrites of untouched sections.
4. House style is enforced, not debated; the style gate runs after every
   fix pass.
5. Do not create issues, publish, or touch version control unless asked.
6. Cap at 4 passes; report and stop at the cap.
