---
name: implement-issue-stack
description: "Use when the user asks to implement a stack or ordered batch of Linear issues, or to implement all sub-issues of a Linear parent issue, with minimal supervision — creating one Graphite branch/PR per issue and advancing only when each issue is verified."
---

# implement-issue-stack

Codex-native port of the Claude skill `implement-issue-stack`.

Implement an ordered stack of Linear issues. Each issue should become its own
independently reviewable Graphite branch/PR, with dependencies represented in
the stack order and Linear relations.

## Required Companion Skills

- `implement-issue` for the per-issue workflow.
- `linear-cli` for issue inspection and updates.
- `graphite` for all branch/commit/submit operations.
- `review-loop`, `pr-description`, and `ci-fix` as each issue reaches those
  phases.

## Inputs

The user must provide one of:

- an ordered list of issue IDs/URLs;
- a single Linear parent issue, which you expand into its sub-issues (see
  "Parent expansion" below); or
- a Linear project that can be resolved into an ordered set.

If order is still ambiguous after applying the ordering rules, ask for the
order before starting.

## Parent expansion

If an input issue has sub-issues, expand it into its children. The parent is
never implemented as a stack entry.

- Parent with children and no scope of its own: replace it with its children.
- Parent with children and real implementable scope in its own description: ask
  the user whether to implement the children, the parent alone, or both (parent
  last). This is worth an upfront question, because a wrong answer builds the
  whole stack wrong.
- Issue with no children: a normal stack entry, unchanged.
- Nested children (a child that itself has sub-issues): expand one more level
  in place, then stop. Deeper nesting means the tree is not stack-shaped —
  report it and stop.
- Mixed inputs (a parent plus loose issue IDs): expand the parent in place and
  keep the surrounding input order.
- Skip children already Done, Canceled, or Duplicate, and say so in the
  confirmation.

Order the resulting children by strict precedence:

1. Blocked-by relations first. Topologically sort so a child never precedes an
   issue that blocks it (`linear issue relation list <ISSUE_ID>`, or the
   GraphQL query below). A cycle among children is fatal: report it and stop.
2. Linear's manual ordering. Break ties by the parent's own sub-issue ordering
   (`subIssueSortOrder`, ascending; fall back to `sortOrder` if the schema
   lacks it) — the order the user sees when dragging sub-issues in Linear.
3. Issue number, ascending, as the last tiebreak only.

The `linear` CLI does not expose sort order, so fetch children in one raw
GraphQL call. Dump and grep the schema first
(`linear schema -o "${TMPDIR:-/tmp}/linear-schema.graphql"`) instead of
trusting field names from memory:

```bash
linear api '{ issue(id: "RAI-800") { children { nodes {
  identifier title subIssueSortOrder sortOrder
  state { name type }
  children { nodes { identifier } }
  relations { nodes { type relatedIssue { identifier } } }
  inverseRelations { nodes { type issue { identifier } } }
} } } }' | jq '.data.issue.children.nodes'
```

## Workflow

1. Preflight the stack.
   - Resolve all issue IDs and titles, expanding any parent issue into its
     ordered children first (see "Parent expansion").
   - Read dependencies and blockers:
     ```bash
     linear issue relation list <ISSUE_ID>
     ```
   - Verify the requested order does not contradict known blockers.
   - Check the repo and Graphite stack:
     ```bash
     git status --short
     gt log short
     ```
   - Stop if unrelated dirty changes would be touched.

2. Create a stack plan.
   - One branch/PR per issue.
   - Shared prerequisites go first.
   - Conflict-prone or integration-heavy work goes last.
   - Record the plan with `update_plan`.
   - Keep a session log under `.tmp/issue-stack/<timestamp>.md`.

3. Ask for one upfront confirmation if the stack will run autonomously. After
   confirmation, do not ask between issues unless blocked by ambiguity, failing
   external systems, or a risky irreversible action.

4. For each issue in order:
   - Follow the `implement-issue` workflow.
   - Keep changes scoped to that issue's branch.
   - Preserve `implement-issue`'s comment discipline on every branch: Rust
     should express intent through names, types, structure, and control flow;
     code comments are only for non-obvious rationale, invariants, safety, or
     external constraints. Keep PR and Linear comments sparse and
     outcome-focused, never a line-by-line implementation narrative.
   - Run targeted checks and required final checks according to the session
     policy.
   - Run review before submission for substantive code.
   - Submit with Graphite.
   - Poll CI for the current commit — the run whose `headSha` matches the pushed
     HEAD, not just the newest run on the branch. If no run appears for this HEAD
     (~90s), Graphite skipped CI for this branch (6th+ in the stack); run the
     full local CI matrix (`nix run .#ci`) as the gate instead.
   - Do not start the next issue until the current issue is submitted and its
     required checks are green (remote run for this HEAD, or the local matrix
     when Graphite skipped CI) — never a stale run from an earlier commit —
     unless the user explicitly authorizes parallel CI risk.

5. Handle failures.
   - If CI fails, use `ci-fix` and resubmit the same branch.
   - If an issue is blocked by missing information, record the blocker in the
     log, update Linear if appropriate, and stop rather than guessing.
   - If the stack order is wrong, explain the conflict and ask for the new order
     before moving branches.

6. Finish the stack.
   - Report each issue, branch, PR, CI status, and Linear status.
   - If the stack came from a parent, report the parent and whether every child
     now has a PR. Do not move the parent to Done yourself.
   - Note any skipped issue and the exact blocker.
   - Leave the working tree clean or explicitly report uncommitted files.

## Hard Rules

- Do not combine unrelated issues into one branch.
- Do not implement a parent issue as a stack entry; expand it. Do not re-order
  children on your own judgement of size or difficulty — the precedence is
  blocked-by, then Linear's manual ordering, then issue number.
- Do not move to the next issue while the current branch has unresolved test,
  review, or CI failures.
- Do not use raw git mutations; use Graphite.
- Do not ask repeated checkpoint questions after the upfront autonomous-run
  confirmation.
- Keep the `.tmp/issue-stack` log out of git.
- Do not accumulate explanatory source comments or overly specific PR/Linear
  comments as the stack grows. Let the code carry implementation detail.
