---
name: graphite-review-reminder
allowed-tools: Bash(gh:*), Bash(gt:*), Bash(git:*), Bash(jq:*), Bash(date:*), Bash(cat:*), Bash(test:*), Bash(source:*), Bash(curl:*), Bash(printf:*), Read, Write, Skill
description: Find open GitHub/Graphite PRs awaiting review and send a pretty Telegram reminder with Graphite links.
argument-hint: "[send|draft] [audience/context]"
---

# Graphite Review Reminder

Find open PRs awaiting human review, format a concise Telegram HTML reminder with Graphite links, and send it through the Telegram bot when approved or explicitly requested.

## Step 1 - Resolve repo and auth

Invoke the `graphite` skill.

Run:

```bash
gh auth status
gh repo view --json nameWithOwner,url
```

Default to the current repository. If the user explicitly asks for all repos, use `gh search prs --author @me --state open` and inspect each result.

## Step 2 - Gather PRs

Run:

```bash
gh pr list --author @me --state open --limit 100 \
  --json number,title,url,isDraft,reviewDecision,headRefName,baseRefName,createdAt,updatedAt,statusCheckRollup,reviewRequests,latestReviews
```

For candidate PRs, fetch commit timing when needed:

```bash
gh pr view <number> --json number,title,commits,latestReviews,reviewRequests,statusCheckRollup
```

Also run:

```bash
gt log
```

or:

```bash
gt log long
```

Prefer Graphite's human status labels when available because GitHub can leave `reviewDecision` blank for stacked PRs that Graphite still marks as needing approval.

## Step 3 - Classify awaiting-review PRs

Include open, non-draft PRs authored by the current GitHub account when any of these are true:

- Newly opened or never reviewed: no human latest review exists, or GitHub says `REVIEW_REQUIRED`.
- Review requested: `reviewRequests` is non-empty, or Graphite says `Needs more reviewers` / `Needs more approvals`.
- Ready for re-review: the latest author commit is newer than the latest `CHANGES_REQUESTED` review, or review was explicitly re-requested after feedback was addressed.
- Stale waiting: the PR is still open, non-draft, not approved, not blocked by failing checks, and has been waiting more than 24 hours since the relevant review request / latest author commit / creation time.

Exclude PRs when any of these are true:

- Draft.
- Already approved, Graphite `Ready to merge`, or otherwise waiting only on merge.
- Required checks are failing.
- `CHANGES_REQUESTED` with no later author commit and no re-review request.
- Closed or merged.
- Not authored by the current GitHub account, unless the user explicitly asks for another author or all local stack PRs.

If checks are pending but not failing, include the PR and add a short `CI pending` note only when useful.

## Step 4 - Bucket and sort

Use exactly one bucket per included PR:

- `New / first review`: no human review yet, newly opened, or `REVIEW_REQUIRED` without prior blocking feedback.
- `Ready for re-review`: latest author commit is newer than the latest changes-requested review, or reviewers were re-requested.
- `Still waiting`: waiting more than 24 hours and not better classified above.

If a PR fits multiple buckets, prefer `Ready for re-review`, then `New / first review`, then `Still waiting`.

Sort stack PRs in dependency order when Graphite provides stack order; otherwise sort by oldest waiting first.

## Step 5 - Build Graphite links

Prefer URLs shown by Graphite tooling. If needed, construct links as:

```text
https://app.graphite.com/github/pr/<owner>/<repo>/<number>
```

Use Graphite links in the message, not GitHub PR links, unless Graphite data is unavailable.

## Step 6 - Draft Telegram HTML

Use Telegram HTML:

- `<b>...</b>` for section headings.
- `<a href="...">#123</a>` for PR links.
- Plain `-` bullets.
- Blank lines between sections.
- Escape `&`, `<`, and `>` in titles and free-form text.
- Keep it short enough to paste into a colleague chat.

Template:

```html
<b>Review reminder: owner/repo</b>

Could you please review these Graphite PRs when you have a chance?

<b>New / first review</b>
- <a href="GRAPHITE_URL">#123</a> Short human title

<b>Ready for re-review</b>
- <a href="GRAPHITE_URL">#456</a> Short human title

<b>Still waiting</b>
- <a href="GRAPHITE_URL">#789</a> Short human title (waiting 3d)

Thanks!
```

Omit empty sections.

## Step 7 - Approval and send

If the user explicitly asked to send the reminder in the current request, that counts as approval to send after composing the draft. Otherwise, show the full formatted draft and wait for explicit approval.

Use the `telegram-message` workflow if available. Otherwise:

1. Write the approved HTML to `/tmp/telegram-message.txt`.
2. Source credentials without printing them:

```bash
source ~/.config/telegram-bot.env
```

3. Send with `curl`:

```bash
curl -sS --fail-with-body \
  -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text@/tmp/telegram-message.txt" \
  --data-urlencode "parse_mode=HTML" \
  --data-urlencode "disable_web_page_preview=true"
```

4. Confirm whether Telegram accepted the message.

## Hard Rules

1. Default to current-repo PRs authored by the logged-in GitHub account.
2. Include PRs awaiting first review, ready for re-review after addressed feedback, and stale unreviewed PRs.
3. Do not include drafts, already-approved/ready-to-merge PRs, or PRs blocked by failing required checks.
4. Do not treat `CHANGES_REQUESTED` as excluded when the author has pushed newer commits or re-requested review.
5. Use Graphite links whenever available.
6. Never print Telegram credentials or read secret files into the conversation.
7. If classification is ambiguous, mention the ambiguous/excluded PRs in the response instead of silently mixing blocked work into the reminder.

## Failure Modes

- `gh` is unauthenticated: report the auth failure and stop.
- The repo is not Graphite-managed: use GitHub metadata for classification and construct Graphite links only if owner, repo, and PR number are known.
- GitHub output is too large: re-run without `statusCheckRollup`, then inspect checks only for candidate PRs.
- Telegram config is missing or send fails: print the formatted HTML message and say it was not sent.
