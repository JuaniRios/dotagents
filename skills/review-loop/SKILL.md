---
name: review-loop
description: >
  Cross-review the current branch with a multi-model panel (opus 5,
  sol 5.6, grok 4.6, flash 3.7, fable 5 deep), auto-fix findings, and
  re-review until clean. Use before you submit something you wrote.
  Pass `stack` to walk the whole upstack.
  If the PR grows too big, offer to split it. Group verified out-of-scope
  fixes under one Linear parent and implement them with implement-issue-stack.
argument-hint: "[stack]"
allowed-tools: Bash(*), Read, Write, Edit
---

# review-loop

Review → fix → lean re-review until a clean independent pass. Automatic
by default. Read `~/Github/dotagents/skills/panel-runtime.md` first — it
owns models, wrappers, lanes, adaptive sizing, lean rounds, quorum,
and Max preflight. This file owns the branch loop around that panel.

The loop is **guest-shaped**: it runs in any harness (claude, codex,
grok, agy). Fan out with that host's parallel primitive. Native lanes
are isolated children pinned to the **model**, not the babysitter.

**Argument:** nothing = current branch only, no version-control
mutation. `stack` = walk the upstack and `gt modify -a` per branch
after that branch converges (still never `gt submit` unless the user
asks).

## Stack mode

When the user asked for `stack`, wrap steps 1–15:

1. Record the starting branch.
2. Run the single-branch loop on the current branch. After the first
   branch, a dirty tree from `gt up` restack is expected; stop only on
   unrelated edits.
3. After clean + `/ci` green, `gt modify -a` if this branch changed.
4. `gt up`. Repeat from 2 until top.
5. A 4-pass cap on any branch stops the walk.
6. Accumulate follow-up candidates across branches; run steps 13–14
   once at the end.
7. Return to the starting branch and print a per-branch summary.

Each branch gets its own `$out_dir` and its own 4-pass cap.

## Size gate — split an oversized PR

Check at step 2 (after `diff.patch`) and at step 12 (updated diff).
Hand-written size only:

```bash
git diff --numstat "$parent" -- . \
  ':(exclude)**/*.lock' ':(exclude)**/*.snap' ':(exclude)**/generated/**' \
  ':(exclude)**/vendor/**' ':(exclude)**/fixtures/**' \
  | awk '{add+=$1; del+=$2; files++} END {print files" files, "add+del" lines"}'
```

Propose a split when any of: >800 hand-written lines, >20 hand-written
files, the loop grew the diff >30% from step 2, or ≥3 unrelated
concerns. Under every threshold and one concern: say nothing.

Ask before splitting. Mid-loop: finish convergence first. Build an
ordered compiling stack (groundwork, then each concern; tests travel
with the behavior). Original branch stays on top. Safety net:
`git branch backup/<branch>-predecomp`. After the split, `git diff
--stat backup/<branch>-predecomp` must be empty. Then continue as
stack mode from `gt bottom`.

Use the `graphite` skill for every version-control mutation.

**Sensitive** (auth, secrets, money, on-chain, migrations) **always
wins over size** for panel sizing — see panel-runtime.

## 1. Preflight

```bash
git rev-parse --show-toplevel
gt log short
command -v gt claude codex grok agy
git status --porcelain
```

Dirty tree (single-branch, first pass): stop. Missing `gt`: stop.
Missing a model's CLI: drop every lane that needs that model and say so.

Run Max preflight from panel-runtime (`claude -p "/usage"`).

## 2. Scope and workspace

Always diff against `gt parent`, not trunk.

```bash
parent=$(gt parent 2>/dev/null || git merge-base origin/HEAD HEAD)
branch=$(git rev-parse --abbrev-ref HEAD)
repo_root=$(git rev-parse --show-toplevel)
ts=$(date +%Y-%m-%d_%H-%M-%S)
safe_branch=$(echo "$branch" | tr '/' '_')
out_dir="$repo_root/.tmp/reviews/${ts}-${safe_branch}"
mkdir -p "$out_dir"
follow_up_candidates_path=${follow_up_candidates_path:-"$out_dir/follow-up-candidates.json"}
```

```bash
git diff "$parent" > "$out_dir/diff.patch"
git diff --name-status "$parent" > "$out_dir/files.txt"
```

