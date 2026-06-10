# Making /review-loop run in under 30 minutes

**Date:** 2026-06-09
**Trigger:** the review-loop run on `st0x.liquidity` branch
`06-09-graphite_ci_optimization` (208-line CI workflow diff, 8 findings,
6 fixes) took ~53 minutes wall-clock from invocation to final summary.
**Question:** can it converge in under 30 minutes without losing review
quality?

**Answer: yes — comfortably.** The measured profile shows the multi-agent
panel is *not* the main cost; the orchestration around it is. Stacking the
changes below projects a similar run at **~22–25 minutes**, with the
biggest wins coming from (1) removing barriers inside the panel workflow,
(2) parallelizing/tightening the main-loop fix phase, (3) skipping the
re-review of formatter-only deltas, and (4) turning down Codex lane
latency knobs that exist today as config flags.

---

## 1. Where the hour actually went (measured)

Reconstructed from workflow journals, agent transcript mtimes, and task
notifications:

| Phase | Wall-clock | Share |
|---|---|---|
| Setup: preflight, scope, prompt-file construction, 2 failed launches | ~3 min | 6% |
| **Review panel workflow** (9 lanes, 8 verifiers, synthesis) | **14.5 min** | 27% |
| **Main loop: parse results, triage, verify upstream action, apply 9 edits, compile gate** | **~21 min** | **40%** |
| Delta re-review pass 1 (6 fix-verifiers + sweep) | ~4 min | 8% |
| /ci (nix shells, check/clippy/fmt, pre-commit ×2) | ~4 min | 8% |
| Delta re-review pass 2 — over a **single whitespace character** | ~5 min | 9% |
| Wrap-up summary | ~2 min | 4% |

### Panel internals (867s total, from per-agent timing)

| Lane | Duration |
|---|---|
| typing-inspector / rust-inspector / test-inspector | 9–18s |
| sonnet (error paths) | 98s |
| contract-inspector | 177s |
| fable-a (concurrency) | 274s |
| fable-b (goal evaluation) | 365s |
| **codex-a / codex-b** | **421s / 463s** |
| Verify phase (8 agents, started at +463s behind a barrier) | most 15–60s, one straggler 301s |
| Synthesize (started +765s) | 102s |

Three structural problems jump out:

1. **The Verify barrier.** All 8 verifiers waited for the slowest lane
   (codex-b, 463s) even though 7 of 9 lanes were done by +365s and the
   three inspectors by +18s. `parallel()` between phases is a barrier the
   workflow doesn't need — verification of a lane's findings only depends
   on that lane.
2. **Synthesis on the critical path.** The triage table needs only the
   findings JSON; the markdown report is an audit artifact. Yet the
   workflow (and the main loop) waited 102s for synthesis before triage
   began.
3. **Codex lanes are 1.3–25× slower than every other lane** and gate the
   whole Review phase.

And the two biggest costs were outside the panel entirely: 21 minutes of
serial main-loop triage/fix work, and a 5-minute single-agent re-review of
a one-character yamlfmt change (the sweep agent cold-read the full diff,
project docs, and sources to evaluate a whitespace fix).

---

## 2. What the research found (verified, cited)

A deep-research pass (23 sources fetched, 114 claims extracted, 25
adversarially verified, 3 refuted) on Codex/Claude latency levers,
competing tools, and published multi-agent patterns:

### Codex CLI levers (all config-only, no code changes)

