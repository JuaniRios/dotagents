---
allowed-tools: Bash(git:*), Bash(gh:*), Bash(jq:*)
description: Backstop the externally-merged CI label. Sweeps the past week's master commits, applies the externally-merged label to closed-but-merged PRs that are missing it (so Linear marks the issue Done), and audits whether the externally-merged.yaml workflow actually fired and succeeded for each.
argument-hint: [days]
---

# Reconcile externally-merged PRs

Graphite's merge queue lands batched PRs by pushing squash commits to master and
then **closing** the PRs instead of merging them. Linear only treats a closed PR
as merged when it carries the `externally-merged` label, so the linked issue
stays open without it. The `.github/workflows/externally-merged.yaml` CI workflow
is supposed to apply that label automatically on the `closed` event — this
command is the manual backstop that catches gaps and verifies the CI is working.

Run from the repo root. `gh` auto-detects the repo from the working directory.
Default window is the **past 7 days**; if `$ARGUMENTS` is a number, use that many
days instead.

## Step 1 — Collect PRs referenced by recent master commits

```bash
git log origin/master --since="<N> days ago" --first-parent \
  --pretty=format:'%H %s'
```

Extract the trailing `(#NNN)` from each commit **subject** — that is the
squash/merge convention identifying the PR that landed the commit. Ignore bare
`#NNN` mentions in commit bodies (they reference other issues/PRs, not the
landing PR). Deduplicate the PR numbers.

If `origin/master` is stale, `git fetch origin master` first.

## Step 2 — Classify each PR

For each PR number:

```bash
gh pr view <N> --json number,state,merged,labels,title,headRefName,closedAt
```

- **state `MERGED`** — landed via a native GitHub merge. No label needed; skip.
- **state `CLOSED`** — Graphite closed it after pushing the squash commit. This
  is the externally-merged case. Check its labels:
  - Has `externally-merged` → CI worked. Record as **OK**.
  - Missing `externally-merged` → **GAP**. Record for Step 3 + Step 4.
- **state `OPEN`** — unexpected (commit on master but PR still open). Record as
  **anomaly** and surface it; do not label.

## Step 3 — Apply the label to gaps (automatic)

For every GAP PR, apply the label without asking:

```bash
gh pr edit <N> --add-label externally-merged
```

If the label does not exist in the repo yet (`gh pr edit` errors on unknown
label), create it to match the CI workflow's definition, then retry:

```bash
gh label create externally-merged \
  --color 6f42c1 \
  --description "Graphite MQ merged this PR; Linear should treat the close as a merge"
```

## Step 4 — Audit why CI missed each gap

A GAP means the CI workflow either didn't fire, didn't match its guard, or
failed. For each GAP PR, find the workflow run for its head branch around its
close time:

```bash
gh run list --workflow "Externally merged label" \
  --json databaseId,headBranch,event,status,conclusion,createdAt --limit 50
```

Match on `headRefName` from Step 2. Then classify the cause:

- **No run found** — the `closed` event didn't trigger the workflow, or the
  branch was deleted before it ran. Likely the PR was closed by a sender other
  than `graphite-app[bot]`, or its head ref started with `gtmq` (both are
  intentionally skipped by the workflow's `if:` guard). Note which guard
  excluded it.
- **Run exists, `conclusion: success`, but label absent** — the workflow's
  "Check Graphite merged this PR" step found no `Merged by the [Graphite merge
  queue]` marker comment, so it no-opped. The PR was likely merged through a
  path that didn't leave that marker. Flag for investigation.
- **Run exists, `conclusion: failure`** — the workflow errored. Pull the logs
  and report the failing step:

  ```bash
  gh run view <databaseId> --log-failed
  ```

Do **not** try to fix the workflow automatically — report the cause and suggest
a concrete next step.

## Step 5 — Report

Print a single summary table covering every PR in the window:

| PR | State | Label before | Action | CI verdict |
|----|-------|--------------|--------|------------|

Then below the table:

- **Labels applied:** list of PRs newly labelled in Step 3.
- **CI investigation:** for each gap, the Step 4 cause and suggested next step.
- **Anomalies:** any OPEN PRs from Step 2.

If there were zero gaps and every closed PR already had the label, say so
explicitly — that means the CI workflow is doing its job for this window.

## Hard rules

1. Only ever apply `externally-merged` to PRs in **CLOSED** state that are
   referenced by a squash commit on master. Never label OPEN or MERGED PRs.
2. Extract PR numbers from the commit **subject's** trailing `(#NNN)` only —
   not from `#NNN` mentions in bodies.
3. Apply labels automatically (no confirmation), but never modify the CI
   workflow or close/reopen PRs without explicit user instruction.
4. Always report the CI verdict for each gap — applying the label silently hides
   a broken automation. The label is the cure; the audit is the point.

## Failure modes

- **`origin/master` stale** → `git fetch origin master` before Step 1.
- **`gh` not authenticated** → stop and tell the user to run `gh auth login`.
- **Label missing in repo** → create it (Step 3) and retry.
- **Branch deleted, no run found** → report as "run not retained"; the label
  application still stands as the fix.
