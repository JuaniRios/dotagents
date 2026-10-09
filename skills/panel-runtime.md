# Panel runtime

Shared contract for every multi-model skill (`review-loop`, `review-pr`,
`critique-loop`, `council-eval`, `implement-issue`, `plan-issue`,
`implement-issue-stack`).
Read this file before spawning reviewers. Do not restate these tables
in those skills.

**Harnesses** (where the skill is running): `claude`, `codex`, `grok`,
`agy`. The current one is the **host**. Fan out with that host's
parallel primitive. Never wrap the panel in a second orchestrator.

**Models** (who reviews). Do not use a harness name as if it were a
model.

| Model | Effort | Home harness | Native on that harness | Foreign CLI (any other host) |
|---|---|---|---|---|
| Cursor Grok 4.7 | high | — | — | `cursor-agent -p --model grok-4.7-high` |
| composer 2.5 | standard | — | — | `cursor-agent -p --model composer-2.5` |
| sol 6.1 | high | codex | isolated Codex child, `-m gpt-6.1-sol` high | `CODEX_HOME=~/.codex codex exec --skip-git-repo-check --sandbox read-only -m gpt-6.1-sol` (ccx; ccxx fallback below) |
| opus 5.5 | (xhigh when the lane says so) | claude | isolated Claude child, `model: claude-opus-5-5` | `env -u ANTHROPIC_API_KEY claude -p --model claude-opus-5-5` |
| flash 3.7 | high | agy | isolated Agy child, `gemini-3.7-flash-high` | `agy -p --model gemini-3.7-flash-high` |

A model is **native** only on its home harness, and only as an
**isolated child pinned to that model**, not the babysitter. On any
other harness, reach it through that model's foreign CLI. Never
`claude -p` when the host is Claude. Same for `codex exec` / `agy -p`
on their home harnesses.

