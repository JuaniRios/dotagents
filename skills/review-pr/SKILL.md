---
name: review-pr
description: >
  Cross-review a pull request by number or URL without checking it out.
  Plain-language TL;DR, then the same multi-model panel as review-loop
  (opus 5, sol 5.6, grok 4.6, flash 3.7, fable 5.1 deep). Stays in the session so you can
  inspect the result; clean reviews are approved automatically, while reviews
  with findings are submitted as changes requested.
  Use when reviewing someone else's PR.
argument-hint: "<pr-number | pr-url>"
allowed-tools: Bash(*), Read, Write
---

# review-pr

Review a PR that is **not** checked out. Read
`~/Github/dotagents/skills/panel-runtime.md` for the panel. This file
owns fetch-without-checkout and the post-review conversation.

The user's request is the PR number, URL, or `owner/repo#n`. Empty =
the PR for the current branch.

## 1. Resolve the PR

```bash
gh pr view <ref> --json number,title,author,headRefName,baseRefName,url,body,headRepository,baseRepository,headRefOid,baseRefOid,state,isDraft,additions,deletions,changedFiles
```

Closed, merged, or draft: warn and ask before continuing.

## 2. Workspace

```bash
out_dir="$repo_root/.tmp/reviews/pr-${number}-${ts}-${safe_branch}"
mkdir -p "$out_dir"
gh pr diff "<ref>" > "$out_dir/diff.patch"
```

Empty diff: stop. >5000 lines: warn and ask. Ask before adding `.tmp/`
to `.gitignore`.

## 3. Fetch the head for context

```bash
git fetch <head-remote> "$head_sha"
```

Reviewers read files via `git show $head_sha:<path>`. Do not check out
the PR.

## 4. TL;DR

Before the panel, print two plain-language sentences: what the PR does
and why. No identifiers. Then run the panel — do not wait.

## 5. Panel

Same adaptive catalogue as review-loop (panel-runtime). Write
`findings.json` and `review.md`. `review.md` has **no** per-finding
agent attribution (keep that in `findings.json` only).

## 6. Stay in the session

Print the compact summary, then a short "what actually changed".

When the completed review has no actionable findings, submit an **APPROVE**
review immediately, pinned to the reviewed head SHA, using the clean-review
path in `publish-review`. This is the user's standing preference; do not ask
for another confirmation or wait for a separate publish request. Never post
"no actionable findings" as a COMMENT review, issue comment, or empty pending
review. Report the approval and its URL.

When actionable findings remain, submit a **REQUEST_CHANGES** GitHub review
immediately, pinned to the reviewed head SHA, using `publish-review`. Every
inline finding must belong to that submitted changes-requested review, never a
COMMENT or PENDING review. This is the user's standing preference and needs no
additional confirmation. An incomplete panel or findings lost during parsing
do not count as a clean review and must not be submitted as either outcome.

Posted comments: ASD-STE100, lowercase severity prefix
(`critical:` / `should fix:` / `minor:` / `nit:`), no em dashes, no
AI/model mentions, no `#1` prefixes. `line` must be in the diff hunk. Include
`event: "REQUEST_CHANGES"` so the review is submitted and blocks merging when
the repository's branch protection honors requested-changes reviews.

## Hard rules

1. Never check out the PR.
2. Panel per panel-runtime. Quorum required.
3. No attribution in anything posted to GitHub.
4. Completed clean reviews must be submitted as APPROVE, never COMMENT or
   PENDING. Apply this per PR in a batch, including clean follow-up reviews
   after all findings are verified fixed.
5. Reviews with findings must be submitted as REQUEST_CHANGES immediately.
   Never leave inline findings as PENDING or submit them as COMMENT. If GitHub
   rejects REQUEST_CHANGES, report the failure; do not downgrade the review.
