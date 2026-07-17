---
name: review-loop
description: "Cross-review the current branch with Codex reviewers, optionally add Claude CLI reviewers, adversarially verify findings, auto-fix, and re-review until clean. Groups verified fixes that are too large or out of scope for the current PR under one Linear parent, then implements its child issues serially with implement-issue. Pass `stack` in $ARGUMENTS to review the whole upstack."
---

# review-loop

Codex-native adaptation of the former Claude slash command `review-loop`.

Compatibility notes:
- Treat `$ARGUMENTS` as the relevant arguments or intent from the user's request.
- Replace `AskUserQuestion` with a concise question to the user when a decision is required.
- Use Codex subagents for parallel reviewer lanes. Do not use Claude subagent
  terminology in the Codex workflow.
- Use `claude -p` only as an optional external reviewer lane for one or two
  prompts when the CLI is installed and extra model diversity is useful.
- Ignore Claude `allowed-tools`, `argument-hint`, `TodoWrite`, and `Skill` tool references as tool-permission metadata.
- When the workflow mentions another slash command, use the corresponding Codex skill or follow that workflow directly.

Run a full self-review loop on the current branch: review → auto-fix →
CI → re-review → repeat until clean. Use this right before you `gt submit`
something you wrote yourself, to catch issues before reviewers do.

The loop is **automatic by default**. Findings that clearly should be fixed
are fixed without asking. The loop re-reviews after each fix pass to catch
issues introduced by the fixes themselves. It stops when a review pass
returns no new actionable findings.

Verified findings whose proper fix would materially expand the current PR are
not discarded. The loop collects them across all passes, groups them as child
issues under one new Linear parent, and, after the current PR converges,
implements those children one at a time through the `implement-issue` skill.
The parent/child issue batch still follows `linear-cli`'s draft and approval
rules before creation.

**Why it loops:** AI review is stochastic — each independent pass over the
same diff surfaces *different* findings. The loop runs **fresh full panel
passes** (not narrow fix-delta sweeps) so coverage accumulates across passes;
catching bugs the fixes introduced is a secondary benefit, folded into the
same pass via fix-verification. It converges when an independent pass returns
no new actionable findings.

**Speed design:** every aggregated finding is adversarially verified
**before** triage, so false positives never cost a fix-and-re-review cycle.
Each reviewer lane should be launched in the same parallel batch, and
verification should start as soon as a lane finishes rather than waiting on
the slowest reviewer. The report is assembled deterministically from
structured findings; do not put a prose synthesis pass on the critical path.
The panel is **adaptively sized to the diff** (small diffs run fewer lanes)
so a genuine full re-pass stays affordable. A **compile gate** runs after
each fix pass so a broken fix never burns a review pass; a **formatter-only
delta** is treated as verified by construction and never burns a pass. CI
runs **concurrently** with the re-review.

**Where it runs & context discipline:** keep the main Codex session focused
on glue commands, parallel subagent launches, triage over structured
findings, and user checkpoints. Do not wrap the entire loop in another
orchestrator/subagent; nested orchestration makes tool availability and state
tracking brittle. On a premium model, or when the caller asks for delegation,
push context-heavy work into closing cheaper subagents:

- **Prompt building (step 4)** — a setup subagent authors the prompt files.
- **Report assembly (step 5)** — a subagent renders `review.md` from
  `findings.json`.
- **Fix application (step 11)** — a fixer subagent reads sources and applies
  each pass's fixes; the main session avoids reading source files.

On cheaper models, inlining these steps is fine when the diff is small.

**Argument:** if `$ARGUMENTS` contains `stack`, run across the **entire
upstack** — current branch and every branch above it — amending each branch as
it goes (see **Stack mode** below). Otherwise run the loop on the **current
branch only** and never touch version control (the safe default).

Follow these steps precisely.

---

## Stack mode (`stack` in `$ARGUMENTS`)

When the argument is `stack`, wrap the single-branch loop (steps 1–15) in an
upstack walk: review-loop the current branch, fold the fixes into its commit,
move up, and repeat until the top of the stack. Passing `stack` is an explicit
opt-in to the amend-and-advance flow, so in stack mode **hard rule #4 is
relaxed**: you MAY `gt modify -a` to amend fixes into the current branch before
moving up. You still never `gt submit`/push without the user asking.

With no `stack` argument, skip this section entirely and run steps 1–15 once on
the current branch.

### Stack flow

1. Record the starting branch: `git branch --show-current`. You return here at
   the very end.
2. Run the full single-branch loop (**steps 1–12**) on the current branch.
   - **Relax the step-1 clean-tree gate after the first branch**: `gt up`
     restacks descendants, so a non-empty tree from that is expected. Still
     stop if there are unrelated uncommitted edits you did not make.
3. After the loop converges clean and CI has passed, if any files were modified
   on this branch (by fixes or CI), amend them into the branch's commit with
   `gt modify -a` (use the `graphite` Codex skill or run `gt` directly). This
   also restacks descendants. If nothing was modified, skip the amend.
4. Move up the stack with `gt up`:
   - If `gt up` succeeds and the branch changed, print
     `"Moving up stack -> <new branch>"` and repeat from step 2.
   - If `gt up` fails or the branch did not change, you are at the top. Print
     `"Reached top of stack."` and end the stack walk.
5. If the single-branch loop **fails to converge** on any branch (hits the
   4-pass cap), stop on that branch — do **NOT** continue up the stack. Report
   which branch is stuck and follow the normal non-convergence flow.
6. Accumulate scope-expanding follow-up candidates across every reviewed
   branch. Do not create a parent per branch. After the entire upstack
   converges, run steps 13–14 once so one parent groups the invocation's full
   follow-up set.
7. When done (success or failure), return to the starting branch
   (`gt checkout <starting-branch>`) and print a per-branch summary:
   ```
   Stack review-loop summary:
     branch-a: converged clean (fixed 3, amended)
     branch-b: converged clean (no changes)
     branch-c: stuck (4-pass cap — see above)
   ```

Each branch gets its own review directory (the step-2 `out_dir` is
branch-named), its own diff against its own `gt parent`, and its own 4-pass
cap. Linear grouping and serial implementation happen once after the stack
walk, not once per branch.

---

## 1. Preflight

Verify prerequisites before doing anything:

1. You are in a git repo with a graphite-tracked branch:
   ```bash
   git rev-parse --show-toplevel
   gt log short
   ```

2. `gt` is on PATH:
   ```bash
   command -v gt
   ```
   If `claude` is missing, skip the optional Claude reviewer lanes. Codex
   subagents remain the primary reviewers.

3. The working tree is clean or stashed. A dirty tree pollutes the diff
   and confuses reviewers:
   ```bash
   git status --porcelain
   ```
   If dirty, tell the user and stop.