Do not pick opus 5.5 through the Agy CLI (Agy lists Claude
model ids; those are not this panel's Claude path).

Cursor is not a supported host harness in this contract. Cursor Grok 4.7 and
composer 2.5 are CLI-only lanes in every multi-model panel, using the exact
account-verified ids above so both consume the Cursor subscription. Keep them
as separate lanes: they share a harness and billing pool, but they are
different models. Never replace Cursor Grok with the direct `grok` CLI; that
would charge the separate Grok/xAI account.

## Availability and substitutes

**Preflight once per run, before pass 1**, in parallel, 30 seconds each.
A model is unavailable when its check fails, its CLI is missing, or the
Max preflight below drops it:

| Model | Check (unavailable when it fails or prints the text) |
|---|---|
| opus 5.5 | Max preflight below |
| sol 6.1 | `codex login status` exits 0 |
| Cursor Grok 4.7, composer 2.5 | `cursor-agent status` prints `Logged in` |
| flash 3.7 | `agy models` exits 0 (it fails fast when logged out; a lane would sit at a login prompt) |

Never start a lane on an unavailable model. **Run it on the first
available substitute instead**, with the same lane prompt and focus:

| Unavailable | Substitutes, in order |
|---|---|
| flash 3.7 | composer 2.5, sol 6.1, opus 5.5 |
| composer 2.5 | flash 3.7, sol 6.1, opus 5.5 |
| Cursor Grok 4.7 | sol 6.1, opus 5.5, composer 2.5 |
| sol 6.1 | Cursor Grok 4.7, opus 5.5, composer 2.5 |
| opus 5.5 | sol 6.1, Cursor Grok 4.7, composer 2.5 |

A substituted lane is labeled and recorded as the model that ran it
(`flash-hygiene (on composer 2.5)`, `found_by: ["composer-2.5"]`), never as
the missing model, and the report lists each substitution. The same
substitution applies when a lane fails fast twice during the run (below).
If no substitute is available, drop the lane and say so. Never wait for a
model's usage limit or cooldown to reset: no `sleep`, no polling loop, no
re-running the preflight to see whether it came back. A model that is out
of usage is unavailable for the whole run. A missing Cursor
CLI makes both Cursor models unavailable; never fall back to the direct
`grok` command.

**Retries and stragglers:**

- A lane that fails fast (an error, a bad parse) gets one retry, then
  moves to its substitute for the rest of the run.
- A lane that hits its timeout is not retried in that pass: record
  `reviewer_error` (timeout) and continue.
- Once every other lane of a pass has returned, wait at most **3 more
  minutes** for the rest. Then stop them, record `reviewer_error`
  (straggler), and continue with the pass. Do not substitute a straggler
  in that pass; if the same model straggles twice, substitute it from the
  next pass.

## Wrapper

Every lane is a host child that either *is* the pinned model or pipes
to that model's CLI.

Inputs: `promptPath`, `targetPath`, `repoRoot`, `schemaPath`.
Write stdout to `$out_dir/raw-<lane>.json` (or `.txt`).

```bash
SCHEMA="${schemaPath:-$HOME/Github/dotagents/skills/schemas/review-finding.json}"
SCHEMA_INLINE=$(cat "$SCHEMA")

# opus 5.5 — Max plan. Always strip a Console key.
env -u ANTHROPIC_API_KEY claude -p --model claude-opus-5-5 \
  --output-format json --json-schema "$SCHEMA_INLINE" \
  "$(cat "$promptPath")"

# sol 6.1 — file schema (every property is already in `required`)
# Account: ccx (CODEX_HOME=~/.codex) by default. If its output says
# "hit your usage limit" and ~/.codex-2 exists, rerun the same command once
# with ccxx (CODEX_HOME=~/.codex-2). This account switch does not use the
# lane's one retry. Otherwise sol 6.1 is unavailable: substitute (above).
# ccx/ccxx are nushell functions, so set CODEX_HOME explicitly from bash.
# --skip-git-repo-check: critiques and plans run outside a git repo.
CODEX_HOME="$HOME/.codex" codex exec --skip-git-repo-check --sandbox read-only -m gpt-6.1-sol \
  --output-schema "$SCHEMA" \
  -c service_tier="fast" \
  -c model_reasoning_effort="high" \
  -C "$repoRoot" \
  "$(cat "$promptPath")"
# If service_tier=fast is rejected, retry without it.

# Cursor Grok 4.7 and composer 2.5 through the Cursor subscription.
# Cursor JSON is an envelope and has no schema flag.
CURSOR_PROMPT="$(cat "$promptPath")

Return only one JSON object matching this schema; no markdown fences or commentary:
$SCHEMA_INLINE"

cursor-agent -p --output-format json --mode ask --trust \
  --sandbox enabled --workspace "$repoRoot" \
  --model grok-4.7-high \
  "$CURSOR_PROMPT"

cursor-agent -p --output-format json --mode ask --trust \
  --sandbox enabled --workspace "$repoRoot" \
  --model composer-2.5 \
  "$CURSOR_PROMPT"

# flash 3.7 — -p last; detach stdin; headless sandbox denies read_file
agy --sandbox --disable-slash-commands \
  --model gemini-3.7-flash-high \
  --output-format json --json-schema "$SCHEMA" \
  --print-timeout 10m \
  --dangerously-skip-permissions \
  -p "$(cat "$promptPath")" \
  < /dev/null
```

For both Cursor lanes, save stdout as `raw-<lane>-envelope.json`, extract
`.result` with `jq -er` into `raw-<lane>.json`, then validate against the
schema. These exact model IDs were verified with `cursor-agent models`. Always
pass them to `cursor-agent`, never to the direct `grok` CLI, which bills the
separate xAI account. A parse or validation failure
gets the same one retry as any other lane, then moves to its substitute.

Inline the artifact when the CLI cannot read files. Timeout 10 minutes
per lane, with the straggler rule above. 2–3 concurrent `claude -p` jobs
are fine.

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
session ≥ 80% or week ≥ 80%, opus 5.5 is unavailable: substitute its
lanes and say so. If `/usage` fails, keep those lanes until a 429, then
substitute the remaining Claude-model lanes for the rest of the run.

## Quorum

A pass counts only if **at least two different models** returned, and
**at least one is not the host harness's home model** (treat Cursor Grok 4.7
as host-equivalent on Grok; sol 6.1 on Codex; opus 5.5 on Claude;
flash 3.7 on Agy).
Otherwise the pass is `incomplete`. Do not converge.

