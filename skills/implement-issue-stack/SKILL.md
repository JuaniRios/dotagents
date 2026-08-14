---
name: implement-issue-stack
description: >
  Implement an ordered list of Linear issues, or expand a parent into
  its children and stack one Graphite PR per child. Each child runs
  implement-issue autonomously (plan → implement → review-loop → CI).
  Use when the user wants a whole issue group shipped as a stack.
argument-hint: "<parent-issue> | <issue-1> <issue-2> ..."
allowed-tools: Bash(*), Read, Write
disable-model-invocation: true
---

# implement-issue-stack

You babysit. Each issue runs the `implement-issue` flow autonomously.
Your context stays tiny: no source, no diffs, no full logs.

Read `~/Github/dotagents/skills/implement-issue/SKILL.md` once at the
start (per-issue steps) and
`~/Github/dotagents/skills/panel-runtime.md` for planner/critics.

The user's request is an ordered list of issue ids, or one parent to
expand. Empty: ask once.

Autonomous overrides vs implement-issue:

- No user questions after pre-flight (except the parent-has-own-scope
  question below).
- Plan critique replaces plan approval. review-loop decides findings.
  `pr-description`'s gate replaces description confirmation.
- Plan and implement are two sequential children, not one.

Log skipped checkpoints to `.tmp/issue-stack/<ID>.md`.

## 0. Pre-flight (only interactive moment)

1. Confirm cwd and a clean tree. `gt sync` once now, never mid-stack.
2. `linear issue view` each id. Record any `<ID> Implementation Plan`
   document — those skip machine planning.
3. **Parent expansion.** An argument with children is never implemented
   as a stack entry:
   - children only → replace with children
   - children **and** own scope → ask: children / parent / both
     (parent last)
   - a child that itself has children → expand one more level, then
     stop if still nested
   - skip Done/Canceled/Duplicate children
   - **Order:** blocked-by topology, then Linear's
     `subIssueSortOrder`/`sortOrder`, then issue number
4. Confirm the ordered list, which issues use an attached plan, the
   base branch, and that each PR will be pushed and CI waited on. Then
   go autonomous.

## Per-issue

1. **Skeleton + cross-link** — implement-issue steps 1–4 in the host
   (cheap one-liners). Hand-written WIP body is enough; do not run
   `pr-description` for the skeleton.
2. **Plan then implement** — two children. Attached plan document →
   skip the planner. Otherwise planner + critics per panel-runtime
   (auto-approve). Implementer reads the plan file. `gt modify -a`.
3. **Review + describe** — `review-loop` in this session (its panel
   must not be wrapped). Decide findings; log deferrals; do not create
   Linear issues. Then `gt modify -a`, then `pr-description`.
4. **Submit + CI** — `gt ss`, wait for this HEAD (or local `nix run
   .#ci` when Graphite skips 6th+). Red → `ci-fix` child, cap 3, then
   **stop the stack**.
5. **Advance** — next `gt create` stacks on this branch. Never start
   N+1 unless N verified and CI green.

## Hard rules

1. You babysit; children implement. review-loop runs here only so the
   panel is not nested.
2. Sequential issues. They share the worktree.
3. Version control via `gt`. `gt sync` only in pre-flight.
4. Planner/critics per panel-runtime. `claude -p` is allowed for Fable
   or Opus when the host is not Claude (Max plan, `env -u
   ANTHROPIC_API_KEY`). Never impersonate a dropped lab.
5. Parent is expanded, never implemented, unless the user picked
   "parent too".
6. Every skipped checkpoint is a line in the issue log.