4. Confirm spawned reviewers can use the commands they need. A blocked shell
   call from one lane stalls the whole fan-out. Before launching, make sure
   `codex`, `git`, `gh`, `cat`, and the project's check command are available
   to reviewer subagents. If external browsing is required by a reviewer, make
   sure the relevant browser/web capability is available before the panel
   starts.

## 2. Resolve scope & prepare workspace

Determine what to review. On a graphite stack, **always diff against `gt
parent`**, not trunk — reviewing against trunk on a stacked branch would
include ancestor PRs and drown the reviewers in unrelated changes.

```bash
default_branch=$(git symbolic-ref refs/remotes/origin/HEAD --short 2>/dev/null || echo origin/master)
parent=$(gt parent 2>/dev/null || git merge-base "$default_branch" HEAD)
branch=$(git rev-parse --abbrev-ref HEAD)
head_sha=$(git rev-parse HEAD)
parent_sha=$(git rev-parse "$parent")
repo_root=$(git rev-parse --show-toplevel)
ts=$(date +%Y-%m-%d_%H-%M-%S)
safe_branch=$(echo "$branch" | tr '/' '_')
out_dir="$repo_root/.tmp/reviews/${ts}-${safe_branch}"
mkdir -p "$out_dir"
follow_up_candidates_path=${follow_up_candidates_path:-"$out_dir/follow-up-candidates.json"}
```

Initialize `follow_up_candidates_path` once for the whole invocation and carry
that same path through every pass. Create it with an empty `candidates` array
before the first review pass. In stack mode, the wrapper sets it before the
first branch and passes it into each branch loop so candidates do not fragment
across branch-specific review directories.

Write the diff and file manifest. Diff against the working tree (no `..HEAD`)
so re-review iterations automatically include uncommitted fixes:

```bash
git diff "$parent" > "$out_dir/diff.patch"
git diff --name-status "$parent" > "$out_dir/files.txt"
wc -l "$out_dir/diff.patch"
```

Refuse to proceed if the diff is empty. If it exceeds 5000 lines, warn the
user and ask whether to proceed — reviewer quality degrades on huge diffs.

**Ensure the artifacts folder is gitignored.** Review artifacts live under
`.tmp/`, the conventional gitignored scratch dir. If `.tmp/` is not in
`.gitignore` (check with `grep -q '\.tmp/' "$repo_root/.gitignore"`), ask the
user directly for permission to add it. Do not silently modify `.gitignore`.

## 3. Load project context

```bash
find "$repo_root" -maxdepth 3 \( -name "CLAUDE.md" -o -name "AGENTS.md" \) \
  -not -path "*/node_modules/*" -not -path "*/target/*"
```

Keep only the paths. Reviewers will read them themselves.

Also extract the PR description if a PR exists for this branch:

```bash
pr_body=$(gh pr view --json body --jq '.body' 2>/dev/null || echo "No PR description available.")
```

Strip bot-appended footers before embedding the description in prompts:
cut everything from the first HTML-comment footer marker onward (e.g.
`<!-- codesmith:footer -->`, CodeRabbit/Codesmith badges, tracking links).
Reviewers should see only the author-written description — bot HTML wastes
their context and can mislead the goal-evaluation lane.

## 4. Build the reviewer prompts

Every reviewer gets a **shared base prompt** plus a **per-reviewer focus
paragraph** that biases each toward a different class of bugs.

On premium models, or when the caller asked for delegation, do not author
these files in the main session. Spawn one setup subagent with this skill's
path, `$out_dir`, the chosen lane keys, the project-doc paths, and the
stripped PR description; it writes `prompt-base.txt`, every
`prompt-{reviewer}.txt`, the inspector prompts, and the step-5 `context.txt`
exactly per this step, then returns only the list of paths written.

### Base prompt

Save this to `$out_dir/prompt-base.txt`:

```
You are a senior staff engineer performing a rigorous code review. You have
15+ years of experience and a track record of catching subtle, high-impact
bugs before they ship. You are thorough but not pedantic. You care about
correctness, security, and maintainability — not style.

Your task: review the diff at {DIFF_PATH} against the project's conventions
documented in these files:
{PROJECT_DOCS_PATHS}

The diff is scoped to exactly the changes on the current PR (parent..HEAD on a
graphite stack). Everything in the diff is in scope; everything outside is
context you may read but should not review.

The PR author describes the change as:
{PR_DESCRIPTION}

Evaluate whether the implementation actually delivers on this description.
If the PR claims to prevent event loss, verify that it does. If it claims
idempotency, check the dedup path. Do not take the description at face value.

Review priorities, in order:

1. CORRECTNESS — bugs, logic errors, off-by-ones, race conditions, unhandled
   errors, incorrect assumptions about external systems, broken invariants,
   dead/unreachable code.
2. CONCURRENCY & ORDERING — async operation sequencing, setup step ordering,
   TOCTOU between async calls, assumptions about which operation completes
   first, whether concurrent writers can produce inconsistent state.
3. SECURITY — injection, authentication/authorization gaps, secret handling,
   input validation, unsafe deserialization, privilege escalation.
4. CONVENTION ADHERENCE — violations of rules explicitly stated in the
   project docs above. Do NOT invent conventions the docs don't mandate.
5. MAINTAINABILITY — only flag things that will actively hurt the next
   engineer to touch this code. Not "could be slightly cleaner."
6. TEST COVERAGE — missing coverage for new logic, tests that assert the
   wrong thing, tests that document gaps instead of fixing them. Only flag if
   the project's docs call test coverage out as required.

What NOT to flag:

- Style, formatting, import ordering, naming nits unless the project docs
  explicitly mandate them.
- Issues the compiler, linter, or typechecker would catch — assume CI exists.
- Pre-existing issues unrelated to the changed behavior. If tracing an
  in-scope change exposes a concrete adjacent problem whose proper fix would
  materially expand this PR, report it with evidence so it can become a
  grouped follow-up; do not roam the repository looking for unrelated work.
- Missing documentation unless the docs mandate it.
- Renamings, reorganizations, or "this could be factored differently"
  suggestions.
- Pedantic edge cases a senior engineer would not call out in a real PR.

Output format — you MUST follow this exactly:

For each finding, emit a section like:

### <short title>

- **Severity:** critical | high | medium | low | nit
- **File:** <path>:<start-line>[-<end-line>]
- **Category:** correctness | security | convention | maintainability | tests
- **Finding:** <one-paragraph description of the issue>
- **Why it matters:** <concrete consequence if not fixed>
- **Recommended fix:** <specific, actionable fix — not "consider doing X">
- **Confidence:** <0-100> — how confident you are this is a real issue (100 =
  certain, 50 = plausible but unverified, 25 = hunch)

Order findings by severity (critical first) then by file.

If you find nothing worth raising, output exactly:

### No findings

<one-sentence justification of why you believe the diff is clean>

Do not include preamble, disclaimers, emojis, or summaries. Start directly
with the first finding (or "### No findings").
```

