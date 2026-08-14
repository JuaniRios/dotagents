# Panel runtime

Shared contract for every multi-lab skill (`review-loop`, `review-pr`,
`critique-loop`, `implement-issue`, `plan-issue`, `implement-issue-stack`).
Read this file before spawning reviewers. Do not restate these tables in
those skills.

The host is whichever harness started the skill (Claude, Codex, Grok, or
Antigravity). Fan out with **this host's** parallel primitive. Never wrap
the panel in a second orchestrator.

## Providers

| Id | Product | Native when host is | Foreign CLI |
|---|---|---|---|
| opus | Claude Opus | Claude | `env -u ANTHROPIC_API_KEY claude -p --model opus` |
| fable | Claude Fable | Claude | `env -u ANTHROPIC_API_KEY claude -p --model fable` |
| sol | gpt-5.6-sol | Codex | `codex exec --sandbox read-only -m gpt-5.6-sol` |
| grok | Grok | Grok | `grok -p` |
| agy | Gemini 3.7 Flash High | Antigravity | `agy -p --model gemini-3.7-flash-high` |

Same-product lanes are **isolated subagents pinned to that model**, not
the babysitter conversation. Never `claude -p` when the host is Claude
(native child instead). Same for `grok -p` / `codex exec` / `agy -p` on
their own hosts.

Do not use Agy's listed Claude/GPT models as a Fable or Opus substitute.

If a CLI is missing or fails after one retry, **drop that lane and say
so**. Do not run the work on the host and still label it as that lab.

## Wrapper

Every lane is a host subagent that either *is* the reviewer or pipes to
that lab's CLI. Same inputs for every lab:

- `promptPath`, `targetPath` (diff or document), `repoRoot`, `schemaPath`
- write stdout to `$out_dir/raw-<lane>.json` (or `.txt` if the CLI is text)

CLI adapters (schema file:
`~/Github/dotagents/skills/schemas/review-finding.json`):

```bash
SCHEMA="$HOME/Github/dotagents/skills/schemas/review-finding.json"
SCHEMA_INLINE=$(cat "$SCHEMA")

# opus / fable — Max plan. Always strip a Console key.
env -u ANTHROPIC_API_KEY claude -p --model <opus|fable> \
  --output-format json --json-schema "$SCHEMA_INLINE" \
  "$(cat "$promptPath")"

# sol — file schema; every property must be in `required` (already true of SCHEMA)
codex exec --sandbox read-only -m gpt-5.6-sol \
  --output-schema "$SCHEMA" \
  -c service_tier="fast" -C "$repoRoot" \
  "$(cat "$promptPath")"
# If service_tier=fast is rejected, retry without it.

# grok — inline schema, not a path
grok -p "$(cat "$promptPath")" \
  --json-schema "$SCHEMA_INLINE" \
  --disallowed-tools Agent

# agy — -p last; detach stdin; headless sandbox denies read_file
agy --sandbox --disable-slash-commands \
  --model gemini-3.7-flash-high \
  --output-format json --json-schema "$SCHEMA" \
  --print-timeout 10m \
  --dangerously-skip-permissions \
  -p "$(cat "$promptPath")" \
  < /dev/null
```

Inline the artifact in the prompt when the CLI cannot read files (Agy
without skip-permissions). Timeout 10 minutes per lane. 2–3 concurrent
`claude -p` jobs are fine; do not serialize them for fear of 429s.

Parse each result into the schema. A dead lane is `reviewer_error`, not
clean. Dedup by file + nearby lines + category (or doc + section for
critique). Keep `found_by`. Write `$out_dir/findings.json`. Assemble
`$out_dir/review.md` (or `critique.md`) from that JSON — no synthesis
agent. The host reads summaries, never full transcripts.

## Max preflight

From any host:

```bash
env -u ANTHROPIC_API_KEY claude -p --output-format text "/usage"
```

Parse `Current session: N%` and `Current week (all models): N%`. If
session ≥ 80% or week ≥ 80%, drop `review-opus` and `fable-deep` and say
so. If `/usage` fails, keep Claude lanes until a 429, then disable all
remaining Claude lanes for the rest of the run.

## Quorum

A pass counts only if **at least two different labs** returned, including
**at least one non-host lab**. Otherwise the pass is `incomplete`, not
clean. Do not converge.

## Code-review lanes (review-loop, review-pr)

### Generals (unbiased "review this PR")

