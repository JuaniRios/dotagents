# Panel runtime

Shared contract for every multi-model skill (`review-loop`, `review-pr`,
`critique-loop`, `implement-issue`, `plan-issue`, `implement-issue-stack`).
Read this file before spawning reviewers. Do not restate these tables
in those skills.

**Harnesses** (where the skill is running): `claude`, `codex`, `grok`,
`agy`. The current one is the **host**. Fan out with that host's
parallel primitive. Never wrap the panel in a second orchestrator.

**Models** (who reviews). Do not use a harness name as if it were a
model.

| Model | Effort | Home harness | Native on that harness | Foreign CLI (any other host) |
|---|---|---|---|---|
| grok 4.6 | high | grok | isolated Grok child, `-m grok-4.6 --effort high` | `grok -p --model grok-4.6 --effort high` |
| sol 5.6 | high | codex | isolated Codex child, `-m gpt-5.6-sol` high | `codex exec --sandbox read-only -m gpt-5.6-sol` |
| opus 5 | (xhigh when the lane says so) | claude | isolated Claude child, `model: opus` | `env -u ANTHROPIC_API_KEY claude -p --model opus` |
| fable 5.1 | xhigh | claude | isolated Claude child, `model: claude-fable-5-1` | `env -u ANTHROPIC_API_KEY claude -p --model claude-fable-5-1` |
| flash 3.7 | high | agy | isolated Agy child, `gemini-3.7-flash-high` | `agy -p --model gemini-3.7-flash-high` |

A model is **native** only on its home harness, and only as an
**isolated child pinned to that model**, not the babysitter. On any
other harness, reach it through that model's foreign CLI. Never
`claude -p` when the host is Claude. Never `grok -p` when the host is
Grok. Same for `codex exec` / `agy -p` on their home harnesses.

Do not pick opus 5 or fable 5.1 through the Agy CLI (Agy lists Claude
model ids; those are not this panel's Claude path).

If a model's CLI is missing or fails after one retry, **drop every
lane that needs that model** and say so. Do not run the work on the
host model and still label it as the missing model.

## Wrapper

Every lane is a host child that either *is* the pinned model or pipes
to that model's CLI.

Inputs: `promptPath`, `targetPath`, `repoRoot`, `schemaPath`.
Write stdout to `$out_dir/raw-<lane>.json` (or `.txt`).

```bash
SCHEMA="$HOME/Github/dotagents/skills/schemas/review-finding.json"
SCHEMA_INLINE=$(cat "$SCHEMA")

# opus 5 / fable 5.1 — Max plan. Always strip a Console key.
env -u ANTHROPIC_API_KEY claude -p --model <opus|claude-fable-5-1> \
  --output-format json --json-schema "$SCHEMA_INLINE" \
  "$(cat "$promptPath")"

# sol 5.6 — file schema (every property is already in `required`)
codex exec --sandbox read-only -m gpt-5.6-sol \
  --output-schema "$SCHEMA" \
  -c service_tier="fast" \
  -c model_reasoning_effort="high" \
  -C "$repoRoot" \
  "$(cat "$promptPath")"
# If service_tier=fast is rejected, retry without it.

# grok 4.6 — inline schema, not a path
grok -p "$(cat "$promptPath")" \
  --model grok-4.6 --effort high \
  --json-schema "$SCHEMA_INLINE" \
  --disallowed-tools Agent

# flash 3.7 — -p last; detach stdin; headless sandbox denies read_file
agy --sandbox --disable-slash-commands \
  --model gemini-3.7-flash-high \
  --output-format json --json-schema "$SCHEMA" \
  --print-timeout 10m \
  --dangerously-skip-permissions \
  -p "$(cat "$promptPath")" \
  < /dev/null
```

Inline the artifact when the CLI cannot read files. Timeout 10 minutes
per lane. 2–3 concurrent `claude -p` jobs are fine.

Parse into the schema. A dead lane is `reviewer_error`, not clean.
Dedup by file + nearby lines + category (or doc + section for
critique). Keep `found_by` as **model ids**. Write
`$out_dir/findings.json`. Assemble `review.md` / `critique.md` from
that JSON. The host reads summaries, never full transcripts.

## Max preflight

From any harness:

```bash
env -u ANTHROPIC_API_KEY claude -p --output-format text "/usage"
```

Parse `Current session: N%` and `Current week (all models): N%`. If
session ≥ 80% or week ≥ 80%, drop opus 5 and fable 5.1 lanes and say so.
If `/usage` fails, keep those lanes until a 429, then disable remaining
Claude-model lanes for the rest of the run.

## Quorum

A pass counts only if **at least two different models** returned, and
**at least one is not the host harness's home model** (grok 4.6 on
Grok, sol 5.6 on Codex, opus 5 / fable 5.1 on Claude, flash 3.7 on Agy).
Otherwise the pass is `incomplete`. Do not converge.

