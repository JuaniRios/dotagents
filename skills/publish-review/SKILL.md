---
name: publish-review
allowed-tools: Bash(gh:*), Bash(git:*), Bash(find:*), Bash(date:*), Bash(test:*), Bash(ls:*), Bash(jq:*), Bash(mktemp:*), Bash(cat:*), Bash(rm:*), Bash(wc:*), Read, Grep, Glob
description: Approve clean PR reviews automatically; publish reviews with findings as pending inline comments. Run after /review-pr.
argument-hint: [review-dir-path]
---

Publish the review outcome for each PR: **APPROVE** when a completed review
has no actionable findings, or a **pending** review with inline comments when
findings remain. Clean reviews are approved automatically under the user's
standing preference, including when called directly from `/review-pr`.

## 1. Locate the review

If the user's arguments is provided, treat it as the path to a review directory or
`review.md` file.

If the user's arguments is empty, find the most recent review:

```bash
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
latest=$(ls -dt "$repo_root"/claude-local-ctx/reviews/pr-*/ 2>/dev/null | head -1)
```

If no review directory is found, stop and tell the user to run `/review-pr`
first.

Confirm the review file exists at `$latest/review.md`. Read it.

## 2. Extract PR metadata

From the review directory name, extract the PR number (e.g., `pr-534-...` ->
`534`). Verify the PR exists:

```bash
gh pr view <number> --json number,headRefOid,headRefName,baseRefName,url
```

Record the `headRefOid` (commit SHA) -- needed for the review API.

## 3. Parse findings

Read `review.md` and extract every finding that has:
- A `**File:**` line with `<path>:<line>` (or `<path>:<start>-<end>`)
- A severity level (from the `### [SEVERITY]` heading)

**Stop parsing** when you hit "Findings dismissed as invalid" or "Findings
dismissed as out-of-scope" sections. Skip everything from those sections
onward.

For each finding, extract:
- `path` -- relative file path
- `line` -- the line number (use start line if a range)
- `severity` -- HIGH, MEDIUM, LOW, NIT
- `title` -- the finding title from the heading
- `issue` -- the `**Issue:**` content
- `fix` -- the `**Recommended fix:**` content

## 4. Select the review outcome

Make this decision separately for every PR in a batch:

- **No actionable findings in a completed review:** submit `event: "APPROVE"`
  immediately. Never use COMMENT, an issue comment saying "no actionable
  findings", or an empty pending review as a substitute. No further user
  confirmation is needed. This also applies after verifying that all findings
  have been fixed.
- **Actionable findings remain:** compose the inline comments below and create
  a pending review, unless the user already authorized submission.
- **Incomplete review or parsing failure:** do not infer a clean review from
  an empty comments array. Report the incomplete result. Findings without an
  inline anchor still count as findings.

For a clean review, verify the current head still matches the reviewed SHA.
If it changed, review the new changes before approving. Check for an existing
approval by this user on that SHA and reuse it instead of posting a duplicate.
Create the approval with this payload:

```json
{
  "commit_id": "<reviewedHeadRefOid>",
  "event": "APPROVE",
  "body": ""
}
```

POST it to `repos/{owner}/{repo}/pulls/{number}/reviews`, then verify the
returned state is `APPROVED` and report its URL. If a clean review was already
created as pending, submit that review with `event: "APPROVE"` through
`repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/events` instead.
An API rejection is a failure to approve, not permission to substitute a
COMMENT review. Report the error.

## 5. Compose inline comments (findings only)

For each finding, write a **concise, human-like** inline comment. Do NOT
copy the markdown verbatim. Transform each finding into a short review
comment that:

- Leads with what's wrong in 1-2 sentences
- Suggests the fix in 1-2 sentences
- Prefixes with a severity tag: `[high]`, `[medium]`, `[low]`, `[nit]`
- Reads like a human reviewer wrote it, not a report generator

Example transformation:

**From review.md:**
> `### [HIGH] Non-unique Svelte {#each} key in trade history panel`
> `**Issue:** The {#each} key is trade.filledAt + trade.symbol + trade.venue.
> Two rapid fills for the same symbol on the same venue at the same timestamp
> will produce duplicate keys...`
> `**Recommended fix:** Add a unique identifier to the Trade DTO...`

**Becomes inline comment:**
> `[high] This key can collide when two fills happen at the same
> timestamp for the same symbol/venue -- Svelte will silently skip
> rendering a row. Add a unique ID to the Trade DTO (e.g. aggregate ID
> or tx_hash:log_index) and use that as the key.`

## 6. Create a pending review (findings only)

Build a JSON payload file with all comments:

```json
{
  "commit_id": "<headRefOid>",
  "body": "Cross-review findings -- <N> comments.",
  "comments": [
    {
      "path": "relative/file/path.rs",
      "line": 42,
      "body": "[high] Concise comment here."
    }
  ]
}
```

Write the JSON to a temp file and POST it:

```bash
payload=$(mktemp -t publish-review.XXXXXX.json)
# ... write JSON to $payload ...
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --method POST \
  --input "$payload"
rm "$payload"
```

For reviews with findings, omit `event` to create a PENDING review unless
submission is already authorized. This rule does not apply to clean reviews,
which require `event: "APPROVE"`.

## 7. Verify and report

For an approval, report APPROVED and the review URL. For a pending review
with findings, print:

```
Review created on PR #<N> (PENDING -- not submitted)

  <count> inline comments:
    [severity] <path>:<line> -- <short title>
    ...

  Dashboard: <pr-url>

Go to Graphite to inspect, edit, and submit the review.
```

## Hard rules

1. A completed review with no actionable findings MUST be submitted as
   APPROVE. Reviews with findings default to PENDING unless submission is
   already authorized. Never replace a clean approval with a COMMENT review.
2. Never copy markdown findings verbatim as comments. Rewrite them to be
   concise and human-readable.
3. Skip dismissed findings (invalid and out-of-scope sections).
4. Every comment must reference a specific file and line number. Skip
   findings that don't have a parseable `**File:** path:line`.
5. Verify the current head against the reviewed SHA. For a clean approval,
   review any new changes first. For findings, verify their current anchors
   before posting; do not approve an unreviewed head.
6. If the API call fails, show the error and the payload so the user can
   debug.

## Failure modes

- **No review.md found**: Tell the user to run `/review-pr` first.
- **PR not found or closed**: Stop and report.
- **Head SHA mismatch**: Review the new changes before approving; verify
  current anchors before posting findings.
- **API rate limit**: Report the error, suggest waiting.
- **Finding without file/line**: Skip it, mention it was skipped in the
  summary.