## Code-review lanes (review-loop, review-pr)

### Generals (unbiased "review this PR")

| Lane | Model |
|---|---|
| `review-sol` | sol 6.1 high |
| `review-grok` | Cursor Grok 4.7 high |
| `review-flash` | flash 3.7 high |
| `review-opus` | opus 5.5 |
| `review-composer` | composer 2.5 standard |

The Claude general and deep specialist use the same pinned model with
different prompts.

### Specialist lanes

Composite lanes combine related inspectors into one process per model.
`flash-config` stays separate because its rollout matrix is independently gated.

| Lane | Model | Covers | Gate |
|---|---|---|---|
| `opus-deep` | opus 5.5 xhigh | goal-eval, simplicity, **and** approach (`approach-inspector`), one prompt | On `<50` non-sensitive, run only the approach part, and only when an approach trigger holds. Re-run if the PR description **or** behavior hunks changed, or the approach part alone if an approach trigger changed. |
| `flash-hygiene` | flash 3.7 high | failure-modes, tests, typing, comments | Pass 1 if any of those surfaces exist. Re-run if tests / comments / types / error-path files changed. |
| `flash-spec` | flash 3.7 high | spec-sync (`spec-sync-inspector`) | Run if the repo has a spec (`SPEC.md`, `docs/spec*`, `docs/architecture*`, `adrs/`, `docs/adr*`) and the diff changes behavior or structure, or edits those docs. Re-run if behavior hunks or those docs changed. |
| `flash-config` | flash 3.7 high | config-schema and deployment compatibility | Run if deployed config, config parsing/validation, schema versions, or release/deploy checks changed. Re-run if any of those paths changed. |
| `grok-special` | Cursor Grok 4.7 high | concurrency + idiomatic Rust | Rust half only if the diff touches `*.rs` or `Cargo.toml`. Concurrency half if the diff has async/await/spawn/tokio/JoinHandle or the run is sensitive. |
| `sol-special` | sol 6.1 high | contract + edge-cases | Contract if HTTP/RPC/SDK/on-chain/money/decimals appear. Edge-cases if `>500` lines **or** sensitive. |
| `sol-paths` | sol 6.1 high | error paths and lifecycle states (`error-path-inspector`) | Run if the diff changes error handling, retries, polling, persisted state, status enums, events, or state transitions, and always when sensitive. Re-run if behavior hunks changed. |
| `grok-runbook` | Cursor Grok 4.7 high | runbooks and operational scripts (`runbook-inspector`) | Run if the diff touches a runbook, `DEPLOY.md`, rollout, rollback, or recovery docs, `docs/ops*`, incident guides, or a one-off operational script. Re-run if any of those changed. |

Sensitive = auth, secrets, payment/financial, on-chain, or migrations.
**Sensitive always wins over size.**

Approach trigger = any of:

- a dependency surface changed: manifests (`Cargo.toml`, `package.json`,
  `pyproject.toml`, `go.mod`, `flake.nix` inputs), Dockerfiles, CI
  workflows, or new imports of an external crate, package, or service API;
- the branch is a follow-up in a stack (its parent is not trunk);
- the touched files had 3 or more fix commits in the last 30 days;
- the diff reads another service's API, database, or logs;
- the repo is public and the diff adds data or config.

