---
name: council-eval
description: >
  One unbiased review from each available model (opus 5, sol 5.6,
  grok 4.6, flash 3.7) of a plan, document, diff, or question. Use when
  the user says council-eval, council, multi-model review, or wants
  each model to look at the same artifact once. Not the full review-loop.
argument-hint: "<path-or-prompt>"
allowed-tools: Bash(*), Read, Write
---

# council-eval

One generalist lane per **model**. No specialists. No fix loop. The
host harness assembles; it does not add a fifth opinion.

**Lanes:** `review-opus` (opus 5), `review-sol` (sol 5.6),
`review-grok` (grok 4.6), `review-flash` (flash 3.7). fable 5 is not
a council lane.

CLI recipes and native-vs-foreign rules: `panel-runtime.md`.

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
command -v grok
command -v agy
```

Drop any lane whose **model** CLI is missing, unless that model is
native on this harness. Say which models dropped.

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

If a CLI cannot take a JSON schema, append the markdown fallback:

```
For each finding emit:

### <title>
- **Severity:** critical | high | medium | low | nit
- **Category:** consistency | goal | completeness | feasibility | scope | cost
- **Finding:** <one paragraph>
- **Why it matters:** <consequence>
- **Recommended fix:** <concrete change>
- **Confidence:** <0-100>

If clean, emit exactly:

### No findings
<one sentence>
```

## 4. Run one wrapper per model

Fan out in one parallel batch with this host harness's parallel
primitive. Each wrapper is a host child. It either *is* the pinned
model or it pipes to that model's CLI (see panel-runtime).

Host harness: claude, codex, grok, or agy.

| Lane | Model | Native on harness | Else CLI |
|---|---|---|---|
| `review-opus` | opus 5 | claude | `claude -p --model opus` |
| `review-sol` | sol 5.6 high | codex | `codex exec -m gpt-5.6-sol` |
| `review-grok` | grok 4.6 high | grok | `grok -p --model grok-4.6 --effort high` |
| `review-flash` | flash 3.7 high | agy | `agy -p --model gemini-3.7-flash-high` |

**Native:** read `$out_dir/prompt.txt` and `{TARGET_PATH}`, return schema JSON
to `$out_dir/raw-<lane>.json`.

**CLI recipes** (write stdout to `$out_dir/raw-<lane>.txt` or `.json`):

```bash
SCHEMA_INLINE=$(cat "$schema")

# opus 5 — Max plan only. Never if ANTHROPIC_API_KEY would stick.
# Do not use this when the host is already Claude.
env -u ANTHROPIC_API_KEY claude -p --model opus \
  --output-format text \
  "$(cat "$out_dir/prompt.txt")" \
  > "$out_dir/raw-review-opus.txt"

# sol
codex exec --sandbox read-only -m gpt-5.6-sol \
  -c service_tier="fast" \
  -C "$repo_root" \
  "$(cat "$out_dir/prompt.txt")" \
  > "$out_dir/raw-review-sol.txt"

# grok 4.6 — not when the host harness is already grok
grok -p "$(cat "$out_dir/prompt.txt")" \
  --model grok-4.6 --effort high \
  --json-schema "$SCHEMA_INLINE" \
  --disallowed-tools Agent \
  > "$out_dir/raw-review-grok.json"

# flash 3.7 — -p last; detach stdin; skip-permissions (headless
# sandbox denies read_file). Do not pass --effort (conflicts with
# gemini-3.7-flash-high).
agy --sandbox --disable-slash-commands \
  --model gemini-3.7-flash-high \
  --output-format json --json-schema "$schema" \
  --print-timeout 10m \
  --dangerously-skip-permissions \
  -p "$(cat "$out_dir/prompt.txt")" \
  < /dev/null \
  > "$out_dir/raw-review-flash.json"
```

If `codex` rejects `service_tier=fast`, retry without that flag. If a CLI
429s, retry once, then drop that lane and record the error. Never fall
back to the host model and still label the result as the missing model.

Timeout: 10 minutes per lane.

## 5. Normalize, dedup, report

Parse each lane into the schema. Markdown `###` sections become findings.
A dead or empty lane is `reviewer_error`, not a clean pass.

Dedup by overlapping title/claim. Keep `found_by` as the list of lanes.

Write `$out_dir/findings.json` and assemble `$out_dir/council.md`
deterministically (no synthesis agent):

```
# Council — <target one-liner>
Lanes: opus 5, sol 5.6, grok 4.6, flash 3.7  (dropped: …)

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

1. Four generalists only (opus 5, sol 5.6, grok 4.6, flash 3.7). No
   fable 5. No inspectors. No re-review loop.
2. Never `claude -p` when the host harness is Claude. Never `grok -p`
   when it is Grok. Never `codex exec` when it is Codex. Never `agy -p`
   when it is Agy. Home-harness lanes are native children pinned to
   the model.
3. `claude -p` is Max-plan usage. Unset `ANTHROPIC_API_KEY`. If Max is
   already thin, drop `review-opus` and say so.
4. A missing or failed CLI drops that lane. Do not impersonate it.
5. Read-only. Do not mutate git, Linear, or the artifact.
6. The host does not add findings of its own except to record lane errors.

## Failure modes

- All four lanes error: stop. Do not invent a review.
- Artifact path does not exist: stop and tell the user.
- `agy -p` hangs: stdin was not detached, or `-p` was not last. Kill and retry.
- Opus output lands on Console billing: `ANTHROPIC_API_KEY` was set. Unset and rerun only if the user asks.