Empty diff: stop. >5000 lines: warn and ask. Run the size gate. If
`.tmp/` is not gitignored, ask before adding it.

## 3. Project context

Collect `CLAUDE.md` / `AGENTS.md` paths. If a PR exists, take the
author-written body (strip bot HTML footers). Reviewers read these
themselves — keep only paths in the host.

## 4. Build prompts

One setup child (host model) writes prompt files per panel-runtime:
shared base + per-lane focus. Composite lanes get every covered
inspector body inlined from `~/Github/dotagents/skills/<name>/SKILL.md`.
The host does not author long prompt text.

## 5. Run the panel

One parallel fan-out as specified in panel-runtime for this pass
(adaptive pass 1, or lean thereafter). Write `findings.json` and
assemble `review.md` on disk. Print a two-line-per-finding summary.
Never dump finding bodies into the host.

If all reviewer lanes error, or quorum fails: stop (or mark
`incomplete`). Carry verified out-of-scope findings into
`$follow_up_candidates_path`.

Chunk diffs over 3500 lines by domain. Inspectors/composites still
run once on the full diff. Re-review chunks: full strength only if
that chunk's patch changed.

## 6–10. Triage

Work from `findings.json`, not `review.md`. Default actions:

| Severity | Verdict | Confidence | Action |
|---|---|---|---|
| critical | any | any | Auto-fix |
| high/medium | valid or likely | ≥50 | Auto-fix |
| high/medium | disputed | any | Discuss |
| low | valid | ≥75 | Auto-fix |
| low | else |  | Auto-dismiss |
| nit | any | any | Auto-dismiss |

Scope gate: a real fix that expands the PR's stated goal → grouped
follow-up, not auto-fix. A simplicity finding that is a *different
approach* (rewrite the design) is always Discuss; deleting dead
machinery is an ordinary auto-fix.

Ask the user only about Discuss items. Then print the consolidated
plan and proceed.

## 11. Fix

One host fixer child per pass, surgical edits, tests if the project
docs require them. ≥4 disjoint fix clusters may fan out as isolated
children. Compile gate after the pass (`cargo check -p` or equivalent).
Never enter re-review with a broken compile.

## 12. Re-review

Independent lean pass over the full updated diff (panel-runtime).
Launch `/ci` concurrently. Formatter-only delta: skip the pass.
Cap 4. Never end on a fix. Filter findings already fixed or dismissed.

## 13–14. Grouped follow-ups

After convergence, if `$follow_up_candidates_path` is non-empty: draft
one Linear parent + one child per candidate via `linear-cli` (file
descriptions, required metadata, one approval). Then
`implement-issue-stack <PARENT-ID>`. One parent per invocation. Nested
reviews append children to that parent.

Single-branch mode may `gt modify -a` once before that handoff so the
starting branch is clean. Review-loop itself never submits.

## 15. Summarize

Fixed / grouped / dismissed, report paths, what actually changed, and
whether a split happened. Stop. Outside stack mode and step 14, do not
mutate version control.

## Hard rules

1. Auto-fix the table; only ask about Discuss.
2. Grouped follow-up only when the fix expands this PR or the user
   asked. Never drop a verified out-of-scope finding.
3. Never create Linear issues without showing the batch and getting
   approval.
4. Never amend/submit except: stack mode per branch; an approved split;
   the step-14 clean-tree amend. `implement-issue-stack` owns follow-up
   submits.
5. `--description-file` for Linear bodies.
6. Re-read source before applying a fix.
7. Surgical fixes. Compile gate every fix pass. `/ci` overlaps
   re-review.
8. Cap 4. Quorum required. Never end on a fix.
9. Panel per panel-runtime. No second orchestrator. No impersonating a
   dropped model.
10. Reports on disk. Host prints summaries only.
11. Follow-ups: one parent, then `implement-issue-stack`.
12. Never split without approval, a backup branch, and an empty
    `git diff --stat` against it.

## Failure modes

- All lanes error or quorum fails → stop, do not triage.
- Clean pass + empty follow-up queue → done.
- 4-pass cap → stop and report per-pass history.
- Missing model CLI → drop those lanes, continue if quorum still holds.
- Split top ≠ backup → stop, keep the backup, do not hand-patch.