Small follow-ups are where "patching the patch" shows up, so they must not
be skipped.

`sol-paths` and `grok-runbook` enumerate instead of reading the PR as a whole:
every exit and state, every runbook step. General lanes skim past these narrow
bugs; CodeRabbit caught several in 2026-10 that the full panel missed. Never
skip them on size alone.

The approach part needs web access to cite upstream sources and `gh` to
read other repos. A native Claude child already has both. On the foreign
CLI, add `--allowedTools "WebSearch WebFetch Read Grep Glob Bash(gh:*) Bash(git:*) Bash(rg:*)"`
to the `opus-deep` call only. Without web access it checks local evidence
and lists the rest as unchecked.

### Adaptive pass 1

Measure hand-written lines (exclude lockfiles, generated, snaps, vendor,
fixtures) as in review-loop's size gate.

| Diff | Run |
|---|---|
| `<50` and not sensitive | `review-sol`, `review-grok`, `review-composer`, `review-flash`. Add `flash-hygiene` if tests/comments/types are in the diff. Add `sol-paths` and `grok-runbook` if their gates hold. Add `flash-config` if its config surfaces changed. Add `grok-special` only for the rust half if `*.rs`. Add `flash-spec` if its gate holds. Add `opus-deep` with only the approach part if an approach trigger holds. Otherwise no opus 5.5. |
| `50–500` and not sensitive | Five generals + `opus-deep` + `flash-hygiene` + gated `flash-spec` / `flash-config` / `grok-special` / `sol-special` (no edge-cases) / `sol-paths` / `grok-runbook`. |
| `>500` **or** sensitive | Full set, including edge-cases. |

### Lean re-review (after a fix)

Always: host **fix-verifiers** (one per applied fix; host model only,
never a foreign CLI) and `review-sol`, `review-grok`, `review-composer`,
`review-flash`.

Conditionally:

- `review-opus` only if the host harness is Claude (native opus 5.5).
- `opus-deep` if the PR description or behavior hunks changed; only its
  approach part if just an approach trigger changed.
- `flash-spec` if behavior hunks or spec docs changed.
- `flash-config` if deployed config, config schema/validation, or release/deploy
  check paths changed.
- `sol-paths` if behavior hunks changed and its gate holds.
- `grok-runbook` if runbook or operational-script paths changed.
- composites if their gate's files changed (`cmp` the filtered
  path-list, not a semantic "slice").

Formatter-only deltas skip the pass. Cap 4 passes. Never end on a fix.
Convergence is a **lean** clean pass that also meets quorum.

A high/critical finding originally raised by opus 5.5 is
re-checked by that same **model** once, or the lean generals are given
that finding's text and told to verify the fix against it.

## Blocker verification (review-pr, publish-review)

A published review blocks a merge only on a **verified blocker**: a
`critical` or `high` finding that at least two different models stand
behind. One model's word never blocks.

Severity is strict; when in doubt, pick the lower one:

| Schema | Posted as | Meaning |
|---|---|---|
| `critical` | `critical:` | A likely way to lose funds, leak a secret, or break production on a normal path. |
| `high` | `should fix:` | A plausible path to losing money or to wrong production behavior. A scenario that needs several unlikely events at once is not plausible. |
| `medium`, `low` | `minor:` | A real defect that needs an unlikely chain of events, or has a cheap workaround. |
| `nit` | `nit:` | Style, naming, or clarity only. |

After dedup, for each `critical` or `high` finding:

- **Two or more models in `found_by`:** it keeps its severity.
- **One model in `found_by`:** run two **blocker verifiers**, on two
  different models, both different from the finder. Give each the
  finding, the code, and the scenario, and ask for its own verdict and
  severity without telling it the finder's. Record both in the finding
  as `verified_by: [{model, severity, why}]` in `findings.json`. The
  finding blocks only if both rate it `critical` or `high`. Otherwise it
  takes the lower severity of the two, or is dismissed as invalid if
  they show it is not a defect.