### Per-reviewer focus paragraphs

Append one of these to the base prompt for each reviewer:

**Codex A — Concurrency & async ordering:**
```
YOUR FOCUS: Pay special attention to the ordering of async operations
during setup, teardown, and reconnection. When two async steps happen in
sequence (subscribe then query, or query then subscribe), consider what
happens if the world changes between them. Look for TOCTOU gaps in async
setup sequences, concurrent writers to shared state, and assumptions about
which operation completes first.
```

**Codex B — Goal evaluation & domain logic:**
```
YOUR FOCUS: Read the PR description carefully, then evaluate whether the
implementation actually achieves what it claims. If the PR says "events
are never lost," find a scenario where they could be. If it says
"checkpoint only advances safely," find a case where it doesn't. Be
adversarial about the stated goals — your job is to find the gap between
intent and implementation.
```

**Codex C — Error handling & failure modes:**
```
YOUR FOCUS: Trace every error path and failure mode. What happens when a
database write fails mid-operation? When a background job exhausts its
retries? When a network call times out during a multi-step process? Look
for silent failures, missing error propagation, and recovery paths that
leave the system in an inconsistent state.
```

**Codex D — Edge cases & boundary conditions:**
```
YOUR FOCUS: Look for edge cases at boundaries. What happens at block 0?
When a range is empty? When both inputs are equal? When an optional value
is None for the first time? When a counter overflows? Find the inputs
that the author probably didn't test.
```

**Codex E — Broad general sweep:**
```
YOUR FOCUS: Do a broad, unbiased review. Don't focus on any particular
category — instead, try to find anything the other reviewers might miss.
Look at the change holistically: does the overall design make sense? Are
there interactions between components that could produce surprising
behavior? Are there implicit assumptions that aren't documented?
```

Save each complete prompt (base + focus) to `$out_dir/prompt-{reviewer}.txt`.

### Shared context file

Write one small context file that reviewer lanes can read, instead of
duplicating diff/docs/PR text into every prompt:

```bash
cat > "$out_dir/context.txt" <<EOF
Diff: $out_dir/diff.patch
Project docs: <CLAUDE.md/AGENTS.md paths, comma-separated>
PR description (author-written, bot footers stripped):
<pr_body>
EOF
```

## 5. Spawn reviewers and inspectors in parallel

All reviewers and inspectors must be spawned in a **single message with
parallel tool calls**. Do not run them sequentially.

### Adaptive panel sizing (by diff size)

A full independent panel runs **every** pass (re-review is for stochastic
coverage, not just fix-checking — see step 12), so size the panel to the
diff to keep each pass affordable. Inspectors are always included (cheap):

- **< 50 changed lines:** the goal-evaluation reviewer + one broad-sweep
  reviewer + all inspectors.
- **50–500 lines:** the full reviewer set minus one overlapping reviewer.
- **> 500 lines, or any diff touching security-sensitive paths** (auth,
  secrets, payment/financial, on-chain, migrations): the full set.

Security-sensitive paths force the full panel regardless of size. When in
doubt, size up. To trim per-reviewer latency on routine diffs, run the Codex
reviewer subagents at **medium** reasoning effort and on the **fast service
tier** (`service_tier = "fast"`, which needs ChatGPT sign-in — fall back to
the default tier if the auth in use rejects it) rather than the defaults;
reserve higher effort for large or security-sensitive diffs.

### Reviewers 1-5 — Codex Subagents

Spawn five Codex subagents. Each gets its own prompt: the base prompt plus
one focus paragraph from Step 4:

- **Codex A**: `$out_dir/prompt-codex-a.txt` (concurrency & async ordering)
- **Codex B**: `$out_dir/prompt-codex-b.txt` (goal evaluation & domain logic)
- **Codex C**: `$out_dir/prompt-codex-c.txt` (error handling & failure modes)
- **Codex D**: `$out_dir/prompt-codex-d.txt` (edge cases & boundary conditions)
- **Codex E**: `$out_dir/prompt-codex-e.txt` (broad general sweep)

Plus the suffix:

```
The diff is at: {DIFF_PATH}
Project docs: {PROJECT_DOCS_PATHS}
Repo root: {REPO_ROOT}

Read the diff, read the project docs, and read any source files referenced by
the diff that you need for context. Return your review in the format
specified above — nothing else.
```

Write each subagent's output to `$out_dir/raw-codex-a.md` through
`$out_dir/raw-codex-e.md`.

### Optional Claude Reviewers

If `claude` is installed and extra model diversity is useful, run one or two
`claude -p` reviewer lanes in parallel. These are external checks, not the
primary reviewer set.

Suggested lanes:

- **Claude A**: `$out_dir/prompt-claude-a.txt` (goal evaluation & domain logic)
- **Claude B**: `$out_dir/prompt-claude-b.txt` (error handling & failure modes)
  — run this lane with `--model sonnet`

At most ONE Claude lane (the goal-evaluation one) may run on the premium
default model: measured runs show the goal-evaluation focus is where the
premium Claude model finds unique high-severity issues, while additional
premium lanes mostly duplicate Codex/Sonnet findings and burn the Anthropic
usage limit ~3x faster per token than Sonnet (2x Opus).

```bash
cat "$out_dir/diff.patch" | claude -p \
  "The diff is provided on stdin. Analyze it as a code reviewer.

$(cat "$out_dir/prompt-claude-${INSTANCE}.txt")

Project docs: <list of paths>
Repo root: $repo_root

Read the project docs and any source files referenced by the diff that you
need for context. Return your review in the format specified above —
nothing else." \
  > "$out_dir/raw-claude-${INSTANCE}.md" 2> "$out_dir/claude-${INSTANCE}-stderr.log"
```

If a Claude lane exits non-zero, record it as "reviewer errored" and
continue. Skip Claude entirely when the CLI is unavailable or the user asks
for Codex-only review.

### Inspector agents — Test, Idiomatic Rust, Strong Typing, and External Contract Inspectors

Alongside the five reviewers, spawn four additional specialized inspector
agents. These produce structured reports in their own format (not the
reviewer finding format) and feed into the aggregator as supplementary
input.

**Test Inspector**:

Prompt: the full content of the Codex `test-inspector` skill
(`~/Github/dotagents/dotcodex/skills/test-inspector/SKILL.md`, everything
below the frontmatter). Treat the current branch as the user request. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Read the diff to identify test files. Read the full test files and the
source files they test. Produce your inspection report. If no test files
are in the diff, say so and stop.
```

Write output to `$out_dir/raw-test-inspector.md`.

**Idiomatic Rust Inspector**:

Prompt: the full content of the Codex `idiomatic-rust-inspector` skill
(`~/Github/dotagents/dotcodex/skills/idiomatic-rust-inspector/SKILL.md`,
everything below the frontmatter). Treat the current branch as the user
request. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Read the diff to identify Rust files. Read the full files and related
type/trait/error definitions. Produce your inspection report. If no Rust
files are in the diff, say so and stop.
```

