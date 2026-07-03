---
name: review-reminder
description: "Use when the user asks to remind or nudge a colleague to review the pull requests they authored: assemble the user's open Graphite PRs that still need review, group them by theme with Graphite links, and send a formatted 'Review reminder' message to the group chat via Telegram."
---

# review-reminder

Codex adaptation of the Claude slash command `review-reminder`. Follow the
workflow below, but use Codex-native tools and normal user questions where the
original mentions Claude-only mechanisms.

Compatibility notes:

- Treat `$ARGUMENTS` as the relevant arguments or intent from the user's
  request (an optional `@reviewer` handle and/or an optional `owner/repo`).
- Replace `AskUserQuestion` with a concise question to the user when a decision
  is required.
- Ignore Claude `allowed-tools` and `argument-hint` as tool-permission metadata.
- When the workflow mentions the `telegram-message` command, follow that send
  workflow directly (it is reproduced in Step 6 below).

# Review Reminder — nudge a reviewer with my open PRs

Assembles the open pull requests I authored that still need review, groups them
by theme with Graphite links, and sends a "Review reminder" message to the group
chat via Telegram.

## Step 1 — Determine the repo

Default to the current repo. If the argument names an `owner/repo`, target that
instead.

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

This yields `<owner>/<repo>` (e.g. `ST0x-Technology/st0x.liquidity`). Use:

- `<repo>` (the part after `/`) for the message title line.
- `https://app.graphite.com/github/pr/<owner>/<repo>/<number>` for each PR link.

## Step 2 — Fetch my open PRs needing review

```bash
gh pr list --author @me --state open \
  --json number,title,url,isDraft,reviewDecision,baseRefName,headRefName \
  --limit 100
```

Include a PR only when it is **open, not a draft, and not already APPROVED**
(`reviewDecision` of `REVIEW_REQUIRED`, `CHANGES_REQUESTED`, or empty). Drop
drafts and approved PRs — those don't need a review nudge.

If nothing qualifies, tell the user there's nothing awaiting review and stop.
Never send an empty reminder.

## Step 3 — Group and describe

Sort the PRs into a few themed sections (e.g. "Infra / CI", "Transfer &
rebalancing fixes", "Extended-hours stack"). Signals for grouping:

- **Graphite stack membership** — PRs in the same stack usually belong in one
  section. Derive stack links from the base/head ref chain (a PR whose
  `baseRefName` equals another's `headRefName` sits above it), or read
  `gt log short`.
- **Shared theme** in the titles (CI, transfers, config, extended hours, etc.).

For each PR, write a **short human description** — a cleaned-up paraphrase of the
title, not necessarily verbatim (e.g. "CI permissions for externally-merged
workflow"). Order PRs within a section in the order that reads best (stack
base-first, or by logical dependency); this is a judgment call, so pick a
sensible order rather than raw PR-number order.

## Step 4 — Compose the message

Match this format exactly:

```
Review reminder: <repo>

Could you please review these Graphite PRs when you have a chance?

<Section>
- #<number> (https://app.graphite.com/github/pr/<owner>/<repo>/<number>) <description>
- ...

<Section>
- ...

Thanks!
```

Notes:

- If a reviewer handle was passed in the argument, prepend it on its own line
  above the title (e.g. `@highonhopium_josh`).
- Blank line between the title, the intro line, each section, and "Thanks!".
- Section headers may be wrapped in `<b>...</b>` for Telegram scannability; the
  Graphite URLs auto-link, so no `<a>` tags are needed.

## Step 5 — Show the draft and confirm

Print the composed message and the proposed grouping to the terminal. Ask the
user to approve, re-group, or edit descriptions. Iterate until they approve.

## Step 6 — Send via Telegram

Credentials live in `~/.config/telegram-bot.env`
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

1. Write the approved message to `/tmp/telegram-message.txt`. Escape `&`, `<`,
   `>` inside descriptions (not inside `<b>` tags).
2. Send with HTML parse mode:

```bash
source ~/.config/telegram-bot.env
python3 -c "
import os, urllib.request, urllib.parse, json

with open('/tmp/telegram-message.txt') as f:
    text = f.read()

token = os.environ['TELEGRAM_BOT_TOKEN']
chat_id = os.environ['TELEGRAM_CHAT_ID']
url = f'https://api.telegram.org/bot{token}/sendMessage'
data = urllib.parse.urlencode({
    'chat_id': chat_id,
    'text': text,
    'parse_mode': 'HTML'
}).encode()
req = urllib.request.Request(url, data)
resp = json.load(urllib.request.urlopen(req))
if resp.get('ok'):
    print('Sent to Telegram')
else:
    print(f'Telegram error: {resp}')
"
```

3. Print "Review reminder sent to Telegram."

## Hard rules

1. Never send an empty reminder — if no PRs need review, say so and stop.
2. Only include open, non-draft, not-yet-APPROVED PRs I authored.
3. Always show the draft and get approval before sending — never auto-send.
4. Use Telegram HTML parse mode — not MarkdownV2.
5. Never invent PR numbers or links — every entry comes from `gh pr list`.
6. If `telegram-bot.env` is missing or the send fails, print the message and
   tell the user to copy-paste it manually.

## Failure modes

- **`gh` not authenticated** — tell the user to run `gh auth login` and stop.
- **Not in a repo / no GitHub remote** — ask which `owner/repo` to target.
- **Only drafts/approved PRs remain** — report that nothing needs a nudge; do
  not send.