- If fewer than two eligible models are available, the finding cannot
  be verified and the review is `incomplete`. Never publish it as a
  blocker, and never approve past it.

Use each model's native child or foreign CLI from the table above,
read-only, with the same one retry. Verifiers answer with the same
finding schema.

## Critique lanes (critique-loop)

Generals: `review-sol`, `review-grok`, `review-composer`, `review-flash`, `review-opus`
(same skip rule on short docs).

`opus-deep`: goal-evaluation, grounding, **and** approach (opus 5.5;
pass 1; re-run if the stated goal or cited sources changed). The approach
part applies `approach-inspector`'s plan section: every new component
states its home and why, checked against the spec, the owning system, and
any planned replacement.

`flash-hygiene`: feasibility, clarity, style (flash 3.7).

`grok-special`: consistency + scope (Cursor Grok 4.7).

`sol-special`: completeness (sol 6.1; its general already covers
broad).

Decision-changing findings are always Discuss.

Lean re-critiques always run `review-sol`, `review-grok`, and
`review-composer` plus host fix-verifiers. Re-run the other general or
specialist lanes only when their focus surface changed. Never end on a fix.

## Plan critics (implement-issue, plan-issue)

Planner: opus 5.5 if the Claude harness is reachable (native child or
`claude -p --model claude-opus-5-5`); otherwise the host's current model. Say
which.

Critics, in parallel, one generalist each: opus 5.5, sol 6.1, Cursor Grok 4.7,
and composer 2.5. The opus 5.5 critic also applies `approach-inspector`'s
plan section. No flash 3.7, except as a substitute. If Claude is
unreachable, substitute the opus 5.5 critic and label the run `portable`. If Claude is the host, label it `claude-host`.

Implementer and fixer stay on the host model (or a cheap same-harness
child).

## Council lanes (council-eval)

One generalist each: opus 5.5, sol 6.1, Cursor Grok 4.7, composer 2.5,
and flash 3.7. Council drops an unavailable model instead of substituting it: its point is one
answer per distinct model. No specialists or re-review. Use the shared wrappers
and Max preflight above; `council-eval` owns only its artifact prompt and
deterministic report.

## Shared prompt base (code review)

Before building prompts, record the visibility of the target repo and of
every repo the diff writes data into (`gh repo view <repo> --json
visibility`). Put it at the top of every lane's prompt. In a public repo,
any lane flags business-sensitive data the diff adds (spreads, pricing or
strategy settings, internal hostnames, wallet roles, infrastructure
layout) as a `high` security finding.

Each general gets the review-loop base prompt (correctness, concurrency,
security, conventions, maintainability, tests — no style nits).
Specialist composites get that base plus their focus paragraphs in
**one** prompt.

Inspector skill bodies still live at
`~/Github/dotagents/skills/<name>/SKILL.md` and are inlined into the
composite or focused specialist lane.

## Hard rules

1. Reports live on disk. The main session prints a two-line-per-finding
   summary and a path. Never pretty-print finding bodies into the host.
2. Verifiers, fixer, prompt-builder, report assembler: host model (or a
   same-harness child). Never a foreign CLI. The one exception is the
   blocker verifiers above, which must run on models other than the
   finder's.
3. The host does not add its own review findings except lane errors.
4. `claude -p` is Max usage when logged in via claude.ai and no
   `ANTHROPIC_API_KEY` is set. Always `env -u ANTHROPIC_API_KEY`.
5. Do not impersonate an unavailable **model**: a substitute runs under
   its own name.
6. Never name a harness as if it were a model. Lanes are owned by
   Cursor Grok 4.7, composer 2.5, sol 6.1, opus 5.5, or flash 3.7 —
   not by "Cursor" / "Grok" / "Codex" / "Claude" / "Agy".