Write output to `$out_dir/raw-rust-inspector.md`.

**Strong Typing Inspector**:

Prompt: the full content of the Codex `strong-typing-inspector` skill
(`~/Github/dotagents/dotcodex/skills/strong-typing-inspector/SKILL.md`,
everything below the frontmatter). Treat the current branch as the user
request. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Build the domain-type inventory from the repo first, then scan the diff.
If the diff has no source files where strong typing is relevant, say so and
stop. Produce your inspection report.
```

Write output to `$out_dir/raw-typing-inspector.md`.

**External Contract Inspector**:

Prompt: the full content of the Codex `external-contract-inspector` skill
(`~/.codex/skills/external-contract-inspector/SKILL.md`, everything below
the frontmatter). Treat the current branch as the user request. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Identify external touchpoints in the diff (HTTP/RPC/SDK responses, on-chain
ABIs and message formats, units/decimals). For each, check whether the
assumed shape is backed by a cited spec or a test encoding a real response.
Read the relevant test files and fixtures to decide. Produce your inspection
report. If the diff has no external touchpoints, say so and stop.
```

Write output to `$out_dir/raw-contract-inspector.md`.

**Skip conditions**: If the diff contains no test files, the test inspector
will self-exit (this is fine — record "no test files, skipped"). If the diff
contains no `.rs` files, the Rust inspector will self-exit (same handling).
If the diff has no strong-typing surface or external touchpoints, those
inspectors will self-exit. The aggregator handles missing inspector reports
gracefully.

### Chunk splitting for large diffs

If the diff exceeds **3,500 lines**, split it into domain-based chunks to
keep each reviewer within quality range. Each chunk should be under ~3,500
lines.

1. Read `$out_dir/files.txt` to understand which files changed.
2. Group files by domain/crate/directory into logical chunks.
3. Generate per-chunk diffs using `git diff` with path filters:
   ```bash
   git diff "$parent" -- 'crates/dto/' 'crates/finance/' > "$out_dir/chunk-a.patch"
   ```
4. Verify all files are covered.
5. Report chunk sizes to the user before proceeding.
6. Spawn **5 x N** reviewers (one per instance per chunk). Output files
   are named `raw-{model}-chunk-{label}.md`.
7. The aggregator receives ALL raw reviews across all chunks.

Skip chunking for diffs under 3,500 lines, single-directory diffs, or if the
user explicitly asks for a single-pass review.

**Chunked re-review passes (changed chunks only at full strength).** The
full per-chunk reviewer set applies only to the FIRST pass. On re-review
passes, regenerate the per-chunk patches and compare each against the
previous iteration's (`cmp -s chunk-X-iter${N}.patch
chunk-X-iter$((N-1)).patch`):

- **Changed chunks** get the full reviewer set — fix regressions live here.
- **Unchanged chunks** get one broad-sweep reviewer only. Measured runs show
  late-pass stochastic discoveries on untouched code come almost entirely
  from diverse-lens lanes (broad sweep, contract inspection), while
  re-running the full panel just re-finds what it already found.
- Inspector lanes still run once per pass on the full diff, so unchanged
  chunks keep their external-contract sweep.

### Output validation

After all reviewer and inspector lanes finish, verify each output file:

```bash
validate_review() {
  local file="$1" reviewer="$2"
  [ ! -f "$file" ] && echo "$reviewer: no output" && return 1
  [ "$(wc -l < "$file")" -lt 5 ] && echo "$reviewer: too short" && return 1
  grep -q '^### ' "$file" || { echo "$reviewer: no findings headings"; return 1; }
  return 0
}
```

If a reviewer errors, record it as "reviewer errored" in the aggregator and
continue. If all five Codex reviewer lanes error, stop.

### Parallelism

In one parallel batch, issue:

1. Codex subagent call for Codex A
2. Codex subagent call for Codex B
3. Codex subagent call for Codex C
4. Codex subagent call for Codex D
5. Codex subagent call for Codex E
6. Codex subagent call for Test Inspector
7. Codex subagent call for Idiomatic Rust Inspector
8. Codex subagent call for Strong Typing Inspector
9. Codex subagent call for External Contract Inspector
10. Optional `claude -p` process for Claude A
11. Optional `claude -p` process for Claude B

## 6. Normalize, verify, and aggregate

Normalize every reviewer and inspector output into one structured findings
array before triage. Prefer JSON objects with these fields: `title`,
`severity`, `file`, `line_start`, `line_end`, `category`, `finding`,
`why_it_matters`, `recommended_fix`, `confidence`, and `found_by`. If a lane
returned markdown, spawn a fresh Codex subagent only to convert that lane's
markdown into this schema; do not ask it to add opinions or new findings.

Merge duplicates deterministically by file, category, overlapping/nearby line
ranges, and materially identical issue text. Save the merged, pre-verification
array to `$out_dir/findings-preverify.json` as an audit trail.

If you need a prose aggregator because a reviewer emitted ambiguous markdown,
use this prompt as a fallback. Its output must still be converted to
structured findings before triage.

Aggregator prompt:

```
You are a senior staff engineer aggregating five independent code reviews of
the same diff. Your job is to produce a single canonical review report that
is more reliable than any individual reviewer.

You have five primary raw reviews:
- {CODEX_A_PATH}   (Codex A)
- {CODEX_B_PATH}   (Codex B)
- {CODEX_C_PATH}   (Codex C)
- {CODEX_D_PATH}   (Codex D)
- {CODEX_E_PATH}   (Codex E)

You may also have optional external raw reviews:
- {CLAUDE_A_PATH}  (Claude A)
- {CLAUDE_B_PATH}  (Claude B)

You also have four specialized inspector reports (may be empty if no
relevant files were in the diff):
- {TEST_INSPECTOR_PATH}      (Test Inspector — test quality assessment)
- {RUST_INSPECTOR_PATH}      (Idiomatic Rust Inspector — Rust idiom assessment)
- {TYPING_INSPECTOR_PATH}    (Strong Typing Inspector — primitive obsession and type-boundary leaks)
- {CONTRACT_INSPECTOR_PATH}  (External Contract Inspector — unverified external-API/contract assumptions)

And the diff itself at:
- {DIFF_PATH}

And the project conventions at:
- {PROJECT_DOCS_PATHS}

Do this:

1. Read all primary reviews and any optional external reviews that exist.
2. Read the diff so you can verify claims against the actual code.
3. For each distinct finding across the five reviews:
   a. Merge duplicates — findings that describe the same underlying issue
      should become one entry, even if worded differently.
   b. Record which reviewer(s) raised it: [codex-a], [codex-b], [codex-c],
      [codex-d], [codex-e], [claude-a], [claude-b], or a combination.
   c. Verify the finding by reading the relevant code. For each one, form
      YOUR OWN opinion on whether it is:
         - valid: a real issue that should be fixed
         - likely: probably real but needs more context
         - disputed: reviewers disagree or the evidence is weak
         - invalid: false positive, not actually a problem
         - out-of-scope: real but on code not in the diff
   d. If a reviewer's claim conflicts with the actual code, mark it invalid
      and say why.
4. Re-score severity from scratch based on your own reading, using the same
   scale: critical | high | medium | low | nit.
5. Re-score confidence: 0-100, where 100 means you verified it yourself.

Output format:

# Review — {BRANCH}

**Commit:** {HEAD_SHA}
**Parent:** {PARENT_SHA} ({PARENT_BRANCH})
**Files changed:** {N}
**Diff size:** {LOC} lines
**Reviewers:** Codex A, Codex B, Codex C, Codex D, Codex E
**Optional reviewers:** Claude A, Claude B if present
**Aggregator:** Codex

## Summary

<2-3 sentence overall verdict. Include the count of valid findings at each
severity.>

## Findings

<findings sorted by: severity (critical first), then verdict (valid first),
then confidence (high first)>

For each finding:

### [SEVERITY] <short title>

- **File:** <path>:<line-range>
- **Category:** correctness | security | convention | maintainability | tests
- **Verdict:** valid | likely | disputed | invalid | out-of-scope
- **Confidence:** <0-100>
- **Found by:** [codex-a], [codex-b], [codex-c], [codex-d], [codex-e],
  [claude-a], [claude-b], [test-inspector], [rust-inspector],
  [contract-inspector], or a list
- **Issue:** <one paragraph>
- **Why it matters:** <concrete consequence>
- **Recommended fix:** <specific action>
- **Verification rationale:** <your own take — do you agree with the
  reviewers? Is this worth fixing? Is any reviewer overreaching?>

## Findings dismissed as invalid

<bullet list of findings you rejected, each with one-sentence rationale and
which reviewer raised it>

## Findings dismissed as out-of-scope

<bullet list — real issues but on code the diff did not touch>

## Overall assessment

<2-3 paragraphs. Your own senior-engineer judgment on whether this PR is
ready to merge, needs a second pass, or has fundamental issues. Call out
anything the individual reviewers missed collectively if you spot it.>

Inspector reports use a different format from the five reviewers. Integrate
their findings as follows:

- **Test Inspector findings** (useless/weak tests, missing coverage, mock
  abuse): convert each into a standard finding entry. Use category "tests".
  Severity: useless tests = medium, weak tests = low, missing coverage for
  risky logic = high, mock abuse = medium.
- **Idiomatic Rust Inspector findings** (non-idiomatic code, ownership
  issues, error handling, type design): convert each into a standard
  finding entry. Use category "maintainability" for style/idiom issues,
  "correctness" for ownership bugs or unsafe misuse. Severity: non-idiomatic
  with correctness impact = high, non-idiomatic style-only = medium,
  suboptimal = low.
- **Strong Typing Inspector findings** (raw primitives where domain types
  exist, missed newtypes, stringly typed IDs, unit confusion, and type-boundary
  leaks): convert each into a standard finding entry. Use category
  "maintainability", or "correctness" when unit/identifier confusion can cause
  wrong behavior. Severity: high for financial values or identifiers that can
  corrupt state, medium for primitive-where-domain-type-exists, low for
  missed-newtype opportunities.
- **External Contract Inspector findings** (unverified assumptions about an
  external API/contract — wire types, numeric widths, units/decimals, field
  shapes — not backed by a cited spec or a real-response test): convert each
  into a standard finding entry. Use category "correctness". Carry over the
  inspector's risk-weighted severity verbatim (critical for wrong
  width/unit/encoding at a money or on-chain boundary, down to low for
  cosmetic shape assumptions). The recommended fix should name how to pin
  the assumption (cite the spec, or add the real-response test).
- If an inspector report is empty or says "no files found", ignore it.
- Inspector findings can corroborate or conflict with the reviewer
  findings — merge duplicates as you would between any two reviewers.
- In the "Found by" field, use [test-inspector], [rust-inspector],
  [typing-inspector], or [contract-inspector] as the attribution.

Do not include emojis, apologies, or disclaimers. Be decisive.
```

If you used the fallback prose aggregator, write its raw output to
`$out_dir/review-aggregate-raw.md`, convert it to the structured schema, and
continue with the same verification flow below.

### Per-finding adversarial verification (refute-before-fix)

Before triage, adversarially verify every finding the aggregator did NOT
already dismiss. A false positive that reaches triage costs a fix pass plus
a re-review pass — killing it here is the cheapest point in the loop.

Spawn one Codex subagent per finding, all in parallel. Each verifier gets
the finding (title, file, line range, issue text, recommended fix), the
diff path, and the repo root, with this instruction:

```
You are adversarially verifying a single code-review finding. Read the
actual code before judging — never judge from the finding text alone.
Classify it: valid (real, you verified it against the code), likely
(probably real but needs more context), disputed (evidence is weak),
invalid (false positive — the code contradicts the claim), out-of-scope
(real but on lines the diff did not modify). Refute only with concrete
evidence from the code; do not dismiss uncertain-but-plausible findings.
Re-score severity and confidence from your own reading.
```

Append each verdict to the finding. Findings judged `invalid` or
`out-of-scope` move to the dismissed lists (record the verifier's rationale
in `review.md`); the rest proceed to triage with the verifier's re-scored
severity, verdict, and confidence.

Do not lose verified `out-of-scope` findings in the dismissed audit trail.
When the verifier confirms that an out-of-scope finding is real, concrete,
and directly exposed by the PR review, append it to an invocation-wide
`$follow_up_candidates_path`. Carry the finding, verifier rationale, source
branch/commit, review path, and why the fix does not belong in the current PR.
Deduplicate candidates across lanes, review passes, and stack branches by the
underlying problem, not merely by title.

After verification, write `$out_dir/findings.json` with:

```json
{
  "findings": [ /* verified valid | likely | disputed findings */ ],
  "dismissed": [ /* invalid | out-of-scope findings */ ],
  "laneErrors": [ /* lane error strings */ ],
  "fixVerifications": []
}
```

Assemble `$out_dir/review.md` deterministically from `findings.json`; do not
use a synthesis agent on the critical path. On premium sessions, a subagent
may render the markdown from `findings.json`, but it must not invent or
reinterpret findings.

## 7. Print findings to the terminal

Print a compact, scannable summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Review — <branch>
<N> files, <LOC> lines changed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▲ CRITICAL (count)
  1. <title>
     <file>:<line>  [codex-a, codex-d]  confidence: 95
     <one-line fix>

▲ HIGH (count)
  ...

▲ MEDIUM (count)
  ...

▲ LOW (count)
  ...

▲ NIT (count)
  ...

▽ Dismissed as invalid: <count>
▽ Dismissed as out-of-scope: <count>

Full report: <absolute path to review.md>
```