| Lane | Provider |
|---|---|
| `review-sol` | sol |
| `review-grok` | grok |
| `review-agy` | agy |
| `review-opus` | opus |

No `review-fable`.

### Composite specialists (one process per lab)

| Lane | Provider | Covers | Gate |
|---|---|---|---|
| `fable-deep` | fable | goal-eval **and** simplicity, one prompt | Skip on `<50` non-sensitive. Re-run if the PR description **or** behavior hunks changed. |
| `agy-hygiene` | agy | failure-modes, tests, typing, comments | Pass 1 if any of those surfaces exist. Re-run if tests / comments / types / error-path files changed. |
| `grok-special` | grok | concurrency + idiomatic Rust | Rust half only if the diff touches `*.rs` or `Cargo.toml`. Concurrency half if the diff has async/await/spawn/tokio/JoinHandle or the run is sensitive. |
| `sol-special` | sol | contract + edge-cases | Contract if HTTP/RPC/SDK/on-chain/money/decimals appear. Edge-cases if `>500` lines **or** sensitive. |

Sensitive = auth, secrets, payment/financial, on-chain, or migrations.
**Sensitive always wins over size.**

### Adaptive pass 1

Measure hand-written lines (exclude lockfiles, generated, snaps, vendor,
fixtures) as in review-loop's size gate.

| Diff | Run |
|---|---|
| `<50` and not sensitive | `review-sol`, `review-grok`, `review-agy`. Add `agy-hygiene` if tests/comments/types are in the diff. Add `grok-special` only for the rust half if `*.rs`. No Opus, no Fable. |
| `50–500` and not sensitive | Four generals + `fable-deep` + `agy-hygiene` + gated `grok-special` / `sol-special` (no edge-cases). |
| `>500` **or** sensitive | Full set, including edge-cases. |

### Lean re-review (after a fix)

Always: host **fix-verifiers** (one per applied fix; host only, never
CLI) and `review-sol`, `review-grok`, `review-agy`.

Conditionally:

- `review-opus` only if the host is Claude (native).
- `fable-deep` if the PR description or behavior hunks changed.
- composites if their gate's files changed (`cmp` the filtered
  path-list, not a semantic "slice").

Formatter-only deltas skip the pass. Cap 4 passes. Never end on a fix.
Convergence is a **lean** clean pass that also meets quorum.

A high/critical finding originally raised by Opus or Fable is
re-checked by that same lab once (one targeted prompt), or the lean
generals are given that finding's text and told to verify the fix
against it.

## Critique lanes (critique-loop)

Generals: `review-sol`, `review-grok`, `review-agy`, `review-opus`
(same skip rule as above on short docs).

Fable: one `fable-deep` covering goal-evaluation **and** grounding
(pass 1; re-run if the stated goal or cited sources changed).

Agy: one hygiene pass (feasibility, clarity, style).

Grok: consistency + scope.

Sol: completeness (and broad is already its general).

Decision-changing findings are always Discuss.

## Plan critics (implement-issue, plan-issue)

Planner: Fable if Claude is reachable (native or `claude -p --model
fable`); otherwise the host. Say which.

Critics, in parallel, one generalist each: Opus, Sol, Grok. Skip Agy.
If Claude is unreachable, drop the Opus critic and say the plan used
the portable tier.

Label the result `claude-host` vs `portable` so runs are comparable.

Implementer and fixer stay on the host (or a cheap same-host child).

## Shared prompt base (code review)

Each general gets the review-loop base prompt (correctness, concurrency,
security, conventions, maintainability, tests — no style nits).
Specialist composites get that base plus their focus paragraphs,
concatenated into **one** prompt per process.

Inspectors that used to be separate files (`test-inspector`,
`idiomatic-rust-inspector`, …) are still those skill bodies, inlined
into the composite prompt. Resolve them from
`~/Github/dotagents/skills/<name>/SKILL.md`.

## Hard rules

1. Reports live on disk. The main session prints a two-line-per-finding
   summary and a path. Never pretty-print finding bodies into the host.
2. Verifiers, fixer, prompt-builder, report assembler: host (or a
   same-host child). Never CLI.
3. The host does not add its own review findings except lane errors.
4. `claude -p` is Max usage when logged in via claude.ai and no
   `ANTHROPIC_API_KEY` is set. Always `env -u ANTHROPIC_API_KEY`.
5. Do not impersonate a dropped lab.
