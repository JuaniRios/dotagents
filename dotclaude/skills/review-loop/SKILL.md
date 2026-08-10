---
name: review-loop
allowed-tools: Bash(gt:*), Bash(git:*), Bash(gh:*), Bash(codex:*), Bash(linear:*), Bash(cargo:*), Bash(nix:*), Bash(mkdir:*), Bash(cat:*), Bash(mktemp:*), Bash(rm:*), Bash(test:*), Bash(grep:*), Bash(wc:*), Bash(date:*), Bash(basename:*), Bash(find:*), Read, Write, Edit, Agent, Workflow, AskUserQuestion
description: Cross-review the current branch with a multi-model Workflow panel, auto-fix findings, and re-review until clean. If the PR grows too big, offer to decompose it into smaller stacked PRs. Group verified fixes that are too large or out of scope for the current PR under one Linear parent, then implement its child issues as a stacked series of PRs with /implement-issue-stack. Pass `stack` to review the whole upstack.
argument-hint: [stack]
---

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
implements those children through `/implement-issue-stack`, which stacks one
branch/PR per child in series. The
parent/child issue batch still follows `/linear-cli`'s draft and approval
rules before creation.

**Why it loops:** AI review is stochastic — each independent pass over the
same diff surfaces *different* findings. The loop runs **fresh full panel
passes** (not narrow fix-delta sweeps) so coverage accumulates across passes;
catching bugs the fixes introduced is a secondary benefit, folded into the
same pass via fix-verification. It converges when an independent pass returns
no new actionable findings.

**Speed design:** every finding is adversarially verified **before** triage,
so false positives never cost a fix-and-re-review cycle. Inside the panel,
each lane's findings verify the moment that lane finishes (pipelined, no
barrier waiting on the slowest reviewer), and the report is assembled
deterministically (no synthesis agent on the critical path). The panel is
**adaptively sized to the diff** (small diffs run fewer lanes) so a genuine
full re-pass stays affordable. A **compile gate** runs after each fix pass so
a broken fix never burns a review pass; a **formatter-only delta** is treated
as verified by construction and never burns a pass either. `/ci` runs
**concurrently** with the re-review.

**Where it runs & context discipline:** the `Workflow` tool exists only in
the main session — subagents cannot invoke it (and ToolSearch cannot load it
there), so this command always runs in the main session. **Never wrap the
loop in an orchestrator subagent** — the panel engine would be lost, and
hand-rolling the fan-out with Agent calls is forbidden (hard rule 10). What
keeps the main context small instead is delegation of the remaining
context-heavy steps to closing `opus` subagents, so source files, prompt
text, and report prose never enter the main context:

- **Prompt building (step 4)** — a setup subagent authors the prompt files.
- **Report assembly (step 5)** — a subagent renders `review.md` from
  `findings.json`.
- **Fix application (step 11)** — a fixer subagent reads sources and applies
  each pass's fixes; the main session never reads source files.

The main session keeps only glue commands, the Workflow invocations, triage
over structured findings, and user checkpoints. On a very small diff you
may inline these steps, since per-subagent overhead can exceed the savings,
but a caller may instruct delegation regardless (`/implement-issue-stack`
does, to keep its babysitter tiny). Every agent this command spawns runs on
Opus or the Codex CLI — never a smaller model.

**Argument:** with no argument, the loop runs on the **current branch only**
and never touches version control (the safe default). With `stack`, it runs
across the **entire upstack** — current branch and every branch above it —
amending each branch as it goes (see **Stack mode** below).

Follow these steps precisely.

---

## Stack mode (`/review-loop stack`)

When invoked with the `stack` argument, wrap the single-branch loop (steps
1–15) in an upstack walk: review-loop the current branch, fold the fixes into
its commit, move up, and repeat until the top of the stack. Passing `stack` is
an explicit opt-in to the amend-and-advance flow, so in stack mode **hard rule
#4 is relaxed**: you MAY `gt modify -a` to amend fixes into the current
branch before moving up. You still never `gt submit`/push without the user
asking.

With no `stack` argument, skip this section entirely and run steps 1–15 once
on the current branch.

### Stack flow

1. Record the starting branch: `git branch --show-current`. You return here at
   the very end.
2. Run the full single-branch loop (**steps 1–12**) on the current branch.
   - **Relax the step-1 clean-tree gate after the first branch**: `gt up`
     restacks descendants, so a non-empty tree from that is expected. Still
     stop if there are unrelated uncommitted edits you did not make.
3. After the loop converges clean and `/ci` has passed, if any files were
   modified on this branch (by fixes or by `/ci`), amend them into the
   branch's commit with `gt modify -a` (invoke the `graphite` skill). This
   also restacks descendants. If nothing was modified, skip the amend.
4. Move up the stack with `gt up` (via the `graphite` skill):
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

## Size gate — decompose an oversized PR into a stack

A PR that keeps growing gets worse review, not more of it: reviewer quality
degrades on large diffs, and this loop's own fixes push the diff further up.
So measure the branch's size at two points and offer to split when it crosses
the line.

### When to check

- **At step 2**, right after writing `diff.patch` — the branch may already be
  too big before the loop touches it.
- **At step 12**, on the updated diff after each fix pass — the loop's fixes
  and the tests they pull in are a common way a reasonable PR becomes an
  unreviewable one.

Measure **hand-written** size only. Exclude lockfiles, generated code,
snapshots, vendored trees, and fixtures from the counts (they inflate the
number without costing review effort):

```bash
git diff --numstat "$parent" -- . \
  ':(exclude)**/*.lock' ':(exclude)**/*.snap' ':(exclude)**/generated/**' \
  ':(exclude)**/vendor/**' ':(exclude)**/fixtures/**' \
  | awk '{add+=$1; del+=$2; files++} END {print files" files, "add+del" lines"}'
```

### Trigger

Propose decomposition when **any** of these holds:

- more than **800** hand-written changed lines, or
- more than **20** hand-written changed files, or
- the loop's own fixes grew the diff by more than **30%** over the size
  recorded at step 2, or
- the diff spans **three or more unrelated concerns** that each stand alone
  (e.g. a schema migration, an unrelated bug fix, and a new endpoint) —
  regardless of line count.

Under every threshold and one coherent concern: say nothing, keep going. A
single-concern 900-line PR is often correctly one PR; do not split a diff
that has no clean seam.

### Propose, never split silently

Splitting rewrites branches, so it is always a user decision (hard rule 4).
Print the measured size and the seams you see, then ask with
`AskUserQuestion`:

```
Q: This PR is <N> files / <L> lines across <K> concerns. Split it into a stack?
   options:
     - "Split into <K> stacked PRs" (Recommended) — show me the plan first
     - "Keep as one PR" — proceed with the review loop unchanged
     - "Split later" — finish the loop, remind me in the final summary
```

If triggered mid-loop (step 12), finish the current loop to convergence
**first** and split after — never split a branch with unreviewed fixes in
flight. Only a step-2 trigger may split before reviewing, since nothing is in
flight yet.

### Build the split plan

Group the changed files into an **ordered** list of independently reviewable
branches, bottom-up:

1. Pure groundwork first — new types, traits, constants, moves/renames with no
   behavior change.
2. Then each behavioral concern, one branch per concern.
3. Tests go **with the branch whose behavior they cover**, never in a
   trailing "add tests" branch.

Every branch must compile on its own (that is the ordering constraint — if
group B does not compile without group C, they are one group). Aim for each
branch under ~400 hand-written lines. If the seams cannot produce compiling
branches, report that and keep the PR whole.

Show the plan for approval before touching version control:

```
Split plan for <branch> (<N> files, <L> lines):
  1. <branch>-types     ~120 lines   crates/dto/**            groundwork: new domain types
  2. <branch>-ingest    ~310 lines   crates/ingest/** + tests behavior: checkpoint handling
  3. <branch>           ~250 lines   (remainder)              behavior: the API surface
```

The original branch stays as the **top** of the stack so its existing PR,
Linear link, and review history survive.

### Execute the split

Invoke `/graphite` for every version-control command; never raw `git` for
branch/commit mutation.

1. The tree must be clean. If this loop applied fixes, `gt modify -a` once to
   fold them into the branch first — this is a size-gate exception to hard
   rule 4, covered by the user's approval above.
2. Take a safety net: `git branch backup/<branch>-predecomp`. Never delete it
   during the session; name it in the final summary.
3. If the branch's existing **commit boundaries already match the groups**,
   use `gt split --by-commit` and stop here.
4. Otherwise peel groups off the bottom, one at a time, for every group except
   the last:
   - `gt checkout <current parent>`
   - stage that group's paths from the branch's tree
     (`git checkout backup/<branch>-predecomp -- <paths>`)
   - `gt create <new-branch> -m "<message>"`
   - move the original branch onto the new branch and restack (`gt move
     --onto <new-branch>`, then `gt restack`). The peeled hunks are already
     applied, so the rebase drops them and the original commit keeps only the
     remainder. On conflicts, invoke `/fix-conflicts`.
5. **Verify nothing was lost.** The top of the new stack must have the same
   tree as the backup:
   ```bash
   git diff --stat backup/<branch>-predecomp   # must print nothing
   ```
   If it prints anything, stop and tell the user — do not hand-patch the
   difference.
6. Each new branch is unsubmitted. Do not `gt submit` (hard rule 4); tell the
   user the stack is ready to submit and that the original PR now carries only
   the top branch's changes, so its description likely needs updating
   (`/pr-description`).

### After the split

Continue as **stack mode** from the bottom of the new stack: `gt bottom`, then
run steps 1–15 per branch as described in **Stack mode** above. Findings
already fixed and dismissed on the pre-split branch carry over — do not
re-litigate them. The 4-pass cap resets per branch.

---

## 1. Preflight

Verify prerequisites before doing anything:

1. You are in a git repo with a graphite-tracked branch:
   ```bash
   git rev-parse --show-toplevel
   gt log short
   ```

2. `codex` and `gt` are on PATH:
   ```bash
   command -v codex gt
   ```
   If `codex` is missing, warn the user and drop the two Codex lanes from the
   panel (9 lanes instead of 11). Nine lanes is still valuable.

3. The working tree is clean or stashed. A dirty tree pollutes the diff
   and confuses reviewers:
   ```bash
   git status --porcelain
   ```
   If dirty, tell the user and stop.

4. **Pre-allowlist the commands the workflow agents need.** A non-allowlisted
   shell/web/MCP call from a lane pauses the whole Workflow mid-run waiting
   for a permission prompt — on a long fan-out that stalls everything.
   Before launching, make sure `codex`, `git`, `gh`, `cat`, and `cargo` (and
   WebFetch, if any lane needs it) are on the allowlist. The frontmatter
   `allowed-tools` covers the main session; confirm the same commands are
   permitted for spawned agents.

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

Now run the **size gate** (see the section above): record the hand-written
file/line counts as the invocation's baseline, and if the branch already
trips a trigger, offer to decompose it into a stack before reviewing.

**Ensure the artifacts folder is gitignored.** Review artifacts live under
`.tmp/`, which is the conventional gitignored scratch dir in most repos. If
`.tmp/` is not in `.gitignore` (check with `grep -q '\.tmp/' "$repo_root/.gitignore"`),
ask the user for permission to add it. Do not silently modify `.gitignore`.

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

**Delegation:** unless the diff is tiny, do not author these files in the
main session. Spawn one
**setup subagent** (`Agent`, `model: opus`) with this command file's path,
`$out_dir`, the chosen lane keys, the project-docs paths, and the stripped
PR description; it writes `prompt-base.txt`, every `prompt-{reviewer}.txt`,
the inspector prompts, and the step-5 `context.txt` exactly per this step,
and returns only the list of paths written. On a tiny diff you may write
them inline as described below.

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

Output: return your findings via the structured output tool you have been
given. Each finding needs: title, severity (critical | high | medium | low |
nit), file (repo-relative path), line_start, line_end, category (correctness
| security | convention | maintainability | tests), finding (one-paragraph
description), why_it_matters (concrete consequence if not fixed),
recommended_fix (specific and actionable — not "consider doing X"), and
confidence (0-100; 100 = certain, 50 = plausible but unverified, 25 = hunch).

If you find nothing worth raising, return an empty findings list and set
clean_reason to a one-sentence justification of why the diff is clean.
```

(For the two Codex lanes, replace the "Output" paragraph in their prompt
files with the original markdown output format — `### <title>` sections with
Severity/File/Category/Finding/Why it matters/Recommended fix/Confidence
bullets, "### No findings" when clean — since Codex returns text that the
lane agent converts to structured output.)

### Per-reviewer focus paragraphs

Append one of these to the base prompt for each reviewer:

**`concurrency` — Concurrency & async ordering:**
```
YOUR FOCUS: Pay special attention to the ordering of async operations
during setup, teardown, and reconnection. When two async steps happen in
sequence (subscribe then query, or query then subscribe), consider what
happens if the world changes between them. Look for TOCTOU gaps in async
setup sequences, concurrent writers to shared state, and assumptions about
which operation completes first.
```

**`goal-eval` — Goal evaluation & domain logic:**
```
YOUR FOCUS: Read the PR description carefully, then evaluate whether the
implementation actually achieves what it claims. If the PR says "events
are never lost," find a scenario where they could be. If it says
"checkpoint only advances safely," find a case where it doesn't. Be
adversarial about the stated goals — your job is to find the gap between
intent and implementation.
```

**`failure-modes` — Error handling & failure modes:**
```
YOUR FOCUS: Trace every error path and failure mode. What happens when a
database write fails mid-operation? When a background job exhausts its
retries? When a network call times out during a multi-step process? Look
for silent failures, missing error propagation, and recovery paths that
leave the system in an inconsistent state.
```

**`codex-a` — Edge cases & boundary conditions:**
```
YOUR FOCUS: Look for edge cases at boundaries. What happens at block 0?
When a range is empty? When both inputs are equal? When an optional value
is None for the first time? When a counter overflows? Find the inputs
that the author probably didn't test.
```

