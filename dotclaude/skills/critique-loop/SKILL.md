---
name: critique-loop
allowed-tools: Bash(codex:*), Bash(git:*), Bash(linear:*), Bash(mkdir:*), Bash(cat:*), Bash(cp:*), Bash(rm:*), Bash(test:*), Bash(grep:*), Bash(wc:*), Bash(date:*), Bash(basename:*), Bash(find:*), Bash(python3:*), Read, Write, Edit, Agent, Workflow, AskUserQuestion, WebFetch
description: Cross-critique a plan, spec, ADR, or design doc with a multi-model Workflow panel, auto-fix the verified findings in the document, and re-critique until clean. The document-side sibling of /review-loop - use it on SPEC.md changes, ADRs, delivery plans, architecture docs, and published artifacts, never on code diffs.
argument-hint: <doc-path...>
---

Run a full critique loop on one or more documents: critique -> fix ->
re-critique -> repeat until clean. Use this before sharing a plan, spec,
ADR, or design artifact, to catch holes before readers do.

This is `/review-loop` for prose. The panel shape, adversarial verification,
triage table, fix loop, and convergence rules are the same. What changes:
the lanes critique a document instead of a diff, the fix pass edits the
document, and the compile gate becomes a style gate. There is no /ci and no
version-control step.

The loop is **automatic by default**. Findings that clearly should be fixed
are fixed without asking. **Decision-changing findings are the exception**:
a finding whose fix would change a decision the document records (an
architecture choice, a scope cut, a sequencing commitment) is never
auto-applied - it goes to the user as a Discuss item, because the document
is the record of the user's decisions, not the panel's.

**Why it loops:** critique is stochastic - each independent pass surfaces
different findings. The loop runs fresh full panel passes so coverage
accumulates, and converges when an independent pass returns no new
actionable findings.

Follow these steps precisely.

---

## 1. Preflight

1. Resolve the target documents from the arguments. Accepted forms:
   - one or more file paths (markdown or HTML);
   - a claude.ai artifact URL - `WebFetch` it and save the HTML body
     (between `<title>` and `</main>`) to the workspace as the working copy;
     note in the final summary that the artifact needs republishing;
   - no argument: ask the user which documents to critique.
2. `codex` on PATH (`command -v codex`). If missing, warn and drop the two
   codex lanes (8 lanes instead of 10).
3. Create the workspace:
   ```bash
   ts=$(date +%Y-%m-%d_%H-%M-%S)
   out_dir="${TMPDIR:-/tmp}/critiques/${ts}"   # or $repo_root/.tmp/critiques/ inside a repo
   mkdir -p "$out_dir"
   ```
4. Copy each target document into `$out_dir/originals/` (the untouched
   baseline for the final before/after diff). Fixes are applied to the real
   files, never to the copies.
5. **Pre-allowlist** `codex`, `cat`, `grep`, and `python3` for spawned
   agents; a non-allowlisted call from a lane stalls the whole Workflow.

## 2. Load context

Collect what the panel needs to judge the documents:

1. **The stated goal.** Every plan claims to achieve something. Extract it
   from the document itself (TL;DR, problem statement) and, when the doc
   relates to a Linear issue or project, pull that description too
   (`linear` CLI). The goal-evaluation lane critiques against this.
2. **Grounding sources.** List the repos, code paths, contracts, and
   external documents the target cites. The grounding lane reads them to
   check the document's claims against reality. Inside a repo, include
   `CLAUDE.md`/`AGENTS.md` paths.
3. Write one shared context file:
   ```
   $out_dir/context.txt
     Documents: <paths, one per line>
     Stated goal: <extracted goal, verbatim where possible>
     Grounding sources: <paths/repos/URLs the docs cite>
     House style: no em dashes; short paragraphs (one idea each);
       ASD-STE100-leaning plain language; no process narration
       (never describe how the document came to be - only decisions
       and considered alternatives).
   ```

## 3. Build the critic prompts

