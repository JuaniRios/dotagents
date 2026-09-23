---
name: council-eval
description: >
  One unbiased review from each available model (opus 5.5, sol 5.6,
  Cursor Grok 4.6, composer 2.5, flash 3.7) of a plan, document, diff, or
  question. Use when
  the user says council-eval, council, multi-model review, or wants
  each model to look at the same artifact once. Not the full review-loop.
argument-hint: "<path-or-prompt>"
allowed-tools: Bash(*), Read, Write
---

# council-eval

One generalist lane per **model**. No specialists. No fix loop. The
host harness assembles; it does not add a sixth opinion.

**Lanes:** `review-opus` (opus 5.5), `review-sol` (sol 5.6),
`review-grok` (Cursor Grok 4.6), `review-composer` (composer 2.5),
`review-flash` (flash 3.7).

Lane catalogue, CLI recipes, Max preflight, and native-vs-foreign rules:
`panel-runtime.md`. Do not restate or fork that catalogue here.

## 1. Resolve the target

The user's request is the target. If they passed a file path, that file
is the artifact. If they passed prose (or "review this plan" in the
conversation), write the artifact to `$out_dir/target.md` so every lane
reads the same bytes.

If the target is empty, ask once what to review and stop until they answer.

## 2. Workspace and preflight

```bash
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ts=$(date +%Y-%m-%d_%H-%M-%S)
out_dir="$repo_root/.tmp/council-eval/$ts"
mkdir -p "$out_dir"
schema="$HOME/Github/dotagents/skills/council-eval/schema.json"
```

If this is inside a git repo and `.tmp/` is not gitignored, ask before
adding it. Do not silently edit `.gitignore`.

```bash
command -v claude
command -v codex
command -v cursor-agent
command -v agy
```

Drop any lane whose **model** CLI is missing, unless that model is
native on this harness. Say which models dropped.

Run the Max preflight from panel-runtime before launching the council.

## 3. Shared prompt

Write `$out_dir/prompt.txt`:

```
You are a senior staff engineer reviewing an artifact. Be rigorous but
not pedantic. Care about correctness, completeness, feasibility, and
hidden cost — not style.

The artifact is at: {TARGET_PATH}

Read that file fully. Review only what is in it. Do not invent
requirements the artifact does not claim.

Priorities:
1. Does the plan actually achieve what it says it will?
2. Contradictions, missing cases, or steps that cannot be executed.
3. Cost or operational risk the author underweighted.
4. A smaller plan that still meets the stated goal.

Do not flag wording nits, formatting, or "I would have written it
differently" unless a reader would do the wrong thing.

Output JSON matching the schema you were given: an array of findings
(title, severity critical|high|medium|low|nit, category consistency|goal|
completeness|feasibility|scope|cost, finding, why_it_matters,
recommended_fix, confidence 0-100). If nothing is worth raising, return
{"findings": [], "clean_reason": "<one sentence>"}.
```

Do not add a markdown fallback. Panel-runtime injects the schema into the
prompt for Cursor Agent, whose CLI has no schema flag, and validates the
returned JSON after extracting its envelope.

## 4. Run one wrapper per model

Fan out in one parallel batch with this host harness's parallel
primitive. Each wrapper is a host child. It either *is* the pinned
model or it pipes to that model's CLI (see panel-runtime).

Run the **Council lanes** from panel-runtime with
`promptPath=$out_dir/prompt.txt`, `targetPath`, `repoRoot=$repo_root`, and
`schemaPath=$schema`. Cursor Grok and composer always run as separate
Cursor-Agent processes. Preserve panel-runtime's retry, timeout, envelope
extraction, schema validation, and no-impersonation behavior.

## 5. Normalize, dedup, report

Parse each lane into the schema. A dead, empty, or invalid lane is
`reviewer_error`, not a clean pass.

Dedup by overlapping title/claim. Keep `found_by` as model ids.

Write `$out_dir/findings.json` and assemble `$out_dir/council.md`
deterministically (no synthesis agent):

```
# Council — <target one-liner>
Lanes: opus 5.5, sol 5.6, Cursor Grok 4.6, composer 2.5, flash 3.7  (dropped: …)

## Findings
### [SEVERITY] <title>
- Found by: …
- Category / confidence
- Issue / Why / Fix

## Clean lanes
- <lane>: <clean_reason>

## Lane errors
- <lane>: <error>
```

Print a two-line-per-finding summary in the chat. Point at `council.md`.
Do not auto-fix. Do not start review-loop.

## Hard rules

1. Five generalists only (opus 5.5, sol 5.6, Cursor Grok 4.6, composer 2.5,
   flash 3.7). No inspectors. No re-review loop.
2. Use panel-runtime's native/foreign routing. Cursor Grok and composer are
   always distinct Cursor-Agent processes.
3. `claude -p` is Max-plan usage. Unset `ANTHROPIC_API_KEY`. If Max is
   already thin, drop `review-opus` and say so.
4. A missing or failed CLI drops that lane. Do not impersonate it.
5. Read-only. Do not mutate git, Linear, or the artifact.
6. The host does not add findings of its own except to record lane errors.

## Failure modes

- All five lanes error: stop. Do not invent a review.
- Artifact path does not exist: stop and tell the user.
- `agy -p` hangs: stdin was not detached, or `-p` was not last. Kill and retry.
- Opus output lands on Console billing: `ANTHROPIC_API_KEY` was set. Unset and rerun only if the user asks.