Keep each finding to **two lines**: title line (title + agents + confidence)
and fix line (recommended fix). The full details live in `review.md`.

If the review reports **no actionable findings**, print that prominently. If
`$follow_up_candidates_path` is empty, exit successfully. If it contains
verified candidates, treat the current PR as converged and continue to step 13
instead of dropping the follow-up queue.

---

## 8. Triage input

Read `$out_dir/findings.json`, not `review.md`, for triage. The markdown
report is for humans; the loop acts on structured findings so it does not
depend on prose parsing. Each finding already carries:

- `title`
- `severity` (critical | high | medium | low | nit)
- `verdict` (valid | likely | disputed)
- `confidence` (re-scored by the verifier)
- `category` (correctness | security | convention | maintainability | tests)
- `file` + `line_start`/`line_end`
- `finding`
- `recommended_fix`
- verifier `rationale`

Findings the verifier judged `invalid` or `out-of-scope` are already in the
`dismissed` list — never triage those.

## 9. Build the triage plan

For each remaining finding, compute a **default action** based on severity,
verdict, and confidence. **Bias heavily toward fixing now** — use grouped
follow-up only when the proper fix is genuinely separate scope.

| Severity   | Verdict  | Confidence | Default action |
| ---------- | -------- | ---------- | -------------- |
| critical   | any      | any        | **Auto-fix**   |
| high       | valid    | >= 50      | **Auto-fix**   |
| high       | likely   | >= 50      | **Auto-fix**   |
| high       | disputed | any        | **Discuss**    |
| medium     | valid    | >= 50      | **Auto-fix**   |
| medium     | likely   | >= 50      | **Auto-fix**   |
| medium     | disputed | any        | **Discuss**    |
| low        | valid    | >= 75      | **Auto-fix**   |
| low        | any      | < 75       | **Auto-dismiss** |
| nit        | any      | any        | **Auto-dismiss** |

**Auto-fix**: apply the fix immediately without asking. No user input needed.

**Auto-dismiss**: drop the finding silently. No user input needed.

**Discuss**: the evidence is weak or reviewers disagree. Show the user the
full finding and ask what to do. Default to fixing unless it's massive.

Apply a **scope gate** before the table above. If a verified finding is real
but its proper fix materially expands the current PR's stated goal (for
example, an independent feature, multi-domain refactor, or adjacent
pre-existing defect), assign **Grouped follow-up** instead of auto-fix. Add it
to `$follow_up_candidates_path`; do not force scope creep into the current PR.
Critical issues still qualify when they are genuinely separate—the serial
implementation phase handles them first.

**Grouped follow-up** is also used when the user explicitly defers a finding.
It is not a way to avoid a surgical in-scope fix. When in doubt about scope,
fix it now.

When in doubt, fix it now.

## 10. Present the plan and auto-apply

Print the plan as a table, in severity order:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Review-loop triage — <N> findings (iteration <I>)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 # | sev      | action       | title
---+----------+--------------+------------------------
 1 | critical | auto-fix     | Off-by-one in batch loop
 2 | high     | auto-fix     | Missing auth check on /admin
 3 | medium   | auto-fix     | Add retry on transient errors
 4 | medium   | DISCUSS      | Lock contention in hot path
 5 | nit      | auto-dismiss | Rename variable for clarity