Every critic gets a **shared base prompt** plus a **per-critic focus
paragraph**. On a premium session, delegate authoring to one `sonnet` setup
subagent (pass this file's path, `$out_dir`, and the lane keys); inline on
cheap models.

### Base prompt (`$out_dir/prompt-base.txt`)

```
You are a principal engineer reviewing a design document before it drives
real work. You have deep experience turning plans into systems and watching
plans fail. You are rigorous but not pedantic: you care whether the plan is
correct, complete, grounded, and actionable - not whether you would have
written it differently.

Your task: critique the document(s) listed in the shared context file. Read
them fully. Read the grounding sources when your focus requires checking a
claim against reality.

The document states this goal:
{STATED_GOAL}

Evaluate whether the document actually delivers on it. Do not take the
document's claims at face value.

Critique priorities, in order:

1. CORRECTNESS OF REASONING - conclusions that do not follow, contradictions
   between sections, numbers or counts that disagree, sequencing that
   violates the document's own dependencies.
2. GOAL FIT - gaps between the stated objective and what the plan, executed
   as written, would produce.
3. GROUNDING - claims about code, contracts, or external systems that are
   wrong, stale, or unverifiable.
4. COMPLETENESS - missing workstreams, unowned dependencies, absent failure
   handling, unstated assumptions a reader cannot supply.
5. ACTIONABILITY - steps that cannot be executed as written, gates that
   cannot be measured, acceptance criteria that cannot be checked.
6. CLARITY - only where a reader would misunderstand or be unable to act.
   Not "could be phrased better."

What NOT to flag:

- Style preferences beyond the house style in the shared context.
- Decisions the document explicitly records as decided, unless the decision
  is contradicted elsewhere in the document or by a grounding source. You
  may flag the CONSEQUENCE of a decision as a risk; do not relitigate the
  decision itself.
- Depth the document deliberately delegates to a linked companion document.
- Hypotheticals with no concrete failure story.
- Anything a spell-checker would catch.

Output: return findings via the structured output tool. Each finding needs:
title, severity (critical | high | medium | low | nit), doc (path),
section (nearest heading), quote (a short verbatim excerpt locating the
issue), category (consistency | goal | grounding | completeness |
feasibility | clarity | scope | style), finding, why_it_matters,
recommended_fix (concrete: what the text should say instead, or what must
be added), decision_changing (true when the fix would alter a decision the
document records), and confidence (0-100).

If you find nothing worth raising, return an empty findings list and set
clean_reason.
```

(For the two codex lanes, replace the Output paragraph with the markdown
`### <title>` section format, as in `/review-loop`; the lane agent converts
to structured output and must set `decision_changing` from the content.)

### Per-critic focus paragraphs

**sonnet-a - Internal consistency:**
```
YOUR FOCUS: Hunt contradictions. Compare every pair of sections that talk
about the same thing: counts vs lists, tables vs prose, diagrams vs text,
early claims vs later claims, terminology that drifts mid-document. If the
document says a thing twice, check the two statements agree exactly.
```

**opus-b - Goal evaluation (opus, xhigh):**
```
YOUR FOCUS: Be adversarial about the stated goal. If the plan claims the
rollout is risk-free, construct the scenario where it is not. If it claims
a step is independent, find the hidden coupling. If a gate claims to prove
something, check what passing it actually proves. Your job is the gap
between what the document promises and what following it would produce.
```

**sonnet - Failure modes & risks:**
```
YOUR FOCUS: Read every step assuming it goes wrong. What is the recovery
when a step fails halfway? Which steps are irreversible and does the
document say so? Which external actors can fail or act concurrently, and
does the plan survive that? Flag missing rollback, missing monitoring, and
assumptions that everything happens in the stated order.
```

**codex-a - Completeness & gaps:**
```
YOUR FOCUS: Find what is missing, not what is wrong. Unowned dependencies,
absent workstreams (deployment, observability, operations, documentation),
scenarios with no owner, work implied but never assigned, questions the
document raises and never answers. List what a reader would still have to
figure out alone.
```

**codex-b - Broad sweep:**
```
YOUR FOCUS: Read the document holistically, without a category bias. Does
the overall shape make sense? Would a competent engineer, handed only this
document, build the right thing? Find anything the other critics might
miss, including problems that span multiple sections.
```

### Inspector prompts

Five inspectors, one prompt file each (dedicated prompts - no sibling
skills to import):

**feasibility-inspector** (`prompt-feasibility-inspector.txt`):
```
You inspect actionability. Walk every step, gate, and acceptance criterion
in the document(s) and ask: can a person execute this as written, and can
anyone verify it was done? Flag: steps with no actor, gates with no
measurement, acceptance criteria that restate the step, estimates that
contradict the described work, and sequencing a single implementer cannot
actually follow. Category "feasibility". Severity: unexecutable step =
high, unmeasurable gate = medium, vague criterion = low.
```

**clarity-inspector** (`prompt-clarity-inspector.txt`):
```
You inspect ambiguity. Flag: jargon used before it is defined, terms the
target audience cannot be assumed to know, sentences with two readings
where the difference matters, ownership stated as "we/someone" where a
specific actor matters, and pronouns whose antecedent is ambiguous. Judge
against the document's audience, not a general reader. Category "clarity".
Severity: actionable-ambiguity (a reader could do the wrong thing) =
medium-high, comprehension-drag = low.
```

**scope-inspector** (`prompt-scope-inspector.txt`):
```
You inspect scope discipline. Flag: content that belongs in a different
document (implementation detail in an architecture doc, rationale
relitigated in a delivery plan), duplicated responsibilities between
sections, work items that expand past the document's stated scope, and
boundaries the document never draws (what is explicitly NOT in scope).
Category "scope". Severity: misplaced decision-bearing content = medium,
duplication that can drift = medium, missing non-goals = low.
```

**grounding-inspector** (opus, xhigh) (`prompt-grounding-inspector.txt`):
```
You inspect factual grounding. Inventory every claim the document(s) make
about external reality: code behavior, repo contents, contract interfaces,
API capabilities, team ownership, prior decisions. For each, check it
against the grounding sources in the shared context - read the actual code
or document cited. Flag claims that are wrong, stale, or stated as fact
without a checkable source. Category "grounding". Severity is risk-weighted:
a wrong claim that work will be built on = critical/high; an unverifiable
claim = medium; a cosmetic inaccuracy = low. The recommended_fix names the
correction or the source to pin.
```

**style-inspector** (`prompt-style-inspector.txt`):
```
You inspect prose discipline against the house style in the shared context.
Flag: em dashes (must be zero), wall-of-text paragraphs (more than roughly
three sentences or one idea), process narration (any account of how the
document evolved, reviews it went through, or what earlier drafts said -
only decisions and considered alternatives are allowed), redundant
restatement of the same fact in multiple places (drift risk), and
inconsistent naming for one concept. Category "style". Severity: process
narration or em dashes = medium (house rules), redundancy = medium,
walls of text = low.
```

Save each complete prompt (base + focus) to `$out_dir/prompt-{key}.txt`.

## 4. Run the critique workflow

One `Workflow` invocation per pass: fan-out, per-lane adversarial
verification (pipelined, no barrier), fix-verification on re-passes,
deterministic assembly by the caller. Reuse `/review-loop`'s workflow
script structure with these substitutions:

- **Lane catalogue** (same shape - drop codex lanes if `codex` missing):

  | key                   | codex | model  | effort |
  | --------------------- | ----- | ------ | ------ |
  | sonnet-a              | no    | sonnet |        |
  | opus-b                | no    | opus   | xhigh  |
  | sonnet                | no    | sonnet |        |
  | codex-a               | yes   | sonnet | medium |
  | codex-b               | yes   | sonnet | medium |
  | feasibility-inspector | no    | sonnet |        |
  | clarity-inspector     | no    | sonnet |        |
  | scope-inspector       | no    | sonnet |        |
  | grounding-inspector   | no    | opus   | xhigh  |
  | style-inspector       | no    | sonnet |        |

- **Finding schema**: replace `file`/`line_start`/`line_end` with
  `doc`/`section`/`quote`, the category enum with `consistency | goal |
  grounding | completeness | feasibility | clarity | scope | style`, and
  add required boolean `decision_changing`.
- **Codex lane command**: same `codex exec --sandbox read-only -m gpt-5.5
  -c model_reasoning_effort=... -c service_tier="fast"` pattern, but pipe
  the document(s) instead of a diff (`cat` the doc paths in order).
- **Adversarial verify prompt**: "Read the actual document at the finding's
  quote and section - never judge from the finding text alone. For
  grounding findings, also read the cited source. Classify valid | likely |
  disputed | invalid | out-of-scope (out-of-scope = real but about a system
  the document does not control, or content a linked companion document
  owns)."
- **verifyFix**: reads the current document at the finding's section and
  confirms the edit fully resolves it without contradicting nearby text.
- Dedup key: same `doc` + `category` + overlapping `section`/`quote`.

**Adaptive sizing:** under ~300 lines of document, run `opus-b` + one codex
lane + all five inspectors (~7 lanes). 300-2000 lines, full catalogue minus
one codex lane. Over 2000 lines or any document that commits money,
security, or irreversible operations: full catalogue. Over ~4000 total
lines, chunk per document (each doc its own reviewer lane set; inspectors
read everything once).

## 5. Assemble, print, triage

Identical to `/review-loop` steps 5-10, with the finding locator being
`doc + section + quote` instead of `file:line`:

1. Write `findings.json`; assemble `critique.md` deterministically (delegate
   rendering to a `sonnet` subagent on premium sessions).
2. Print the two-line-per-finding severity summary; never echo full finding
   bodies into the main session.
3. Triage by the same severity/verdict/confidence table with one override:
   **`decision_changing: true` findings are always Discuss**, whatever the
   severity. Present them with the recorded decision, the finding, and the
   options "Change the document" / "Keep the decision, add the risk" /
   "Dismiss".
4. Real findings about systems the document does not control (missing
   contract features, upstream gaps) are **not** fixes or dismissals: append
   them to `$out_dir/open-questions.json`. They surface in the final
   summary, and the user may ask to turn them into Linear issues via
   `/linear-cli` (never create issues unprompted).

## 6. Fix pass

On premium sessions, spawn one `sonnet` **editor subagent** per fix pass
with the fix-now findings JSON and the document paths; inline on cheap
models. For each finding in severity order: re-read the section (the text
may have moved), apply the minimal edit that resolves the finding, keep the
document's voice and the house style, and print a one-line summary.

Never let an edit change a recorded decision - if a fix turns out to
require that, reclassify to Discuss and continue.

### Style gate (replaces the compile gate)

After every fix pass, run a deterministic scan before any re-critique:

```bash
python3 - <<'EOF'
# per target document:
#   em dashes           -> must be 0
#   paragraphs > 600 chars of text -> list them
#   (HTML) <p>/<pre>/<div> balance -> must be unchanged vs pass start
EOF
```

Fix violations immediately - never enter a re-critique pass that a
deterministic scan would fail; that wastes an entire panel pass.

## 7. Re-critique loop

Identical to `/review-loop` step 12: a re-critique is a **fresh independent
full panel pass** over the updated document(s), with fix-verification
folded in (`fixedFindings` as `{title, doc, section}` locators). Clean =
no new actionable findings AND every fix verified. Filter findings
substantively identical to ones already fixed or dismissed. **Cap at 4
passes total**; on the cap, report per-pass history and stop. The pattern
is always `critique -> fix -> critique(clean) -> done` - never end on a
fix.

## 8. Converge and summarize

1. Print the final summary: passes run, findings fixed/dismissed/discussed
   per pass, the before/after word count, and a `git`-style diff of each
   document against its `originals/` copy (path only - do not print the
   diff body).
2. List `open-questions.json` items and offer (do not execute) `/linear-cli`
   issue creation for them.
3. If a target was a published artifact, remind the user it needs
   republishing (or republish via the `Artifact` tool if this session owns
   it and the user asked).

## Hard rules

1. **Never auto-change a recorded decision.** `decision_changing` findings
   are always Discuss. The panel advises; the user decides.
2. **Never end on a fix.** Convergence requires a clean independent pass.
3. **Wording-preserving by default.** Fixes edit the minimum text that
   resolves the finding; no drive-by rewrites of untouched sections.
4. **House style is enforced, not debated**: zero em dashes, short
   paragraphs, no process narration. The style gate runs after every fix
   pass.
5. The `Workflow` tool exists only in the main session - never wrap the
   loop in an orchestrator subagent, and never hand-roll the fan-out with
   `Agent` calls.
6. Never echo full finding bodies, document contents, or `critique.md` into
   the main session; triage from structured fields, prose stays on disk.
7. Do not create Linear issues, republish artifacts, or touch version
   control unless the user asks.
8. Cap at 4 panel passes; report and stop at the cap.

## Failure modes

- **All lanes error** -> stop and report; do not fix anything on partial
  evidence.
- **codex missing** -> 8-lane panel, note it in the summary.
- **A document is huge (> ~4000 lines)** -> chunk per document; if a single
  document exceeds that alone, ask the user whether to critique it in
  sections.
- **Two findings give contradictory fixes** -> Discuss both together; never
  apply both.
- **The user rejects a Discuss decision-change** -> record "considered and
  kept" in the triage log, never re-raise it in later passes.