**`codex-b` — Broad general sweep:**
```
YOUR FOCUS: Do a broad, unbiased review. Don't focus on any particular
category — instead, try to find anything the other reviewers might miss.
Look at the change holistically: does the overall design make sense? Are
there interactions between components that could produce surprising
behavior? Are there implicit assumptions that aren't documented?
```

Save each complete prompt (base + focus) to `$out_dir/prompt-{reviewer}.txt`.

### Inspector prompts

Write six inspector prompt files the same way. Each contains the full body
of the corresponding skill file (everything below the frontmatter, with
`$ARGUMENTS` replaced by the empty string — use the current branch), plus an
appended context block, plus structured-output mapping rules:

**Test Inspector** — `$out_dir/prompt-test-inspector.txt` from
`~/.claude/skills/test-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Read the diff to identify test files. Read the full test files and the
source files they test. If no test files are in the diff, return an empty
findings list with clean_reason "no test files in diff".

Return findings via the structured output tool. Category is always "tests".
Severity mapping: useless tests = medium, weak tests = low, missing coverage
for risky logic = high, mock abuse = medium.
```

**Idiomatic Rust Inspector** — `$out_dir/prompt-rust-inspector.txt` from
`~/.claude/skills/idiomatic-rust-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Read the diff to identify Rust files. Read the full files and related
type/trait/error definitions. If no Rust files are in the diff, return an
empty findings list with clean_reason "no Rust files in diff".

Return findings via the structured output tool. Category: "maintainability"
for style/idiom issues, "correctness" for ownership bugs or unsafe misuse.
Severity mapping: non-idiomatic with correctness impact = high, non-idiomatic
style-only = medium, suboptimal = low.
```

**Strong Typing Inspector** — `$out_dir/prompt-typing-inspector.txt` from
`~/.claude/skills/strong-typing-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Build the domain-type inventory from the repo first, then scan the diff.
If the diff has no source files where strong typing is relevant, return an
empty findings list with clean_reason.

Return findings via the structured output tool. Category is always
"maintainability". Severity mapping: primitive-where-domain-type-exists =
medium (high if it touches financial values or identifiers), missed-newtype
opportunity = low.
```

**External Contract Inspector** — `$out_dir/prompt-contract-inspector.txt`
from `~/.claude/skills/external-contract-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Identify external touchpoints in the diff (HTTP/RPC/SDK responses, on-chain
ABIs and message formats, units/decimals). For each, check whether the
assumed shape is backed by a cited spec or a test encoding a real response.
Read the relevant test files and fixtures to decide. If the diff has no
external touchpoints, return an empty findings list with clean_reason.

Return findings via the structured output tool. Category is always
"correctness". Severity is risk-weighted: critical for wrong
width/unit/encoding at a money or on-chain boundary, down to low for
cosmetic shape assumptions. The recommended_fix should name how to pin the
assumption (cite the spec, or add the real-response test).
```

**Comment Discipline Inspector** — `$out_dir/prompt-comment-inspector.txt`
from `~/.claude/skills/comment-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

Read the diff to identify source files with added or modified comments.
Run the volume measurement in step 2 first, against {DIFF_PATH}, and report
the ratio in every finding set even when it is within bounds. If the diff
adds no comments, return an empty findings list with clean_reason.

Return findings via the structured output tool, one per Delete or Rewrite
entry. Category is "maintainability" unless project docs explicitly make it
"convention". Severity: medium for a ticket or PR reference, change history,
a comment block that narrates rather than explains, duplication that will
predictably become stale, and any diff whose comment ratio exceeds 15%; low
only for a single wordy line. Do not default everything to low, or these
findings rank below every real bug and never get fixed.
```

**Simplicity Inspector** — `$out_dir/prompt-simplicity-inspector.txt` from
`~/.claude/skills/simplicity-inspector/SKILL.md`. Append:

```
The diff is at: {DIFF_PATH}
Repo root: {REPO_ROOT}

The PR author describes the change as:
{PR_DESCRIPTION}

Measure the budget first, then read the changed files whole (not only the
hunks) — you cannot tell that an abstraction has one user from the hunk that
adds it. Search the repo before claiming an existing mechanism already
covers the case, and name it with a path. If the diff is already minimal,
return an empty findings list and set clean_reason to the two or three
things you tried to cut and why each is load-bearing.

Return findings via the structured output tool. Category is always
"maintainability". Severity mapping: a different, materially smaller
approach that still meets the stated goal = high; removable machinery
(one-user abstraction, unused knob, stored derived state, forwarding
wrapper, impossible branch, dead-on-arrival code, copy-paste bulk) = medium;
local verbosity = low. Put the line count you would remove in
why_it_matters, and the written-out smaller form in recommended_fix — a
finding without a concrete replacement is not a finding.
```

## 5. Run the review workflow

The whole review pass — fan-out, per-lane adversarial verification, and (on
re-review passes) fix-verification — runs as **one `Workflow` invocation**.
Findings come back schema-validated, so there is no markdown parsing and no
synthesis agent in the workflow; the main session assembles `review.md`
deterministically from the structured findings (the loop acts on findings,
not prose, and the ~100s synthesis agent used to sit on the critical path).