## Code-review lanes (review-loop, review-pr)

### Generals (unbiased "review this PR")

| Lane | Model |
|---|---|
| `review-sol` | sol 5.6 high |
| `review-grok` | grok 4.6 high |
| `review-flash` | flash 3.7 high |
| `review-opus` | opus 5 |

No `review-fable`.

### Composite specialists (one process per model)

| Lane | Model | Covers | Gate |
|---|---|---|---|
| `fable-deep` | fable 5.1 xhigh | goal-eval **and** simplicity, one prompt | Skip on `<50` non-sensitive. Re-run if the PR description **or** behavior hunks changed. |
| `flash-hygiene` | flash 3.7 high | failure-modes, tests, typing, comments | Pass 1 if any of those surfaces exist. Re-run if tests / comments / types / error-path files changed. |
| `grok-special` | grok 4.6 high | concurrency + idiomatic Rust | Rust half only if the diff touches `*.rs` or `Cargo.toml`. Concurrency half if the diff has async/await/spawn/tokio/JoinHandle or the run is sensitive. |
| `sol-special` | sol 5.6 high | contract + edge-cases | Contract if HTTP/RPC/SDK/on-chain/money/decimals appear. Edge-cases if `>500` lines **or** sensitive. |

Sensitive = auth, secrets, payment/financial, on-chain, or migrations.
**Sensitive always wins over size.**

### Adaptive pass 1

Measure hand-written lines (exclude lockfiles, generated, snaps, vendor,
fixtures) as in review-loop's size gate.

| Diff | Run |
|---|---|
| `<50` and not sensitive | `review-sol`, `review-grok`, `review-flash`. Add `flash-hygiene` if tests/comments/types are in the diff. Add `grok-special` only for the rust half if `*.rs`. No opus 5, no fable 5.1. |
| `50–500` and not sensitive | Four generals + `fable-deep` + `flash-hygiene` + gated `grok-special` / `sol-special` (no edge-cases). |
| `>500` **or** sensitive | Full set, including edge-cases. |

### Lean re-review (after a fix)

Always: host **fix-verifiers** (one per applied fix; host model only,
never a foreign CLI) and `review-sol`, `review-grok`, `review-flash`.

Conditionally:

- `review-opus` only if the host harness is Claude (native opus 5).
- `fable-deep` if the PR description or behavior hunks changed.
- composites if their gate's files changed (`cmp` the filtered
  path-list, not a semantic "slice").

Formatter-only deltas skip the pass. Cap 4 passes. Never end on a fix.
Convergence is a **lean** clean pass that also meets quorum.

A high/critical finding originally raised by opus 5 or fable 5.1 is
re-checked by that same **model** once, or the lean generals are given
that finding's text and told to verify the fix against it.

## Critique lanes (critique-loop)

Generals: `review-sol`, `review-grok`, `review-flash`, `review-opus`
(same skip rule on short docs).

`fable-deep`: goal-evaluation **and** grounding (fable 5.1; pass 1;
re-run if the stated goal or cited sources changed).

`flash-hygiene`: feasibility, clarity, style (flash 3.7).

`grok-special`: consistency + scope (grok 4.6).

`sol-special`: completeness (sol 5.6; its general already covers
broad).

Decision-changing findings are always Discuss.

## Plan critics (implement-issue, plan-issue)

Planner: fable 5.1 if the Claude harness is reachable (native child or
`claude -p --model claude-fable-5-1`); otherwise the host's current model. Say
which.

Critics, in parallel, one generalist each: opus 5, sol 5.6, grok 4.6.
No flash 3.7. If Claude is unreachable, drop the opus 5 critic and
label the run `portable`. If Claude is the host, label it `claude-host`.

Implementer and fixer stay on the host model (or a cheap same-harness
child).

## Shared prompt base (code review)

Each general gets the review-loop base prompt (correctness, concurrency,
security, conventions, maintainability, tests — no style nits).
Specialist composites get that base plus their focus paragraphs in
**one** prompt.

Inspector skill bodies still live at
`~/Github/dotagents/skills/<name>/SKILL.md` and are inlined into the
composite.

## Hard rules

1. Reports live on disk. The main session prints a two-line-per-finding
   summary and a path. Never pretty-print finding bodies into the host.
2. Verifiers, fixer, prompt-builder, report assembler: host model (or a
   same-harness child). Never a foreign CLI.
3. The host does not add its own review findings except lane errors.
4. `claude -p` is Max usage when logged in via claude.ai and no
   `ANTHROPIC_API_KEY` is set. Always `env -u ANTHROPIC_API_KEY`.
5. Do not impersonate a dropped **model**.
6. Never name a harness as if it were a model. Lanes are owned by
   grok 4.6, sol 5.6, opus 5, fable 5.1, or flash 3.7 — not by
   "Grok" / "Codex" / "Claude" / "Agy".