- `model_reasoning_effort = minimal | low | medium | high | xhigh` —
  per-run via `-c`; review lanes currently run at the default. Confirmed
  in the [Codex config reference](https://developers.openai.com/codex/config-reference).
- `service_tier = "fast"` (maps to API `priority`) — server-side faster
  serving. GPT-5.5 **Fast mode**: 1.5× faster tokens at 2.5× credit cost,
  ChatGPT sign-in only (not API-key auth)
  ([Codex speed docs](https://developers.openai.com/codex/speed)).
- GPT-5.5 itself uses ~40% fewer tokens than 5.4 at matched per-token
  latency ([OpenAI](https://openai.com/index/introducing-gpt-5-5/),
  corroborated by llm-stats.com) — we already use 5.5; don't downgrade.
- `codex exec resume --last` / `resume <SESSION_ID>` lets a follow-up turn
  continue the reviewer's session
  ([noninteractive docs](https://developers.openai.com/codex/noninteractive)),
  so a Codex-found finding could be verified inside the same session
  instead of a fresh agent re-ingesting the diff.

### Claude Code levers

- **Fast mode** (`/fast`): Opus up to 2.5× faster output at higher
  per-token cost, same weights; Opus-only — no effect on Sonnet/Haiku/Fable
  lanes ([fast-mode docs](https://code.claude.com/docs/en/fast-mode)).
  Useful for a synthesis/sweep lane if switched to Opus; research preview,
  pricing subject to change.
- **Per-agent model/effort routing** is native: subagent `model` +
  `effort` frontmatter, and Workflow per-stage `model` overrides
  ([sub-agents](https://code.claude.com/docs/en/sub-agents),
  [workflows](https://code.claude.com/docs/en/workflows)). The
  cheap-reviewers / strong-judge pattern is officially recommended.
- **Workflow overheads**: 16-concurrent-agent cap; non-allowlisted
  shell/web/MCP calls pause the run mid-flight (pre-allowlist before
  starting); every subagent starts cold and pays a context-gathering tax.

### Production architectures

- **Cloudflare** runs a 7-specialist-panel + coordinator-judge review at a
  **3m39s median** across 48,095 MRs/30 days
  ([blog](https://blog.cloudflare.com/ai-code-review/)). Transferable
  techniques: (a) **tiered model assignment** — strong models only for the
  coordinator's dedup/false-positive filtering, mid-tier for reviewer
  lanes; (b) **85.7% prompt-cache hit rate** by writing shared MR context
  to a disk file all reviewers read, plus identical base prompts across
  runs; (c) **adaptive panel sizing**: ≤10-line diffs get 2 agents,
  ≤100-line get 4, only >100-line/security-sensitive diffs get the full 7+
  panel. Caveat: first-party telemetry, and no per-finding adversarial
  verification stage.
- **CodeRabbit** independently converges on parallel specialized agents
  including a dedicated verification agent
  ([architecture docs](https://docs.coderabbit.ai/overview/architecture)) —
  the review+verify shape is validated, not exotic.
- **No competitor publishes verifiable wall-clock numbers** (CodeRabbit
  CLI, Greptile, Qodo, Graphite Diamond, Cursor Bugbot, Copilot) — the
  comparison rests on Cloudflare/CodeRabbit architecture docs.

### Benchmarks on panel size and model choice

- Agent count dominates latency: single-agent 7.7 min vs sequential
  three-agent chain 48.5 min for ~identical accuracy; a two-agent +
  verifier configuration was the accuracy-per-latency optimum
  ([arXiv 2505.02133](https://arxiv.org/pdf/2505.02133)). Caveat: measured
  on *sequential* chains, so the multiplier overstates the cost of our
  *parallel* panel — but the "minimal panel + one strong verification
  pass" conclusion transfers.
- The most expensive model is not the best reviewer: GPT-5.2 beat Opus 4.6
  on a 50-real-PR benchmark at 40% of the cost
  ([Factory.ai](https://factory.ai/news/code-review-benchmark); vendor
  benchmark, predates GPT-5.5/Opus 4.7+, gap within judge-swap variance).
- **Refuted/unresolved:** all three claims on "single strong model vs
  multi-model panel" accuracy were killed in verification — that tradeoff
  is genuinely open. **Speculative fix generation during review produced
  no surviving evidence.** Don't bet on either.

---

## 3. Recommendations, ranked by projected saving

### R1. Restructure the panel workflow: pipeline verify, de-barrier synthesis (~6 min saved)

Replace the `parallel(lanes) → parallel(verify) → synthesize` barriers
with `pipeline()`: each lane's findings go to verification as soon as that
lane returns (cross-lane dedup becomes verify-side: skip a verifier if an
equivalent finding was already verified). Return findings to the main loop
the moment the last verification lands; run synthesis **concurrently with
main-loop triage** (it's an audit artifact, not an input). Measured
critical path drops from 866s to ~500s.

### R2. Cut the main-loop fix phase (~8–10 min saved)

The 21-minute block decomposes into: result parsing, re-reading sources,
upstream verification (`ls-remote`/`curl` of the pinned action), 9 Edit
calls, long user-facing prose between steps. Changes:

- **Fan out independent fixes.** After triage, dispatch fix application as
  a small workflow — one agent per finding-cluster (cluster = findings
  touching the same file region), `isolation: 'worktree'` only if clusters
  overlap. Main loop reviews the combined patch instead of authoring it.
  For ≤2 trivial fixes, stay in the main loop.
- **Move "verify the finding against upstream" into the verify phase.**
  The 301s verifier straggler already curl-ed the action source; the main
  loop then re-did similar research. Have verifiers emit the evidence the
  fixer needs (e.g. "pin to SHA `9bc969a`, contract confirmed") so the fix
  phase doesn't repeat it.
- **Defer narrative.** One compact triage table before fixing, full prose
  only in the final summary.

### R3. Skip re-review of formatter-only deltas (~5 min saved)

New rule for step 12: if the post-/ci delta consists solely of changes
applied by a formatter/hook and that formatter now passes, the delta is
verified by construction — do not spawn a review pass over it. Our run
spent 5.1 minutes having a Fable agent cold-read everything to judge two
spaces before a comment.

### R4. Turn down the Codex lanes (~2–3 min saved)

- Add `-c model_reasoning_effort="medium"` (or `low` for re-review passes)
  to the `codex exec` invocation — review-with-structured-output doesn't
  need default-effort deliberation for sub-500-line diffs.
- If signed in via ChatGPT, add `service_tier = "fast"` for 1.5× token
  speed (2.5× credit cost — acceptable for two lanes).
- Review phase gate drops from ~463s toward the Fable-lane ~365s.

### R5. Adaptive panel sizing (Cloudflare tiering) (~1–3 min + cost)

- **< 50 changed lines:** 3 lanes (fable-b goal-eval, one codex broad,
  contract-inspector) + verify. No synthesis report unless findings ≥ 3.
- **50–500 lines:** current 9 lanes minus one codex lane (codex-a and
  codex-b overlapped heavily — every codex-a finding this run was also
  found by others).
- **> 500 lines / security-sensitive paths:** full panel.
- Keep all four inspectors at every tier — they cost 9–18s each.

### R6. Overlap /ci with the first delta pass (~3–4 min saved)

The delta re-review and /ci both consume the fixed working tree and don't
interact. Launch /ci's parallel steps and the delta workflow in the same
breath; gate convergence on both. Also prewarm the nix dev shells
(`nix develop .#ci-backend -c true` in the background) during the panel.

### R7. Static prompt assets + shared context file (setup ~2 min + cache wins)

The base prompt and focus paragraphs are 95% static per repo. Ship them as
files in the skill directory; per-run, write only a small context file
(diff path, docs paths, PR description) that every lane reads —
Cloudflare's shared-context-file pattern, which also maximizes prompt-cache
hits across agents on identical base prompts. Eliminates the multi-step
prompt-construction Bash round trips (and the two failed launches we paid
for hand-rolling args — already fixed separately with defensive parsing).

### R8. Pre-allowlist agent commands

Any non-allowlisted shell/web call from a workflow agent pauses the run
until answered. Allowlist `codex`, `git`, `gh`, `curl`/WebFetch for
verifier lanes before launching.

### Projected timeline after R1–R8 (same diff, same findings)

| Phase | Now | Projected |
|---|---|---|
| Setup | 3 min | 1 min |
| Panel | 14.5 min | ~7–8 min |
| Triage + fixes | 21 min | ~8–10 min |
| Delta 1 ∥ /ci | 8 min | ~4–5 min |
| Delta 2 (formatter-only) | 5 min | 0 |
| Wrap-up | 2 min | 1 min |
| **Total** | **~53 min** | **~21–25 min** |

---

## 4. What not to do

- **Don't collapse to a single strong model.** The panel's diversity paid
  off this run (the dead `predicate-quantifier` filter was found by 6
  lanes, but the hooks/pre-commit poisoning only by the two Fable lanes);
  the research on single-vs-panel accuracy is unresolved (all claims
  refuted in verification). Shrink adaptively instead.
- **Don't add speculative fix generation during review.** No surviving
  evidence it saves wall-clock; it risks wasted fixes for findings that
  die in verification.
- **Don't drop the adversarial verify phase.** It's cheap when pipelined
  (most verdicts took 15–60s) and it's what kept false positives from
  costing fix-and-re-review cycles (e.g. it correctly inverted the
  delta-verifier's wrong every-vs-any claim).

## 5. Caveats and open questions

- Vendor self-reporting dominates the strongest external numbers
  (Cloudflare 3m39s, GPT-5.5 fast-mode 1.5×, Claude fast-mode 2.5×); fast
  modes are research previews with pricing subject to change; GPT-5.5 Fast
  requires ChatGPT sign-in; Claude fast mode is Opus-only.
- Cloudflare's latency is achieved *without* per-finding adversarial
  verification and with server-side 85.7% cache hits — our local cache
  behavior across subagent spawns is unmeasured (open question; the
  shared-context-file pattern is the cheapest way to find out).
- The arXiv panel-size multipliers come from sequential chains, not
  parallel panels — directionally right, numerically overstated.
- The fix-phase projection (R2) is the least certain: fan-out fixing adds
  coordination overhead and only pays when findings cluster into
  independent regions. Measure before committing to it for small runs.

## 6. Suggested implementation order

1. R3 (formatter-only skip) + R8 (allowlist) — one-paragraph edits, zero risk.
2. R1 (pipeline the panel) + synthesis-off-critical-path — workflow script change.
3. R4 (codex effort/tier flags) — one-line lane command change.
4. R6 (/ci ∥ delta) + nix-shell prewarm — loop-step reordering.
5. R7 (static prompt assets) — skill restructuring.
6. R5 (adaptive tiers) — needs a sizing rule and a quality eye over a few runs.
7. R2 (fix fan-out) — biggest win, most design work; prototype on a run with ≥5 independent findings.