The same workflow serves the first pass and every re-review pass — the only
differences are `fixedFindings` (empty first, this loop's fixes thereafter)
and the lane set (which may shrink for small diffs, below).

### Lanes

Full lane catalogue (drop the codex lanes if `codex` is not on PATH):

| key                | codex | model  | effort | promptPath                              |
| ------------------ | ----- | ------ | ------ | --------------------------------------- |
| concurrency        | no    | opus   |        | prompt-concurrency.txt (async ordering) |
| goal-eval          | no    | opus   | xhigh  | prompt-goal-eval.txt (goal evaluation)  |
| failure-modes      | no    | opus   |        | prompt-failure-modes.txt (error paths)  |
| codex-a            | yes   | opus   | medium | prompt-codex-a.txt (edge cases)         |
| codex-b            | yes   | opus   | medium | prompt-codex-b.txt (broad sweep)        |
| test-inspector     | no    | opus   |        | prompt-test-inspector.txt               |
| rust-inspector     | no    | opus   |        | prompt-rust-inspector.txt               |
| typing-inspector   | no    | opus   |        | prompt-typing-inspector.txt             |
| contract-inspector | no    | opus   | xhigh  | prompt-contract-inspector.txt           |
| comment-inspector  | no    | opus   |        | prompt-comment-inspector.txt            |
| simplicity-inspector | no  | opus   | xhigh  | prompt-simplicity-inspector.txt         |

**Model allocation:** every lane runs on Opus or the Codex CLI
(`gpt-5.6-sol`). Never put a lane on a smaller model — a weak reviewer costs
a whole pass and returns noise. `goal-eval`, `contract-inspector`, and
`simplicity-inspector` run on Opus at xhigh effort: they are the lanes that
must hold the whole change at once (intent-vs-implementation gaps, unpinned
external assumptions at money boundaries, and the smaller design that was
available). All other non-Codex lanes run on Opus. The codex lanes' model
applies to the WRAPPER agent that shells out to the codex CLI — it is Opus
too, and does only trivial wrapper work.

**Pass lanes compactly.** Don't hand-spell the full lane objects in `args` —
the script expands them. The caller sends just `outDir`, `diffPath`, and
`laneKeys` (e.g. `["concurrency","goal-eval","failure-modes","codex-a",
"codex-b","test-inspector","rust-inspector","typing-inspector",
"contract-inspector","comment-inspector","simplicity-inspector"]`);
the script's `LANE_CATALOGUE` turns each key into the full
`{key, codex, model, promptPath, diffPath, effort?}` (promptPath =
`$out_dir/prompt-<key>.txt`, `effort` defaults to `medium` for codex lanes).
This keeps the per-pass `args` the main session inlines tiny — re-spelling 10
objects with absolute paths every pass just burns main-session tokens for zero
review value. Normally all lanes share `$out_dir/diff.patch`. **Chunked runs**
(per-chunk keys like `concurrency-chunk-b`, per-chunk paths) are the exception:
pass an explicit `lanes` array, which the script uses verbatim.

### Adaptive panel sizing (by diff size)

A full independent panel runs **every** pass (re-review is for stochastic
coverage, not just fix-checking — see step 12), so size the panel to the
diff to keep each pass affordable. Inspectors are always included (9–18s
each, negligible):

- **< 50 changed lines:** `goal-eval` + one codex broad lane +
  all six inspectors. ~8 lanes.
- **50–500 lines:** the full catalogue minus one codex lane (`codex-a` and
  `codex-b` overlap heavily). ~10 lanes.
- **> 500 lines, or any diff touching security-sensitive paths** (auth,
  secrets, payment/financial, on-chain, migrations): the full catalogue.

Security-sensitive paths force the full panel regardless of size. When in
doubt, size up.

### Shared context file

Write one small context file the non-codex lanes read, instead of
duplicating the diff path / docs / PR description into every lane prompt
(maximizes prompt-cache reuse across the concurrent lanes — identical base
prompt + one shared context pointer):

```bash
cat > "$out_dir/context.txt" <<EOF
Diff: $out_dir/diff.patch
Project docs: <CLAUDE.md/AGENTS.md paths, comma-separated>
PR description (author-written, bot footers stripped):
<pr_body>
EOF
```

### Prewarm (overlap setup with the panel)

Kick the nix dev shells warm in the background while the panel runs, so the
later `/ci` step doesn't pay cold-shell startup:

```bash
nix develop .#ci-backend -c true >/dev/null 2>&1 &
```

### Workflow invocation

Invoke the `Workflow` tool with the script below via `script`, and `args`
(compact form — the script expands `laneKeys` into full lane objects):

```json
{
  "repoRoot": "<repo_root>",
  "contextPath": "<out_dir>/context.txt",
  "outDir": "<out_dir>",
  "diffPath": "<out_dir>/diff.patch",
  "laneKeys": [ "concurrency", "goal-eval", "failure-modes", ... ],
  "fixedFindings": []
}
```

`fixedFindings` is `[]` on the first pass. On re-review passes pass it as
**locator-only** objects `{title, file, line_start, line_end}` — the verify-fix
agent reads the actual source at that location, so inlining the full
`finding`/`why_it_matters`/`recommended_fix` prose just wastes main-session
tokens. The tool result includes a `scriptPath` — reuse it
(`{scriptPath, args}`) for every re-review pass instead of resending the
script. Build the `args` with a small Bash/python step and pass it straight to
the tool — do **not** `Read` the generated args JSON back into the main context
(it lives on disk for the tool).

```javascript
export const meta = {
  name: 'review-panel',
  description: 'Independent multi-model review pass over the full diff: per-lane review + adversarial verify (pipelined, no barrier), plus concurrent fix-verification on re-review passes. No synthesis agent — the caller assembles the report deterministically.',
  phases: [
    { title: 'Review', detail: 'reviewer lanes; each verifies its own findings as it finishes' },
    { title: 'Verify fixes', detail: 'confirm each applied fix (re-review passes only)' },
  ],
}

const FINDING = {
  type: 'object',
  required: ['title', 'severity', 'file', 'line_start', 'line_end', 'category',
    'finding', 'why_it_matters', 'recommended_fix', 'confidence'],
  properties: {
    title: { type: 'string' },
    severity: { enum: ['critical', 'high', 'medium', 'low', 'nit'] },
    file: { type: 'string' },
    line_start: { type: 'integer' },
    line_end: { type: 'integer' },
    category: { enum: ['correctness', 'security', 'convention', 'maintainability', 'tests'] },
    finding: { type: 'string' },
    why_it_matters: { type: 'string' },
    recommended_fix: { type: 'string' },
    confidence: { type: 'integer' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: { type: 'array', items: FINDING },
    clean_reason: { type: 'string' },
    reviewer_error: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'rationale', 'severity', 'confidence'],
  properties: {
    verdict: { enum: ['valid', 'likely', 'disputed', 'invalid', 'out-of-scope'] },
    rationale: { type: 'string' },
    severity: { enum: ['critical', 'high', 'medium', 'low', 'nit'] },
    confidence: { type: 'integer' },
  },
}

const VERIFY_FIX_SCHEMA = {
  type: 'object',
  required: ['fixed', 'rationale'],
  properties: {
    fixed: { type: 'boolean' },
    rationale: { type: 'string' },
    new_issues: { type: 'array', items: FINDING },
  },
}

// The harness may deliver args as a JSON-encoded string instead of a
// parsed object — parse defensively before destructuring.
const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
// fixedFindings is empty on the first pass and carries this loop's applied
// fixes on re-review passes. Re-review is a genuine INDEPENDENT panel pass
// over the full updated diff (stochastic coverage — each pass surfaces
// different findings), with fix-verification folded in concurrently.
const { repoRoot, contextPath, outDir, diffPath, laneKeys,
  lanes: explicitLanes, fixedFindings = [] } = parsedArgs

// Lane catalogue: the caller passes a COMPACT { outDir, diffPath, laneKeys }
// and the script expands each key to a full lane object here — so the per-pass
// args the main session must inline stay tiny (the lanes are identical every
// pass except diffPath, so re-spelling 10 objects with absolute paths each pass
// just burns main-session tokens). Chunked runs (lane keys like
// `concurrency-chunk-b`, per-chunk promptPath/diffPath) pass an explicit `lanes`
// array instead, which takes precedence.
const LANE_CATALOGUE = {
  'concurrency':          { codex: false, model: 'opus' },
  'goal-eval':            { codex: false, model: 'opus', effort: 'xhigh' },
  'failure-modes':        { codex: false, model: 'opus' },
  'codex-a':              { codex: true,  model: 'opus',  effort: 'medium' },
  'codex-b':              { codex: true,  model: 'opus',  effort: 'medium' },
  'test-inspector':       { codex: false, model: 'opus' },
  'rust-inspector':       { codex: false, model: 'opus' },
  'typing-inspector':     { codex: false, model: 'opus' },
  'contract-inspector':   { codex: false, model: 'opus', effort: 'xhigh' },
  'comment-inspector':    { codex: false, model: 'opus' },
  'simplicity-inspector': { codex: false, model: 'opus', effort: 'xhigh' },
}
const lanes = explicitLanes || (laneKeys || []).map(key => ({
  key, ...LANE_CATALOGUE[key],
  promptPath: `${outDir}/prompt-${key}.txt`,
  diffPath,
}))

// Each lane reviews the FULL diff, then its own findings are adversarially
// verified immediately — pipeline, NOT a barrier waiting on the slowest
// reviewer. Cross-lane duplicate findings may be verified more than once;
// that is far cheaper than a barrier and is deduped afterward. No synthesis
// agent runs here (it was ~100s on the critical path and the loop consumes
// structured findings, not prose) — the caller assembles the report.

const codexPrompt = (lane) =>
  `Use Bash to run exactly this command (one call, 10 minute timeout):\n` +
  `cat "${lane.diffPath}" | codex exec --sandbox read-only -m gpt-5.6-sol ` +
  `-c model_reasoning_effort="${lane.effort || 'medium'}" ` +
  `-c service_tier="fast" -C "${repoRoot}" "$(cat "${lane.promptPath}")"\n` +
  `(model_reasoning_effort is turned down from default and service_tier is ` +
  `pinned to fast — both cut Codex-lane latency, which gated the whole ` +
  `review phase. service_tier="fast" needs ChatGPT sign-in; if codex errors ` +
  `that fast/priority tier is unavailable for the auth in use, drop the ` +
  `service_tier flag and retry.) Codex mixes tool-call logs with the ` +
  `review; the review appears after the last bare 'codex' marker line in ` +
  `stdout, before any 'tokens used' trailer. If the command fails with a ` +
  `rate-limit or quota error, retry once with -m o3. Convert the review ` +
  `into structured findings (parse each ### section into one finding). If ` +
  `codex is unusable, return an empty findings list and set reviewer_error.`

const reviewLane = (lane) => {
  const prompt = lane.codex
    ? codexPrompt(lane)
    : `Read the review instructions at ${lane.promptPath} and follow them ` +
      `exactly.\nShared review context (diff path, docs paths, PR ` +
      `description) is at: ${contextPath}\nRepo root: ${repoRoot}\nRead the ` +
      `diff, the project docs, and any source files referenced by the diff.`
  return agent(prompt, {
    label: `review:${lane.key}`, phase: 'Review', model: lane.model,
    ...(lane.effort && !lane.codex ? { effort: lane.effort } : {}),
    schema: REVIEW_SCHEMA,
  }).then(result => ({
    key: lane.key,
    error: result ? (result.reviewer_error || null) : 'lane died or was skipped',
    findings: result
      ? (result.findings || []).map(finding => ({
          ...finding, found_by: [lane.key], diff_path: lane.diffPath }))
      : [],
  }))
}

const verifyLane = (reviewed) =>
  parallel((reviewed.findings || []).map(finding => () =>
    agent(
      `You are adversarially verifying a single code-review finding. Read ` +
      `the actual code before judging — never judge from the finding text ` +
      `alone.\n\nFinding: ${JSON.stringify(finding)}\n\nThe diff is at: ` +
      `${finding.diff_path}\nRepo root: ${repoRoot}\n\nClassify: valid ` +
      `(real, verified against the code), likely (probably real, needs more ` +
      `context), disputed (evidence weak), invalid (false positive — the ` +
      `code contradicts the claim), out-of-scope (real but on lines the diff ` +
      `did not modify). Refute only with concrete evidence; do not dismiss ` +
      `uncertain-but-plausible findings. Re-score severity and confidence ` +
      `from your own reading (confidence 100 = you verified it yourself).`,
      { label: `verify:${finding.file}`, phase: 'Review', model: 'opus',
        schema: VERDICT_SCHEMA },
    ).then(verdict => verdict && ({ ...finding, ...verdict }))
  )).then(verdicts => ({
    key: reviewed.key, error: reviewed.error,
    verified: verdicts.filter(Boolean),
  }))

const verifyFix = (finding) =>
  agent(
    `A code review flagged this finding and a fix was applied:\n` +
    `${JSON.stringify(finding)}\n\nThe full updated PR diff is at: ` +
    `${lanes[0].diffPath}\nRepo root: ${repoRoot}\n\nRead the current source ` +
    `at the finding's location. Confirm the fix fully resolves the finding ` +
    `— not partially, not by suppressing the symptom — and check the ` +
    `surrounding code for issues the fix introduced. Report new_issues only ` +
    `for problems caused by or directly adjacent to the fix.`,
    { label: `verify-fix:${finding.title}`, phase: 'Verify fixes',
      model: 'opus', schema: VERIFY_FIX_SCHEMA },
  ).then(result => result && ({ finding, ...result }))

// Panel (pipelined review->verify, no barrier) and fix-verification run
// concurrently. fixedFindings is [] on the first pass.
const [laneRows, fixVerifications] = await parallel([
  () => pipeline(lanes, reviewLane, verifyLane),
  () => parallel(fixedFindings.map(finding => () => verifyFix(finding))),
])

const rows = (laneRows || []).filter(Boolean)
const laneErrors = rows.filter(row => row.error).map(row => `${row.key}: ${row.error}`)
const allVerified = rows.flatMap(row => row.verified)

// Post-verify dedup: collapse the same finding surfaced by multiple lanes.
const merged = []
for (const finding of allVerified) {
  const dup = merged.find(existing =>
    existing.file === finding.file &&
    existing.category === finding.category &&
    finding.line_start <= existing.line_end + 3 &&
    existing.line_start <= finding.line_end + 3)
  if (dup) {
    dup.found_by = [...new Set([...dup.found_by, ...finding.found_by])]
    if (finding.confidence > dup.confidence) {
      Object.assign(dup, { ...finding, found_by: dup.found_by })
    }
  } else {
    merged.push({ ...finding })
  }
}

const survivors = merged.filter(finding =>
  finding.verdict === 'valid' || finding.verdict === 'likely' ||
  finding.verdict === 'disputed')
const dismissed = merged.filter(finding =>
  finding.verdict === 'invalid' || finding.verdict === 'out-of-scope')

const sevRank = { critical: 0, high: 1, medium: 2, low: 3, nit: 4 }
const verdictRank = { valid: 0, likely: 1, disputed: 2 }
survivors.sort((first, second) =>
  sevRank[first.severity] - sevRank[second.severity] ||
  verdictRank[first.verdict] - verdictRank[second.verdict] ||
  second.confidence - first.confidence)

const fixes = (fixVerifications || []).filter(Boolean)
log(`${allVerified.length} verified -> ${survivors.length} survivors, ` +
  `${dismissed.length} dismissed; lane errors: ${laneErrors.length}; ` +
  `fix-verifications: ${fixes.length}`)

return { findings: survivors, dismissed, laneErrors, fixVerifications: fixes }
```

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
6. Duplicate the five reviewer lanes per chunk (keys like `concurrency-chunk-b`),
   each with its chunk's `diffPath`. Inspector lanes run once on the full
   diff. Pass all lanes to a single workflow invocation — dedup and
   verification handle the rest.

Skip chunking for diffs under 3,500 lines, single-directory diffs, or if the
user explicitly asks for a single-pass review.

**Chunked re-review passes (changed chunks only at full strength).** The
full per-chunk panel applies only to the FIRST pass. On re-review passes,
compare each chunk's regenerated patch against the previous iteration's
(`cmp -s chunk-X-iter${N}.patch chunk-X-iter$((N-1)).patch`):

- **Changed chunks** get the full five-lane panel — fix regressions live
  here, and this is where the repeated generalist lanes keep earning.
- **Unchanged chunks** get the two codex lanes only. Measured runs show the
  late-pass stochastic discoveries on untouched code come almost entirely
  from the diverse-model lanes (codex + contract-inspector), while re-run
  re-run generalists just re-find what they already found.
- Inspector lanes still run once per pass on the full diff, so unchanged
  chunks keep their external-contract sweep.

### After the workflow returns

The workflow returns `{findings, dismissed, laneErrors, fixVerifications}`.

1. Write the findings JSON to `$out_dir/findings.json` (audit trail), and
   assemble `$out_dir/review.md` **deterministically** from the structured
   fields — no synthesis agent. For each finding emit a
   `### [SEVERITY] <title>` section with File, Category, Validity,
   Confidence, Found by, Issue, Why it matters, Recommended fix, and the
   verifier's rationale as "Verification"; append "## Dismissed as invalid"
   and "## Dismissed as out-of-scope" bullets from `dismissed`. (Optional:
   on the **final clean pass only**, you MAY spawn one `opus` agent for a
   2–3 paragraph "Overall assessment" / "what did reviewers collectively
   miss" meta-check — it is off the loop's critical path there.) Delegate
   the rendering: write `findings.json` yourself (the structured findings
   are already in the tool result), then spawn an `opus` subagent to
   assemble `review.md` from it per the format above.
2. On re-review passes, `fixVerifications` carries one entry per applied fix
   (`{finding, fixed, rationale, new_issues}`) — feed it into step 12.
3. If `laneErrors` is non-empty, tell the user which lanes errored. If **all
   reviewer lanes** errored, stop.
4. If `findings` is empty (and, on re-review passes, every fix verified with
   no new issues), the pass is clean.
5. Do not lose verified `out-of-scope` findings in the dismissed audit trail.
   When verification confirms one is real, concrete, and directly exposed by
   the PR review, append it to an invocation-wide
   `$follow_up_candidates_path`. Carry the finding, verification
   rationale, source branch/commit, review path, and why the fix does not
   belong in the current PR. Deduplicate across lanes, passes, and stack
   branches by the underlying problem, not merely by title.

## 6. (Reserved)

Aggregation now happens inside the workflow (step 5). There is no separate
aggregator step.

## 7. Print findings to the terminal

Print a compact, scannable summary from the returned `findings`:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Review — <branch>
<N> files, <LOC> lines changed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▲ CRITICAL (count)
  1. <title>
     <file>:<line>  [concurrency, codex-b]  confidence: 95
     <one-line fix>

▲ HIGH (count)
  ...

▲ MEDIUM (count)
  ...

▲ LOW (count)
  ...

▲ NIT (count)
  ...

▽ Dismissed by verification: <count>

Full report: <absolute path to review.md>
```

Keep each finding to **two lines**: title line (title + lanes + confidence)
and fix line (recommended fix). The full details live in `review.md`.

**Never echo full finding bodies into the main session.** Parse
`findings.json` to this compact summary (and the step-9 triage table) only —
do not print or `cat` the `finding`/`why_it_matters`/`recommended_fix` prose,
and do not pretty-print the whole JSON to the terminal. Triage decisions are
made from `{severity, verdict, confidence, file, line, title}`; the prose stays
on disk in `review.md`/`findings.json`. Re-dumping all N findings' bodies each
pass is the single biggest avoidable main-context cost of the loop.

If the review reports **no actionable findings**, print that prominently. If
`$follow_up_candidates_path` is empty, exit successfully. If it contains
verified candidates, treat the current PR as converged and continue to step 13
instead of dropping the follow-up queue.

---

## 8. Triage input

Triage works directly on the structured `findings` array returned by the
workflow (also saved to `findings.json`) — no report parsing. Each finding
already carries: `title`, `severity` (re-scored by the verifier), `verdict`
(valid | likely | disputed), `confidence` (re-scored), `category`, `file` +
`line_start`/`line_end`, `finding`, `recommended_fix`, and the verifier's
`rationale`.

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

**Simplicity findings** (from `simplicity-inspector`) follow the same table
with one exception: a finding whose fix is a **different approach** — one
that rewrites how the PR solves the problem rather than deleting a piece of
it — is always **Discuss**, whatever its severity. Deleting a one-user
abstraction, an unused knob, or copy-paste bulk is an ordinary auto-fix and
should just happen; re-architecting the branch mid-loop is the user's call.
Show the line counts both ways when you ask.

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

For **discuss** findings only, use `AskUserQuestion`:

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

**Delegation:** do not apply fixes in the main session. Spawn one **fixer
subagent** (`Agent`, `model: opus`) per fix pass with the full JSON of the
fix-now findings, the repo root, and the project-docs paths, instructed to
execute substeps 1–6 below for each finding in severity order and then run
the compile gate, returning a one-line summary per fix plus the compile-gate
result. The main session never reads source files. The ≥4-disjoint-fixes
Workflow fan-out below still applies when it qualifies. Only on a one-file
fix may you apply it inline.

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
7. Do **not** run the full test suite, lints, or commit yet — `/ci` runs
   only after the review loop converges.

If while implementing a fix you discover that the real solution materially
expands the PR, reclassify it as a grouped follow-up, record the concrete
scope reason in `$follow_up_candidates_path`, and continue with the remaining
in-scope fixes. Only stop for a genuinely ambiguous correctness decision.

### Optional: fan out independent fixes

When there are **≥4 fix-now findings whose edits touch disjoint file
regions**, applying them serially in the main loop is the slow path. Instead
dispatch them as a small `Workflow`: one agent per finding-cluster (a
cluster = findings whose `file` + line ranges overlap or are adjacent), each
agent reading the source and applying its cluster's fix with `Edit`. Use
`isolation: 'worktree'` only if two clusters touch the same file. The main
loop then reviews the combined patch instead of authoring every edit. For
≤3 fixes, or fixes that interact, stay in the main loop — the coordination
overhead isn't worth it. Either way, the compile gate below still runs on
the merged result.

### Compile gate

After all fix-now items are done, run the **compile gate** before any
re-review (when fixes were delegated, the fixer subagent runs it and reports
the result — only re-run it in the main session if anything was applied
inline afterwards): the project's fastest typecheck scoped to what was touched (for
Rust, `cargo check -p <touched crates>`; otherwise the project's equivalent).
Fix any compile errors immediately — never enter a re-review pass with code
that doesn't compile; that wastes an entire review pass. The compile gate is
NOT a substitute for `/ci` — full tests and lints still run only after
convergence.

Then proceed directly to step 12 (re-review).

## 12. Re-review loop (independent full passes)

Re-review after every fix pass. **Why the loop exists:** AI review is
stochastic — each independent pass over the same diff surfaces *different*
findings. The primary purpose of looping is this **coverage** (shaking out
issues an earlier pass happened to miss), and only secondarily catching bugs
the fixes introduced. So a re-review is NOT a narrow sweep of the fix delta —
it is a **fresh, independent panel pass over the full updated diff**, with
fix-verification folded in. The adaptive panel sizing (step 5) is what keeps
a genuine full re-pass affordable.

**CRITICAL: The re-review is NOT optional.** After fixing findings, you MUST
re-review at least once. Do not skip it because the fixes "looked
straightforward." Only a review pass determines when the loop is done.

**CRITICAL: Convergence requires a CLEAN pass.** The loop is ONLY done when
an independent panel pass returns no new actionable findings AND every
applied fix verified. Fixing the last batch is NOT convergence. The pattern
is always `review → fix → review → fix → review(clean) → done`. You can
never end on a fix.

### Prepare the updated diff

```bash
git diff "$parent" > "$out_dir/diff-iter${N}.patch"   # updated full diff
git diff HEAD --stat | tail -1                          # what the loop changed
```

Re-run the **size gate** against this updated diff, comparing with the step-2
baseline. If it trips, note it and raise it at convergence — do not split a
branch with unreviewed fixes in flight.

Bump `diffPath` to `diff-iter${N}.patch` in the `args` (a single field — the
script rebuilds the lanes from it), rewrite the shared `context.txt` to point
at it, and re-pick `laneKeys` with the **step 5 adaptive sizing** rule against
the updated diff. On chunked runs, also apply the **changed-chunks-only** rule
from step 5: regenerate the per-chunk patches, full panel only for chunks whose
patch differs from the previous iteration, codex lanes only for unchanged
chunks (chunked runs pass an explicit `lanes` array).

### Formatter-only skip (R3)

If the only thing that changed since the last reviewed state is the output
of a deterministic formatter/hook (e.g. `cargo fmt`, `yamlfmt`, `prettier`,
`deno fmt`) and that formatter now passes, **do not spawn a review pass over
it** — formatter output cannot introduce a review-worthy finding. Treat that
delta as verified by construction and skip straight to convergence. Confirm
the change is purely a formatter's doing (the diff matches what re-running
the formatter produces); if any hand-written line changed, run the full
re-pass.

### Run the re-review pass

Re-invoke the **same `review-panel` workflow** (reuse its `scriptPath` from
step 5) with the updated lanes and this loop's fixes:

```json
{
  "repoRoot": "<repo_root>",
  "contextPath": "<out_dir>/context.txt",
  "outDir": "<out_dir>",
  "diffPath": "<out_dir>/diff-iter${N}.patch",
  "laneKeys": [ ...adaptively-sized lane keys... ],
  "fixedFindings": [ ...{title, file, line_start, line_end} per fix THIS loop... ]
}
```

The workflow returns `{findings, dismissed, laneErrors, fixVerifications}`:
the panel's fresh stochastic findings, plus one `fixVerifications` entry per
applied fix (`{finding, fixed, rationale, new_issues}`).

### Overlap /ci with the re-review (R6)

The re-review and `/ci` both read the same working tree and don't interact,
so launch them **concurrently** after a fix pass — start `/ci` (invoke the
`ci` skill) in the background as you fire the re-review workflow. Then gate
convergence on both:

- Re-review clean **and** `/ci` green, `/ci` made no changes → converged,
  go to step 13.
- Re-review clean **and** `/ci` made changes (lint/format) → apply the
  formatter-only skip above; if the changes are purely formatter output you
  are converged, otherwise run one more re-pass over the new delta.
- Re-review **not** clean → ignore the in-flight `/ci` result (you will
  re-run it next convergence), and proceed to the next bullet.

`/ci`'s own "amend via `gt modify -a` on success" step is overridden by this
loop: never amend in single-branch mode (hard rule 4 — the user drives
version control); in stack mode the stack flow amends once per branch after
convergence, so `/ci` must not amend separately there either.

### Interpret the result

1. Save the result to `$out_dir/review-iter${N}.json` (audit trail).
2. **Clean** = `findings` empty AND every `fixVerifications` entry has
   `fixed: true` with no `new_issues`. Converge per the /ci-overlap rules
   above. If the size gate tripped during any pass, raise it here — before
   step 13 — and, if the user approves, execute the split and continue as
   stack mode from the bottom of the new stack.
3. **Not clean**: collect the panel `findings`, any `fixed: false`
   verifications (re-fix those), and `new_issues` from the verifications.
   Filter out anything substantively identical to a finding already fixed or
   dismissed (compare file + line range + description) — this is what stops
   the stochastic passes from re-litigating settled findings forever. If
   nothing new remains, treat as clean. Otherwise increment the iteration
   counter and loop back to step 9 (triage) with only the remaining
   findings.

**Cap at 4 review passes total** (initial + up to 3 re-reviews). Because
re-review is stochastic, hitting the cap usually means findings are
genuinely thinning out, not that fixes are breaking things — but stop and
tell the user either way: report what each pass found and let a human judge
whether the residual findings are noise or a real unresolved problem.

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

Invoke `/linear-cli` and follow its exact `--help`, file-based description,
required-metadata, and approval rules:

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
   batch. Ask once with `AskUserQuestion` to create the group; allow edits or
   removal of individual children. This single approval covers the displayed
   parent and child drafts—do not ask again per child unless a draft changes
   materially.
6. After approval, create the parent first, then create each child as a true
   Linear subissue of that parent (not merely a `blocks` relation). Run
   `linear issue create --help` and `linear issue update --help` before using
   parent flags; use `/linear-cli`'s raw GraphQL fallback only if the installed
   CLI cannot set parentage.
7. Record the parent and ordered child IDs/URLs in
   `$out_dir/follow-up-issues.json`. Order children by severity, then discovery
   order. Update the parent description with child links if Linear does not
   render them automatically.

Do not create one parent per finding or per stack branch. One review-loop
invocation produces at most one new follow-up parent.

## 14. Implement grouped follow-ups serially

After the issue group is created, hand the whole group to
`/implement-issue-stack` — do not drive a serial `/implement-issue` queue
yourself. That skill already expands a parent into its children, orders them
(blocked-by, then Linear's manual ordering, then issue number), and stacks one
Graphite branch/PR per child with CI gating between them.

1. Capture the branch where review-loop started. The handoff requires a clean
   tree. If this loop applied reviewed fixes in single-branch mode, invoke
   `/graphite` and run `gt modify -a` once to fold only those fixes into the
   current branch before leaving it. This is the sole single-branch amend
   exception; do not submit directly from review-loop.
2. Invoke `/implement-issue-stack <PARENT-ID>` — the parent alone, not the
   child list. Passing the parent keeps ordering authority in one place: if the
   user re-orders sub-issues in Linear between review and implementation, the
   stack follows Linear, not `follow-up-issues.json`. Only pass an explicit
   ordered child list when the parent also has implementable scope of its own
   and you already know the user wants children only.
3. Record the branch, PR, and final status it reports for each child back into
   `follow-up-issues.json`.
4. If a child's nested review discovers another genuine scope-expanding
   finding, reuse this parent and append the new child to it rather than
   creating a nested follow-up parent. Search the parent's existing children
   first to avoid duplicate issues or cycles.
5. `/implement-issue-stack` stops the stack on the first child that blocks or
   fails. Take its report as-is: update the parent with the blocker and report
   exactly where execution stopped. Never restart the remaining children by
   hand.
6. When all children finish, update the parent status to match the repository's
   Linear policy and the children's actual states. Do not mark the parent Done
   while any child PR is still in a state that keeps its issue open.
7. Return to the branch where review-loop started before printing the final
   summary.

`/implement-issue-stack` runs each child through the full `/implement-issue`
flow autonomously, so there are no per-child plan-approval checkpoints. It is
strictly serial: child N's complete workflow (plan, implement, review, PR, CI)
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

Below the summary block, add these prose sections:

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

**Decomposition** — if the size gate fired, state the final size, whether the
PR was split, the resulting branch order, and the backup branch name. If the
user chose "Split later", repeat the recommendation here so it is not lost.
Omit this section when the gate never fired.

Then stop. Outside stack mode and the explicit grouped-follow-up handoff in
step 14, do not auto-run `gt modify`, `gt submit`, or any other mutation.

**In stack mode**, steps 13–15 run only after the upstack walk has converged;
the wrapper must not create or implement follow-ups per branch.

---

## Failure modes

- **All reviewer lanes error:** stop immediately, tell the user, don't
  proceed to triage. (Inspector lanes erroring is non-fatal.)
- **Review returns no actionable findings:** print "No findings"; exit only
  when the follow-up candidate queue is also empty. Otherwise continue to
  grouped issue creation.
- **A fix turns out to be larger than expected:** reclassify it as a grouped
  follow-up when the solution is genuinely separate scope; stop only if the
  classification or correctness decision is ambiguous.
- **Review pass cap hit (4 passes):** stop and tell the user. Summarize
  what each pass found. Because re-review is stochastic, late passes usually
  surface *thinning* residual findings rather than fix-induced regressions —
  but let a human judge whether what remains is noise or a real unresolved
  problem.
- **The workflow itself fails mid-run:** relaunch with
  `{scriptPath, args, resumeFromRunId}` — completed lanes return cached
  results instantly; only the failed part re-runs.
- **The follow-up parent fails to create:** report the exact `linear` error,
  preserve every draft, and stop before creating children.
- **A follow-up child fails to create:** report the exact error, preserve the
  draft and already-created group, and stop before serial implementation so
  the parent is not silently incomplete.
- **A child run inside `/implement-issue-stack` blocks or fails:** that skill
  stops the stack; update the parent with the blocker and leave later children
  unstarted.
- **The user says "stop" mid-loop:** immediately stop, then print the
  summary with what was completed so far. Do not silently abandon the rest.
- **Codex not installed:** warn the user and drop the codex lanes
  (9 lanes instead of 11). Nine lanes is still valuable.
- **The diff is oversized but has no clean seam:** report that the groups
  cannot be made to compile independently, keep the PR whole, and continue the
  loop. Do not force a split that produces broken intermediate branches.
- **A split leaves the stack top differing from the backup branch:** stop
  immediately, keep `backup/<branch>-predecomp`, and hand the user the
  `git diff --stat` output. Never reconcile it by hand.

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
   an approved size-gate split may `gt modify -a` once to clean the tree
   before splitting, and then rewrites branches under that same approval;
   and a created follow-up queue may `gt modify -a` once in single-branch mode
   to make the reviewed starting branch clean before invoking
   `/implement-issue-stack`. Review-loop itself never submits;
   `/implement-issue-stack` owns all branch/PR mutations and submission for the
   follow-up children.
5. Always use `--description-file` with `linear issue create`, never inline
   `--description`.
6. Always re-verify findings against the current source before applying
   fixes — the code may have changed since the review.
7. Keep fixes surgical. No "while I'm here" cleanups.
8. Run the compile gate after every fix pass; launch `/ci` concurrently
   with the re-review (both read the same working tree). If `/ci` makes
   non-formatter code changes, run another re-review pass over them; a
   pure-formatter delta is verified by construction and needs no pass.
9. Cap at 4 review passes. Convergence requires a clean independent pass —
   never end on a fix. Stop and ask the user if you don't converge.
10. Each review/re-review pass runs as a single `Workflow` invocation —
    never run reviewers sequentially or hand-roll the fan-out with
    individual Agent calls.
11. Use `--sandbox read-only` for codex — non-negotiable.
12. Adversarial verification (of findings AND of fixes) happens inside the
    workflow, never in the main session (context pollution). The report is
    assembled deterministically in the main session from structured
    findings — no synthesis agent on the critical path.
13. Never fabricate findings when a lane errors — record the failure from
    `laneErrors`.
14. Save `findings.json`, the assembled `review.md`, and each
    `review-iter${N}.json` to `$out_dir` before printing to the terminal.
15. Never silently modify `.gitignore` — ask permission to add
    `.tmp/` if missing.
16. Re-review is always a fresh INDEPENDENT panel pass over the full updated
    diff (stochastic coverage), adaptively sized per step 5 — never a narrow
    fix-delta sweep. The only thing that skips a pass is a verified
    formatter-only delta.
17. This command runs only where the `Workflow` tool exists — the main
    session. Never run it inside a subagent and never wrap it in an
    orchestrator subagent. Delegate prompt building, report assembly, and
    fix application to closing `opus` subagents (steps 4, 5, 11); every
    agent runs on Opus or Codex, never smaller. The Workflow
    invocations, triage, and user checkpoints always stay in the main
    session.
18. **Keep large generated artifacts out of the main context.** Pass lanes
    compactly (`laneKeys`, not 9 spelled-out objects) and `fixedFindings` as
    locator-only objects; build the Workflow `args` with a Bash/python step and
    pass it straight to the tool. Never `Read` the generated args JSON or the
    diff patches back into the main session, and never pretty-print full
    finding bodies — those live on disk for the workflow/`review.md`. This is
    quality-neutral (same lanes, same verification) and is the loop's biggest
    main-context saving.
19. Create at most one follow-up parent per review-loop invocation. Every
    verified scope-expanding finding becomes a true child issue under it.
20. Hand follow-up children to `/implement-issue-stack` (passing the parent ID),
    never to a hand-rolled serial `/implement-issue` queue. It runs children
    strictly in series and stops on failure with the remaining queue preserved.
21. Nested review loops from those child implementations reuse the same parent
    and append deduplicated children to the serial queue; they never create a
    hierarchy of follow-up parents.
22. Never split a PR without explicit user approval of the split plan, never
    while fixes are in flight (converge first), and never without a
    `backup/<branch>-predecomp` branch plus a verified empty
    `git diff --stat` against it. A split that loses content is worse than an
    oversized PR — stop and report rather than hand-patch a mismatch.
