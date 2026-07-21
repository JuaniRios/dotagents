---
allowed-tools: Bash(gh:*), Bash(gt:*), Bash(git:*), Bash(source:*), Bash(python3:*), Bash(cat:*), Read, Write, AskUserQuestion
description: Draft and send a grouped "Review reminder" message listing my open Graphite PRs that still need review. Groups PRs by theme with Graphite links and sends to the group chat via Telegram. Use when asking a colleague to review the PRs I authored.
argument-hint: "[@reviewer] [owner/repo]"
---

# Review Reminder — nudge a reviewer with my open PRs

Assembles the open pull requests I authored that still need review, groups them
by theme with Graphite links, and sends a "Review reminder" message to the group
chat via Telegram. Reuses the `telegram-message` send path.

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

`CHANGES_REQUESTED` PRs are awaiting *my* changes, not a fresh review — Step 3
handles them specially (they may need a re-review).

If nothing qualifies, tell the user there's nothing awaiting review and stop.
Never send an empty reminder.

## Step 3 — Flag PRs awaiting my changes (re-reviews)

Split the qualifying PRs into two buckets by `reviewDecision`:

- **Fresh review** — `REVIEW_REQUIRED` or empty. Awaiting a first look (or all
  prior reviews were dismissed). Straightforward review requests.
- **Re-review** — `CHANGES_REQUESTED`. A reviewer already looked and requested
  changes, so the PR is awaiting *my* fixes. It only belongs in a reminder once
  I've pushed those fixes and want another look.

If there are any re-review PRs, **before drafting** list them and ask the user
whether to include them (via `AskUserQuestion` or a concise prompt), e.g. "These
have changes requested and are awaiting your fixes: #978, #981. Include them as
re-review requests?"

- If the user says **no**, drop them and draft with the fresh-review PRs only.
  If that leaves nothing to send, tell the user and stop — never send an empty
  reminder.
- If the user says **yes**, for each included re-review PR:
  1. **Re-request review** from the reviewer(s) who requested changes, so the
     nudge actually re-triggers their GitHub review request:

     ```bash
     # logins whose latest review is CHANGES_REQUESTED
     gh pr view <number> --json latestReviews \
       -q '.latestReviews[] | select(.state == "CHANGES_REQUESTED") | .author.login'

     # re-request each returned login
     gh api --method POST \
       repos/<owner>/<repo>/pulls/<number>/requested_reviewers \
       -f 'reviewers[]=<login>'
     ```

  2. **Tag the line as a re-review** in the composed message so the reviewer
     knows changes were addressed (see Step 5).

If a re-request call fails (e.g. the login can't be re-requested), note it to
the user and still include the PR with its re-review tag.

## Step 4 — Group and describe

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

## Step 5 — Compose the message

Load the `write-as-me` skill first. This message is sent to a colleague as
him, so the framing line and every PR description have to sound like him:
short, direct, warm, no corporate padding.

The voice applies to the prose — the ask, the section names, and each PR's
one-line description. The scaffolding below (links, PR numbers, structure) is
fixed; keep it exactly as specified.

Match this format exactly:

```
Review reminder: <repo>

Could you please review these Graphite PRs when you have a chance?

<Section>
- <a href="https://app.graphite.com/github/pr/<owner>/<repo>/<number>">#<number></a> <description>
- ...

<Section>
- ...

Thanks!
```

Notes:

- If a reviewer handle was passed in the argument, prepend it on its own line
  above the title (e.g. `@highonhopium_josh`).
- Blank line between the title, the intro line, each section, and "Thanks!".
- Hyperlink each PR number with a Telegram HTML `<a>` tag —
  `<a href="…/<number>">#<number></a>` — so the reader sees a clickable `#978`,
  never a raw URL. Do not paste the bare Graphite URL into the visible text; the
  link belongs in the `href`. Section headers may also be wrapped in `<b>...</b>`
  for scannability.
- A PR the user opted to include as a re-review (Step 3) is tagged on its line
  so the reviewer knows changes were addressed — append `— re-review (changes
  addressed)` to that PR's description, e.g. `- <a href="…/978">#978</a> show
  per-asset config flags — re-review (changes addressed)`.

## Step 6 — Show the draft and confirm

Print the composed message and the proposed grouping to the terminal. Ask the
user (via `AskUserQuestion` or a concise prompt) to approve, re-group, or edit
descriptions. Iterate until they approve.

## Step 7 — Send via Telegram

Credentials live in `~/.config/telegram-bot.env`
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

1. Write the approved message to `/tmp/telegram-message.txt`. Escape `&`, `<`,
   `>` inside descriptions (not inside `<b>`/`<a>` tags), and escape any `&` in
   an `href` URL as `&amp;`.
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
7. Only re-request review for PRs the user explicitly opts to include as
   re-reviews — never re-request reviewers silently or for fresh-review PRs.
8. Always load the `write-as-me` skill before composing — the message goes
   to a teammate as him. Voice the prose (the ask, section names, PR
   descriptions); leave the links and structure exactly as templated.

## Failure modes

- **`gh` not authenticated** — tell the user to run `gh auth login` and stop.
- **Not in a repo / no GitHub remote** — ask which `owner/repo` to target.
- **Only drafts/approved PRs remain** — report that nothing needs a nudge; do
  not send.
