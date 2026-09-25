---
name: review-pr
description: >
  Cross-review a pull request by number or URL without checking it out.
  Plain-language TL;DR, then the same multi-model panel as review-loop
  (opus 5.5, sol 5.6, Cursor Grok 4.6, composer 2.5, flash 3.7,
  with an opus 5.5 deep lane). Stays in the session so you can
  inspect the result. Only verified blockers (a critical or should fix that
  two models stand behind) request changes; otherwise the review is
  approved, with any minor comments inline.
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

Same adaptive catalogue as review-loop (panel-runtime). Then run
**blocker verification** from panel-runtime on every `critical` or `high`
finding that only one model raised. Write `findings.json` and `review.md`. `review.md` has **no** per-finding
agent attribution (keep that in `findings.json` only).

## 6. Stay in the session

Print the compact summary, then a short "what actually changed".

The verdict follows from the findings; publish it immediately with
`publish-review`, pinned to the reviewed head SHA. This is the user's standing
preference; do not ask for another confirmation or wait for a separate publish
request.

- **Any verified blocker** (panel-runtime, blocker verification): submit a
  **REQUEST_CHANGES** review with every finding inline, blockers and minor
  ones alike.
- **No verified blocker:** submit an **APPROVE** review, with any `minor` and
  `nit` findings as inline comments on it. Keep those few and worth reading.
  Never post a clean result as a COMMENT review, issue comment, or empty
  pending review.

Report the review and its URL. An incomplete panel, a `critical` or `high`
finding that could not be verified, or findings lost during parsing do not
count as either outcome and must not be submitted.

Posted comments: ASD-STE100, lowercase severity prefix
(`critical:` / `should fix:` / `minor:` / `nit:`, mapped from the schema
severity as in panel-runtime; one prefix per comment), no em dashes, no
AI/model mentions, no `#1` prefixes. `line` must be in the diff hunk.

## Hard rules

1. Never check out the PR.
2. Panel per panel-runtime. Quorum required.
3. No attribution in anything posted to GitHub.
4. A completed review with no verified blocker must be submitted as APPROVE,
   with its minor comments inline, never COMMENT or PENDING. Apply this per PR
   in a batch, including follow-up reviews after all blockers are fixed.
5. A review with a verified blocker must be submitted as REQUEST_CHANGES
   immediately. A `critical` or `high` finding from one model never blocks
   until two other models confirm it. Never leave inline findings as PENDING
   or submit them as COMMENT. If GitHub rejects the event, report the
   failure; do not downgrade the review.