Full details: <path to review.md>
```

**Auto-fix and auto-dismiss findings proceed immediately — no user input.**

For **discuss** findings only, ask the user directly:

```
Q: [#N] <title> — sev <severity>. Reviewers disagree — what should I do?
   options:
     - "Fix now" (Recommended) — implement the fix in this session
     - "Dismiss" — drop it, not a real issue
     - "Grouped follow-up" — separate scope; create and implement as a child issue
     - "Show me the details" — read the full finding first
```

If the user picks "Show me the details", present the finding
conversationally and re-ask without that option.

After resolving discuss items, print the consolidated plan:

```
Plan:
  Fix now (3):     #1, #2, #4
  Follow up (1):   #3
  Dismiss (1):     #5
```

## 11. Fix-now loop

For each "fix now" finding, in severity order:

1. Announce which one you're addressing.
2. Read the relevant source file(s).
3. Verify the finding is still valid (the code may have been edited since
   the review — re-read, don't trust the report blindly).
4. Apply the recommended fix using `Edit` (or `Write` for new files). Keep
   the change surgical — do not drift into unrelated cleanups. Match the
   project's style.
5. If the fix touches tests or requires them, add/update the tests. If the
   user's project docs (`CLAUDE.md`/`AGENTS.md`) mandate test coverage for
   the kind of logic being fixed, add tests even if the finding didn't
   mention it.
6. Print a one-line summary of what changed.
7. Do **not** run the full test suite, lints, or commit yet — the `ci`
   skill runs only after the review loop converges.

If while implementing a fix you discover that the real solution materially
expands the PR, reclassify it as a grouped follow-up, record the concrete
scope reason in `$follow_up_candidates_path`, and continue with the remaining
in-scope fixes. Only stop for a genuinely ambiguous correctness decision.

### Compile gate

After all fix-now items are done, run the **compile gate** before any
re-review: the project's fastest typecheck scoped to what was touched (for
Rust, `cargo check -p <touched crates>`; otherwise the project's
equivalent). Fix any compile errors immediately — never enter a re-review
pass with code that doesn't compile; that wastes an entire review pass. The
compile gate is NOT a substitute for the `ci` skill — full tests and lints
still run only after convergence.

Then proceed directly to step 12 (re-review).

## 12. Re-review loop (independent full passes)

Re-review after every fix pass. **Why the loop exists:** AI review is
stochastic — each independent pass over the same diff surfaces *different*
findings. The primary purpose of looping is this **coverage** (shaking out
issues an earlier pass happened to miss), and only secondarily catching bugs
the fixes introduced. So a re-review is NOT a narrow sweep of the fix delta —
it is a **fresh, independent panel pass over the full updated diff**, with
fix-verification folded in. Adaptive panel sizing (step 5) keeps a genuine
full re-pass affordable.

**CRITICAL: The re-review is NOT optional.** After fixing findings, you MUST
re-review at least once. Do not skip it because the fixes "looked
straightforward." Only a review pass determines when the loop is done.

**CRITICAL: Convergence requires a CLEAN pass.** The loop is ONLY done when
an independent panel pass returns no new actionable findings AND every
applied fix verified. Fixing the last batch is NOT convergence. The pattern
is always `review → fix → review → fix → review(clean) → done`. You can never
end on a fix.

### Prepare the updated diff

```bash
git diff "$parent" > "$out_dir/diff-iter${N}.patch"   # updated full diff
git diff HEAD --stat | tail -1                          # what the loop changed
```

Re-pick the lane set with the **step 5 adaptive sizing** rule against the
updated diff, pointing the reviewer lanes at `diff-iter${N}.patch`. On
chunked runs, also apply the **changed-chunks-only** rule from step 5: full
reviewer set only for chunks whose patch differs from the previous
iteration, one broad-sweep reviewer for unchanged chunks.

### Formatter-only skip

If the only thing that changed since the last reviewed state is the output
of a deterministic formatter/hook (`cargo fmt`, `yamlfmt`, `prettier`,
`deno fmt`, …) and that formatter now passes, **do not spawn a review pass
over it** — formatter output cannot introduce a review-worthy finding. Treat
that delta as verified by construction and skip to convergence. Confirm the
change is purely the formatter's doing (re-running the formatter reproduces
it); if any hand-written line changed, run the full re-pass.

### Run the re-review pass

Run the **same panel as the first pass** (adaptively sized) over the full
updated diff, INCLUDING aggregation and per-finding adversarial
verification. In the same parallel batch, also spawn **one fix-verifier per
applied fix**:

```
A code review flagged this finding and a fix was applied. Read the current
source at the finding's location. Confirm the fix fully resolves the
finding — not partially, not by suppressing the symptom — and check the
surrounding code for issues the fix introduced. Report: fixed (yes/no),
rationale, and any new issues caused by or directly adjacent to the fix
(standard finding format).
```

Save outputs to `$out_dir/review-iter${N}-*.md` (audit trail).

### Overlap CI with the re-review

The re-review and the `ci` skill both read the same working tree and don't
interact, so launch them **concurrently** after a fix pass. Then gate
convergence on both: clean re-review + green CI with no CI changes →
converged; clean re-review + formatter-only CI changes → converged (per the
formatter-only skip); re-review not clean → ignore the in-flight CI result
(you'll re-run it next convergence). The `ci` skill's own "amend via
`gt modify -a` on success" step is overridden by this loop: never amend in
single-branch mode (hard rule 4 — the user drives version control); in stack
mode the stack flow amends once per branch after convergence, so ci must not
amend separately there either.

### Interpret the result

1. **Clean** = the panel reports no findings AND every fix-verifier reports
   fixed with no new issues. Converge per the CI-overlap rules above.
2. **Not clean**: collect the panel findings, any unresolved fixes (re-fix
   those), and new issues from the verifiers. Filter out anything
   substantively identical to a finding already fixed or dismissed (compare
   file + line range + description) — this is what stops the stochastic
   passes from re-litigating settled findings forever. If nothing new
   remains, treat as clean. Otherwise increment the iteration counter and
   loop back to step 9 (triage) with only the remaining findings.

**Cap at 4 review passes total** (initial + up to 3 re-reviews). Because
re-review is stochastic, hitting the cap usually means findings are thinning
out, not that fixes are breaking things — but stop and tell the user either
way: report what each pass found and let a human judge whether the residual
findings are noise or a real unresolved problem.

Print a status line at the start of each iteration:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Re-review iteration <N> (independent full pass, <K> lanes) — stochastic coverage + fix verification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 13. Group scope-expanding follow-ups in Linear

Run this step after the current branch (or entire requested stack) converges.
Load the invocation-wide `$follow_up_candidates_path`. Candidates are:

- verified `out-of-scope` findings that are real, concrete, and directly
  exposed while reviewing the PR;
- verified findings reclassified by the scope gate because the proper fix
  would materially expand the current PR; and
- findings the user explicitly chose to move to a grouped follow-up.

Exclude invalid/speculative findings and unrelated repository observations.
Deduplicate materially identical candidates. If none remain, skip steps
13–14.

Invoke the `linear-cli` skill and follow its exact `--help`, file-based
description, required-metadata, and approval rules:

1. Resolve the current PR's Linear issue when possible and inherit its team,
   project, milestone, and assignee. If there is no linked issue, use the
   repository's Linear configuration. If the required project or other
   metadata cannot be inferred safely, ask one batched metadata question.
2. Draft **one parent issue** titled `Address follow-ups from review of
   <original issue or PR>`. Its body explains the reviewed goal, links the
   original PR/branch and review reports, and states that each child is an
   independently implementable scope boundary. Set its priority to the
   highest child priority.
3. Draft **one child issue per candidate**. Use an imperative title and this
   body shape:

   ```markdown
   ## Problem

   <verified issue text>

   ## Evidence

   - File: `<path>:<line-range>`
   - Category: <category>
   - Severity: <severity>
   - Found during review of branch `<branch>` (commit `<sha>`)

   ## Desired outcome

   <outcome derived from the recommended fix, stated without over-prescribing implementation>

   ## Verification rationale

   <verifier rationale>

   ---

   Grouped from review `<path to review.md>` because the fix would expand the
   original PR's scope.
   ```

4. Derive child priority from severity and select only labels that actually
   exist for the resolved team. Give every parent and child the required
   project and default assignee. Preserve the original issue's milestone when
   appropriate.
5. Show the exact parent draft, every child draft, and all metadata as one
   batch. Ask once to create the group; allow edits or removal of individual
   children. This single approval covers the displayed parent and child
   drafts—do not ask again per child unless a draft changes materially.
6. After approval, create the parent first, then create each child as a true
   Linear subissue of that parent (not merely a `blocks` relation). Run
   `linear issue create --help` and `linear issue update --help` before using
   parent flags; use the raw GraphQL fallback from `linear-cli` only if the
   installed CLI cannot set parentage.
7. Record the parent and ordered child IDs/URLs in
   `$out_dir/follow-up-issues.json`. Order children by severity, then discovery
   order. Update the parent description with child links if Linear does not
   render them automatically.

Do not create one parent per finding or per stack branch. One review-loop
invocation produces at most one new follow-up parent.

## 14. Implement grouped follow-ups serially

After the issue group is created, implement every child through the
`implement-issue` skill **one at a time**. Never run child implementations in
parallel.

1. Capture the branch where review-loop started. The `implement-issue` handoff
   requires a clean tree. If this loop applied reviewed fixes in single-branch
   mode, invoke the `graphite` skill and run `gt modify -a` once to fold only
   those fixes into the current branch before leaving it. This is the sole
   single-branch amend exception; do not submit directly from review-loop.
2. For each child ID in `follow-up-issues.json`, in order:
   - invoke `implement-issue <CHILD-ID>` and let that skill complete its full
     plan, implementation, review, PR, submission, CI, and Linear workflow;
   - wait for it to finish successfully before starting the next child; and
   - record its branch, PR, and final status in `follow-up-issues.json`.
3. Pass the existing parent ID as standing context. If a child's nested review
   discovers another genuine scope-expanding finding, reuse this parent and
   append the new child to the end of the same serial queue instead of creating
   a nested follow-up parent. Search the parent's existing children first to
   avoid duplicate issues or cycles.
4. If one child blocks or fails, stop the serial queue, leave the remaining
   children unstarted, update the parent with the blocker, and report exactly
   where execution stopped. Never skip ahead silently.
5. When all children finish, update the parent status to match the repository's
   Linear policy and the children's actual states. Do not mark the parent Done
   while any child PR is still in a state that keeps its issue open.
6. Return to the branch where review-loop started before printing the final
   summary.

The `implement-issue` skill retains its own plan-approval and architecture
decision checkpoints. "Serial" means the complete workflow for child N
finishes before child N+1 begins.

## 15. Summarize

After all review iterations converge and the grouped follow-up queue either
completes or stops on a real blocker, print a final summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Review loop complete — <N> iteration(s), converged clean
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fixed (3):
  #1  critical  Off-by-one in batch loop               <file>:<line>
  #2  high      Missing auth check on /admin            <file>:<line>
  #4  medium    Lock contention in hot path             <file>:<line>

Grouped follow-ups (2):
  Parent         Address follow-ups from review         <linear url>
  #3  medium     Add retry on transient errors           <child url>  implemented: <PR url>

Dismissed (1):
  #5  nit       Rename variable for clarity

Reports: <paths to review.md, findings.json, review-iter*.json>
```

Below the summary block, add two prose sections:

**What changed** — for each fixed finding, a short paragraph describing the
change actually applied, not just the finding title: what the code does now
versus before, any public API impact (added/removed/renamed items), tests
added or modified, and any design decision made between competing fix
options (name the option chosen and why). If a fix made the PR description,
docs, or comments stale, call that out explicitly so the user can update
them before submitting.

**Grouped follow-ups** — name the parent and each child, with implementation
status and PR link. If the queue stopped, identify the blocker and list the
unstarted children. Omit this section when there were no candidates.

Then stop. Outside stack mode and the explicit grouped-follow-up handoff in
step 14, do not auto-run `gt modify`, `gt submit`, or any other mutation.

**In stack mode**, steps 13–15 run only after the upstack walk has converged;
the wrapper must not create or implement follow-ups per branch.

---

## Failure modes

- **All reviewers error:** stop immediately, tell the user, don't proceed
  to triage.
- **Review returns no actionable findings:** print "No findings"; exit only
  when the follow-up candidate queue is also empty. Otherwise continue to
  grouped issue creation.
- **A fix turns out to be larger than expected:** reclassify it as a grouped
  follow-up when the solution is genuinely separate scope; stop only if the
  classification or correctness decision is ambiguous.
- **Re-review pass cap hit (4 passes):** stop and tell the user. Summarize
  what each pass found. Because re-review is stochastic, late passes usually
  surface *thinning* residual findings rather than fix-induced regressions —
  let a human judge whether what remains is noise or a real problem.
- **The follow-up parent fails to create:** report the exact `linear` error,
  preserve every draft, and stop before creating children.
- **A follow-up child fails to create:** report the exact error, preserve the
  draft and already-created group, and stop before serial implementation so
  the parent is not silently incomplete.
- **A child `implement-issue` run blocks or fails:** update the parent with the
  blocker, stop the queue, and leave later children unstarted.
- **The user says "stop" mid-loop:** immediately stop, then print the
  summary with what was completed so far. Do not silently abandon the rest.
- **Claude not installed:** skip optional Claude reviewer lanes and proceed
  with the Codex reviewer set.

## Hard rules

1. **Auto-fix without asking** for findings that match auto-fix criteria.
   Only ask the user about "discuss" findings.
2. **Bias toward fixing now.** Use a grouped follow-up only when the proper fix
   materially expands the current PR or the user explicitly requests it.
   Never silently discard a verified, actionable out-of-scope finding.
3. Never create Linear issues without showing the exact parent/child batch and
   receiving explicit approval. One approval may cover the unchanged batch;
   materially edited drafts require renewed approval.
4. Never amend, commit, or `gt submit` automatically — the user drives
   version control. **Exceptions:** stack mode may `gt modify -a` per branch;
   and a created follow-up queue may `gt modify -a` once in single-branch mode
   to make the reviewed starting branch clean before invoking
   `implement-issue`. Review-loop itself never submits; each serial
   `implement-issue` owns its branch/PR mutations and submission.
5. Always use `--description-file` with `linear issue create`, never inline
   `--description`.
6. Always re-verify findings against the current source before applying
   fixes — the code may have changed since the review.
7. Keep fixes surgical. No "while I'm here" cleanups.
8. Run the compile gate after every fix pass; launch the `ci` skill
   concurrently with the re-review (both read the same working tree). If CI
   makes non-formatter code changes, run another re-review pass over them; a
   pure-formatter delta is verified by construction and needs no pass.
9. Cap at 4 review passes. Convergence requires a clean independent pass —
   never end on a fix. Stop and ask the user if you don't converge.
10. Spawn all reviewers in a single message with parallel tool calls.
11. Use `--sandbox read-only` for codex — non-negotiable.
12. Normalize reviewer output to structured findings, verify findings in
    parallel, and assemble `review.md` deterministically from `findings.json`.
    A subagent may render markdown from JSON, but must not synthesize new
    findings on the critical path.
13. Never fabricate findings when a reviewer errors — record the failure.
14. Save raw outputs, `findings.json`, `review.md`, and each
    `review-iter${N}.json` before printing to terminal.
15. Never silently modify `.gitignore` — ask permission to add `.tmp/` if
    missing.
16. Validate reviewer output files before normalization — reject files that
    contain dumped file contents instead of review analysis.
17. Re-review is always a fresh INDEPENDENT panel pass over the full updated
    diff (stochastic coverage), adaptively sized per step 5 — never a narrow
    fix-delta sweep. The only thing that skips a pass is a verified
    formatter-only delta.
18. Create at most one follow-up parent per review-loop invocation. Every
    verified scope-expanding finding becomes a true child issue under it.
19. Invoke `implement-issue` for child issues strictly in series. A child must
    finish its complete workflow before the next starts; on failure, stop and
    preserve the remaining queue.
20. Nested review loops from those child implementations reuse the same parent
    and append deduplicated children to the serial queue; they never create a
    hierarchy of follow-up parents.
