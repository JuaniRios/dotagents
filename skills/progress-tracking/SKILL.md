---
name: progress-tracking
allowed-tools: Bash(linear:*), Bash(git:*), Bash(gh:*), Bash(cat:*), Bash(date:*), Bash(jq:*), Bash(tdl:*), Bash(python3:*), Bash(ls:*), Bash(grep:*), Read, Write, Grep, Glob
description: Gather progress on both bots by default (or hedge-bot / issuance-bot alone) from Linear issues, GitHub PRs, git history, the dev-channel daily reports (everyone's, exported via tdl), and the live /pnl endpoint via the pnl-review skill (liquidity side), since the last run or a custom time range. Produces a single ASD-STE100 report for higher-ups (TL;DR, KPIs, risks, next-report expectations) and saves it to disk.
argument-hint: "[both|hedge-bot|issuance-bot] [since <timeframe>]"
---

# Progress tracking

Compile a progress report for a project by pulling from Linear issues and
git history. The report covers everything since the last time this command
was run, or since a user-specified time range.

## Step 1 — Parse arguments

The argument is: `<project> [since <timeframe>]`

Examples:
- (empty) or `both` — combined report on both bots, since last run
- `hedge-bot` — liquidity bot only, since last run
- `issuance-bot` — issuance bot only, since last run
- `both since last week` — combined, override: last 7 days
- `issuance-bot since last 10 days` — override: last 10 days
- `hedge-bot since 2026-04-01` — override: specific date

Extract:
1. **Project name** — the first word (e.g., `hedge-bot` or `issuance-bot`)
2. **Time override** — everything after `since` (optional)

If no project name is provided, default to **`both`** — a single combined
report covering the two bots. The configured projects are `hedge-bot` (the
liquidity bot, `st0x.liquidity`) and `issuance-bot` (the Alpaca ITN issuer,
`st0x.issuance`); naming one still produces a single-bot report. Both live
in the same Linear team (RAI), so relevance filtering (Step 5) matters.

### Combined mode (`both`, the default)

One report, both bots — higher-ups care about the product, not repo
boundaries. Deltas from the single-bot flow:

- **Since date**: the OLDER of the two projects' `last_run` values, so
  nothing falls in a gap. If the two differ materially, say so once in
  the report.
- **Steps 3/3b (git, PRs)**: run for BOTH repos; keep results labeled per
  repo.
- **Step 3c (dev channel)**: one export serves both — use everything
  relevant to either bot instead of filtering to one.
- **Step 3d (PnL)**: still hedge-bot only (issuance has no /pnl); frame
  it as the liquidity side's number.
- **Step 5 (relevance)**: include issues relevant to EITHER bot, tagged
  with which; excluded = belongs to neither (other products). Shared
  work (event-sorcery, shared crates) is included once, marked shared.
- **Step 6 (report)**: one TL;DR and one narrative covering both, with
  every accomplishment/risk labeled by bot where it isn't obvious; the
  KPI table gets per-bot rows where metrics differ (incidents, output)
  and shared rows where they don't. The optional completed-work appendix
  gets per-bot subsections.
- **Step 7 (save)**: filename `combined-<YYYY-MM-DD>.md` (the single
  STE report); update BOTH projects' `last_run`.
- **Step 2b (continuity)**: read the most recent prior report of ANY kind
  (combined or single-bot) per bot, so expectations from older single-bot
  reports still get closed out.

## Step 2 — Load config and determine date range

Read the config file:

```bash
cat ~/Github/dotagents/data/progress-tracking.json
```

Look up the project by name. If the project isn't found, tell the user
and list available projects.

Determine the "since" date:
- If the user provided a `since` override, parse it into a date. Use
  `date` to resolve relative expressions (e.g., "last week" → 7 days ago,
  "last 10 days" → 10 days ago, or a literal ISO date).
- If no override, use `last_run` from the config. If `last_run` is null
  (first run), default to 14 days ago and tell the user.

Store the resolved date as an ISO 8601 string for use in queries.

## Step 2b — Load the previous report (continuity)

Reports live in `~/Github/dotagents/data/progress-tracking/reports/`.
Read the most recent prior report for this project (skip one dated today —
that's a re-run). Two things to extract:

1. Its **"By the next report"** section (if present): every expectation
   listed there must be answered in the new report — happened, slipped, or
   dropped, with a one-line why. This is what makes consecutive reports
   accountable to each other; a higher-up reading two reports in a row
   should never wonder what happened to a promise.
2. Its period end date, to sanity-check the new range has no gap.

If no prior report exists, note "first report — no continuity data" and
move on.

## Step 3 — Fetch git history

Run git log on the project's repo:

```bash
git -C <repo_path> log --since="<date>" --format="%h %ad %s" --date=short --all
```

Also get a summary of files changed:

```bash
git -C <repo_path> log --since="<date>" --format="" --shortstat --all | tail -5
```

If the repo path starts with `~`, expand it. Collect all commits — these
will go into the report.

## Step 3b — Fetch GitHub PRs

PRs often contain richer descriptions than commit messages or Linear
issues. Fetch both merged and open PRs from the repo:

```bash
cd <repo_path>

# Merged PRs in the date range
gh pr list --state merged --search "merged:>=<date>" \
  --json number,title,author,mergedAt,body,labels,url --limit 100

# Open PRs (in review / in progress)
gh pr list --state open \
  --json number,title,author,createdAt,body,url --limit 50
```

PR descriptions are a primary source for the executive summary — they
explain the *why* and *impact* in ways that commit messages and issue
titles often don't. When writing the summary, prefer PR descriptions
over issue titles for understanding what was actually accomplished.

Also use PRs to catch work that has no Linear issue attached. A merged
PR without a linked issue still represents real progress that should
appear in the report.

**Never cite the raw open-PR count as "work in review."** Open PRs are a
mix: the active stack being landed, deliberately paused stacks, and stale
drafts from months ago. Fetch `createdAt` and `isDraft`, bucket by
recency (active = created in the last ~2 weeks or clearly being iterated;
paused = tied to a Paused Linear project; stale = months old, untouched),
and report the buckets — "~30 active PRs (56 open in total incl. paused
stacks and stale drafts)", never just "56 PRs in review".

## Step 3c — Fetch dev-channel daily reports (everyone's, via tdl)

The whole team posts end-of-day reports in the dev Telegram channel. Export
the channel over the report range with `tdl` so the synthesis sees
**everyone's** daily reports plus the surrounding discussion — incidents,
prod status, manual interventions, decisions, and the *why* behind the
work. This context is invisible to git/Linear/PR data, and teammates'
reports cover work that left no trace in this repo at all.

Pre-flight:

```bash
if ! command -v tdl >/dev/null; then echo "tdl: NOT INSTALLED"
elif ! tdl chat ls >/dev/null 2>&1; then echo "tdl: NOT LOGGED IN"
else echo "tdl: ok"; fi
```

The work chats live in `~/.config/daily-report-telegram-chats.txt` (one
chat ID or @username per line, `#` for comments — the same file the
daily-report skill maintains). If it's missing, run `tdl chat ls`, ask the
user which chat is the dev channel (ask the user), and write the file.

Export each configured chat over the range and parse each export
immediately (export and parse in the same loop — variables set inside a
piped `while read` subshell don't survive it):

Everyone formats their end-of-day post differently — observed first lines
include `📋 Daily Report — <date>`, `# Daily Update <date>`, a bare
`UPDATE` / `Update` / `update`, `Daily update — July 16`, `Logging off for
the day.`, and `Weekly catch-up`. Never grep for one literal header.
Detect reports with two complementary rules:

1. **First-line pattern** (case-insensitive, after stripping `#`/`*`/emoji):
   contains `daily report`, `daily update`, `update`, `eod`, `logging off`,
   `catch-up`, or `weekly` — and the message is ≥ ~200 chars.
2. **Long-message fallback**: any message ≥ ~1200 chars that the pattern
   missed is probably a multi-day catch-up, incident writeup, or detailed
   status post — read those too.

Export with `--raw`: the plain export has NO sender field, but `--raw`
adds `raw.FromID.UserID`. Map user IDs to names using the teammate-DM
section of the chats config (each `#` comment line names the person, the
next line is their numeric user ID — for DMs the chat ID IS the user ID).
Unmapped IDs stay numeric; that's fine.

```bash
SINCE_EPOCH_S=$(date -j -f "%Y-%m-%d" "<YYYY-MM-DD>" +%s)
NOW_EPOCH_S=$(date +%s)
for chat in $(grep -v '^#' ~/.config/daily-report-telegram-chats.txt | grep -v '^$'); do
  out="/tmp/tg-export-$(echo "$chat" | tr -c 'A-Za-z0-9' '-').json"
  tdl chat export -c "$chat" -T time -i "$SINCE_EPOCH_S,$NOW_EPOCH_S" \
    --all --with-content --raw -o "$out" 2>/dev/null || { echo "export failed: $chat"; continue; }
  echo "=== $chat ==="
  python3 -c "
import json, sys, re, pathlib
from datetime import datetime
names = {}
lines = pathlib.Path('$HOME/.config/daily-report-telegram-chats.txt').read_text().splitlines()
for i, ln in enumerate(lines):
    if ln.strip().isdigit() and i > 0 and lines[i-1].startswith('#'):
        names[int(ln.strip())] = lines[i-1].lstrip('# ').strip()
pat = re.compile(r'^[#*\s📋]*(daily\s*(report|update)|update\b|eod|logging off|catch[- ]?up|weekly)', re.I)
data = json.load(open(sys.argv[1]))
for m in data.get('messages', []):
    txt = m.get('text') or ''
    if not isinstance(txt, str) or not txt.strip():
        continue
    uid = ((m.get('raw') or {}).get('FromID') or {}).get('UserID')
    sender = names.get(uid, uid or '?')
    when = datetime.fromtimestamp(m['date']).strftime('%Y-%m-%d %H:%M')
    first = txt.strip().splitlines()[0]
    tag = 'REPORT' if (pat.match(first.strip()) and len(txt) >= 200) \
        else ('LONG' if len(txt) >= 1200 else None)
    if tag:
        print(f'--- {tag} [{when}] {sender} ---')
        print(txt[:2500])
    else:
        print(f'[{when}] {sender}: {txt[:200]}')
" "$out"
done
```

If the parsed output looks wrong, inspect the export schema first
(`head -c 2000 "$out"`) and adapt the field names.

A multi-week range produces a lot of messages — don't read it all
linearly. Read every `REPORT` and `LONG` block first, then selectively
read the short-message discussion around days those blocks flag as
eventful. If a teammate seems to have posted nothing for a stretch, skim
that period's short messages before concluding they went quiet — formats
drift, and a new one belongs in the pattern above (update this file when
you find one).

Notes:

- Daily reports and channel chatter cover ALL repos, not just this bot's —
  use only the parts about this bot's repo/domain (Step 5 relevance rules
  apply here too).
- Don't quote messages verbatim, but DO use them for attribution: the
  sender on each report tells you who did what, which feeds the
  who-did-what credit in the report (see Step 6). This is the opposite of
  the daily-report skill's no-attribution rule — that report is a
  first-person chat message, this one credits the team.
- Missing days are normal (no report was sent), not an error.
- Especially mine the reports for: incidents and their durations, manual
  prod interventions, "merged but not deployed" gaps, and decisions that
  redirected the work. These feed the executive summary's honest framing —
  a daily report saying "prod was patched manually, fix still in PR" is
  exactly the kind of truth the investor summary must not paper over.
- The user's own reports are also saved locally at
  `~/Github/dotagents/data/daily-report/reports/` (`<date>.html`
  + `<date>.json` sidecar with compact status/themes) — handy as a quick
  pre-scan of which days were eventful before diving into the export.

If `tdl` is unavailable (not installed, not logged in) or the export
fails, fall back to those locally saved reports only, and note in the
report that team-wide dev-channel context was unavailable.

## Step 3d — Query the PnL endpoint (hedge-bot only)

For **hedge-bot**, get profitability numbers first-hand instead of only
quoting daily reports: invoke the `pnl-review` skill (Skill tool) with the
report period as an explicit range, e.g. `2026-06-02 to 2026-07-17`. That
skill owns the endpoint mechanics (ET dates, snapshot pinning, cost-tier
rules); follow it, don't re-implement curl calls here.

Respect its **3-call budget**. Get everything from as few calls as
possible — one unfiltered full-period call already returns per-symbol and
per-day decomposition. Questions to answer for the report:

1. **Full-period net PnL and the gross→net bridge**, onchain volume, and
   the bps margin (net / onchain notional). This becomes the KPI row and
   replaces any daily-report-quoted PnL figure as the primary source.
2. **Which days were negative** (daily windows are GROSS — label them so;
   "every day positive" claims must say gross or net correctly).
3. **What drove the profit**: hedged spread capture vs market-move luck vs
   onchain netting, plus top winner / worst loser symbol and which bucket
   drove each.
4. **Cost coverage**: which costs are `not_ingested` — this is the exact
   wording basis for the "net is an upper bound" caveat. If gas or other
   costs are untracked, the report must say so.
5. If extended hours is a period theme and budget allows, the pre+post
   session split (2 extra calls — that exhausts the budget).

Notes:

- The endpoint has **no capital base** — it cannot give APY. The KPI
  section's run-rate/APY handling still applies.
- The data may not cover the whole report period (`availableRange`); if
  clipped, state the actual PnL window in the report, never imply
  full-period coverage.
- **Cross-check against daily-report PnL claims** (feeds Step 6b): when
  the endpoint and a daily report disagree, prefer the endpoint (it's
  live data) and note the discrepancy instead of silently picking one.
- If the endpoint is unreachable (not on the tailnet, host down), fall
  back to the daily-report-quoted numbers and mark them "as reported on
  <date>, not independently verified".

## Step 4 — Fetch Linear issues

**Important**: Use `linear issue query`, not `linear issue list`. The `list`
subcommand does not support `--json` output or date-based sorting. Only
`query` supports `--json`, `--updated-after`, and `--no-pager`.

Fetch all issues from the team updated in the date range:

```bash
linear issue query --team <team> --updated-after <date> --json --limit 0 --no-pager
```

This returns structured JSON with all issue metadata (title, state,
project, milestone, assignee, labels, updatedAt, etc.).

Then, for each candidate issue, if you need the full description (not
included in query output), fetch it:

```bash
linear issue view <ID> --json
```

Read the description and metadata of each issue.

## Step 4b — Fetch Linear milestones

For each Linear project that has issues relevant to this bot (determine the set
per Step 5, from the data — never from a hardcoded list of names), fetch the
milestone structure to understand the planned roadmap and current phase:

```bash
# `linear project list` does NOT support --json, so get project IDs by reusing
# the Step 4 issues JSON — extract unique id/name pairs:
linear issue query --team <team> --updated-after <date> --json --limit 0 --no-pager \
  | jq -r '[.nodes[] | select(.project) | {id: .project.id, name: .project.name}]
      | unique_by(.id)[] | "\(.id)\t\(.name)"'

# `linear milestone list` takes a project ID (NOT a name) and does NOT support
# --json or --no-pager — read the plain table output:
linear milestone list --project <projectId>
```

Note which milestones are completed, which is active, and what's coming
next. This is essential for placing the period's work in context and for
writing an accurate "coming next" section.

## Step 5 — Filter issues by relevance

Relevance is judged by the **work itself**, never by a fixed list of project
names. New Linear projects spin up regularly for both bots, so an unfamiliar or
recently-created project is **not** grounds to exclude an issue. Do not use
project membership — or a project's absence from any known list — as a filter.

Decide with, in priority order:

1. **Does the work touch this bot's repo?** Strongest signal: the issue is
   linked to, or its work landed in, a PR/commit in this bot's repo
   (`st0x.liquidity` for hedge-bot, `st0x.issuance` for issuance-bot). If so,
   include it — whatever project it's filed under.
2. **Domain context** from the config:
   - **hedge-bot**: liquidity bot — hedging, rebalancing, vaults, Raindex,
     Alpaca, order strategies, staging/prod deployment
   - **issuance-bot**: Alpaca ITN issuer — minting, redemption, account
     linking, asset/token management, dividends and corporate actions, new
     token launches, the Rain SFT (`OffchainAssetReceiptVault`) contracts
3. **Issue description** — does it mention components, features, or bugs in
   this bot's domain?
4. **Common sense** — "website redesign" belongs to neither bot; "fix hedging
   gap calculation" is hedge-bot; "redemption journaling error" is issuance-bot.

When you hit a project you don't recognize, don't skip it — open its issues,
read the descriptions and any linked PRs, and include anything that serves this
bot's repo or domain. When genuinely unsure, lean toward including it and say so
in the report, rather than silently dropping possibly-relevant work.

**Both bots share the RAI team and some code** (notably the event-sourcing /
CQRS core, `event-sorcery`). Watch for two things:
- The *other* bot's work, plus other products (e.g. Bebop pricing,
  frontend/webapp, marketing/analytics), will show up in the query results —
  exclude those and note why, per the Excluded Issues section. Base that call on
  what the work is, not on the project's name.
- Genuinely cross-cutting work (e.g. an `event-sorcery` change, shared
  tooling) can be **included** for whichever bot the report is about when it
  landed in or directly serves that bot's repo — say so explicitly.

Classify each issue as:
- **INCLUDED** — relevant to the project
- **EXCLUDED** — not relevant (note the reason)

## Step 6 — Compile the report

### Write the whole report in ASD-STE100

The report is written in **ASD-STE100 (Simplified Technical English)** —
controlled language, not personal voice. Do NOT load the `write-as-me`
skill for this report; controlled language and personal voice are mutually
exclusive by design. STE rules to apply throughout:

- Sentences ≤ 25 words, one idea each; paragraphs ≤ 6 sentences.
- Active voice with named agents ("Rouz built X. Gleb did the reviews.").
- One meaning per word. In particular, collapse status vocabulary to
  exactly two states used consistently: **merged** and **deployed**
  (never "landed", "shipped", "live" as synonyms).
- No idiom or metaphor ("hard to kill" → "resistant to failures").
- "approximately", never "~" or "about".
- Warnings as explicit callouts: "Caution: the profit values do not
  include gas costs."
- Domain terms (PnL, hedge, spread, basis points) survive as technical
  names, which STE permits.
- Label the report as STE-style, not certified STE (full compliance
  needs the official dictionary).

STE does not weaken the honesty rule — it strengthens it: state what is
fragile or unfinished in plain short sentences, and frame progress
against real completion, never aspiration.

Structure the report as markdown, ready to copy-paste.

### Report structure (the single deliverable)

The title of the report is exactly:
`# St0x liquidity and issuance bots progress report` (combined mode).
For a single-bot run, use `# St0x liquidity bot progress report` or
`# St0x issuance bot progress report`. Below the title, the Period line,
then exactly this note line:
`**Note**: This report uses Simplified Technical English (ASD-STE100
style): short sentences, active voice, one meaning for each word.`

This document IS the deliverable — the only saved output of this command.
It gets sent as-is to higher-ups (leadership, investors) to communicate
progress, justify timelines, and build confidence. Write it as a
standalone narrative: someone should be able to read only this document
and fully understand what happened, what's at risk, and what's needed
from them. There is no saved appendix; supporting detail (issue lists,
incident logs, excluded issues) is shown in the conversation during the
run, not in the file.

**Tone**: ASD-STE100 (see the STE rules above): short, active, specific,
no fluff. Use domain terms investors would know (hedging, rebalancing,
deployment infrastructure) but explain system internals in plain English.
Avoid jargon like "projection views", "optimistic lock conflicts", or
"apalis jobs" — translate these into what they mean for the product.

"Confident" means *concrete and honest*, never inflated. Lead with the real
status including what is fragile or unfinished, and frame progress against
actual completion (shipped vs planned, real Linear ratios), not aspiration.
Do not claim a thing is done, stable, or deployed when it is merged, patched,
or in review — say which. An investor who later discovers the gap trusts
nothing else in the report.

**Before writing the summary**, fetch Linear project milestones to
understand the planned roadmap:

```bash
# Project ID (not name); no --json support — parse the table (see Step 4b):
linear milestone list --project <projectId>
```

Run this for each project that has INCLUDED issues (from Step 5). The examples
below are illustrative only, not an allowlist:
- **hedge-bot**: e.g. "Live MVP of st0x.liquidity bot", "Robust liquidity
  management with auto-recovery", "ST0x observability, hardening, and testing".
- **issuance-bot**: e.g. "Issuance Bot Improvements", "Dividends", "New Token
  Launches", "Corporate-action-aware oracle".

Derive the real set of projects from the data each run — a project you've never
seen before is still in scope if its work serves the bot. Never assume the lists
above are exhaustive or current. Milestones define the intended sequencing — use
them to understand what phase the team is in and what the next milestone is.

Also look at all **Todo** and **Backlog** issues (not just In Progress /
In Review) to identify the forward workplan. From these, determine:
- What's on the **critical path** to the next milestone?
- What's running in **parallel** and not blocking anything?
- What's **background / whenever** with no immediate deadline?

Be precise about sequencing — don't imply something is a prerequisite
if it isn't. If two workstreams are parallel and independent, say so
explicitly.

**Structure the summary as**:
1. **TL;DR** — 3-5 lines at the very top: overall status in one sentence,
   the single biggest win of the period, and the single biggest open
   risk. A higher-up who reads nothing else should still walk away
   correctly informed.
2. **Opening paragraph** — what the team focused on this period and why.
   Frame the work in terms of product goals (e.g., "production readiness",
   "risk reduction", "operational reliability") not just tickets closed.
3. **Key accomplishments** — 3-5 bullet points, each 1-2 sentences.
   Lead with the business impact, then briefly mention what was done
   technically. E.g., "Eliminated a class of stuck-transfer failures that
   could block rebalancing indefinitely — added timeout-based recovery so
   the system self-heals without manual intervention."
4. **KPIs** — a small scannable table of the period's numbers, drawn from
   the PnL data, daily reports, and incident log where available. Typical
   rows: PnL / volume (when known), incidents and total degraded hours,
   funds lost (state "$0" explicitly when true — it's the number they
   most want), assets live in prod, PRs landed, issues closed. Only rows
   the data actually supports — never fabricate a metric, and mark
   estimates as such.

   **Profit is always framed as a rate, never just raw dollars.** A
   higher-up can't judge "+$520" without a denominator. Whenever profit
   appears (KPI table or prose), give alongside it:
   - **bps on volume**: net PnL / traded volume — the margin per dollar
     traded.
   - **Annualized return on capital (APY)**: net PnL annualized over the
     period, divided by the capital deployed. Capital comes from the
     data (dashboard/inventory, daily reports) or the user — if it isn't
     known, say "proper APY needs the capital base" and give the
     annualized dollar run-rate instead, clearly labeled as an
     extrapolation of a short sample.
   Don't conflate the two: bps-on-volume is a margin, APY is a return on
   capital. Show the arithmetic inputs so the number is checkable.
5. **What's in progress / coming next** — Derive a clear workplan from
   the milestone structure, Todo/Backlog issues, and open PRs. Distinguish
   explicitly between: (a) what's on the critical path to the next
   milestone, (b) what's running in parallel and not blocking, and (c)
   what's deferred / background. Don't guess at sequencing — use the
   milestone and issue data to reason about it. Frame delays honestly but
   constructively.
6. **Risks** — the top 2-4 open risks stated plainly: what could go
   wrong, what's being done about it, what recurs until a fix deploys.
   A progress report informs; it never asks. If something is needed from
   a specific person (a decision, coordination, resources), that is a
   direct message to that person, not a line in this document. Open
   decisions may appear as risk statements ("X is undecided; until then
   Y"), never as requests. Domain note: **RKLB is the designated
   test/pilot asset** (extended-hours pilot, shared-inventory pilot) —
   frame RKLB findings as test results that inform a decision, never as
   material risks or losses by themselves.
7. **By the next report** — 2-4 concrete expectations for the next
   period, honestly hedged ("should", "aiming for", not "will" unless
   certain). Also close the loop here on the PREVIOUS report's
   expectations (from Step 2b): each one gets happened / slipped /
   dropped with a one-line why.
8. **Team output stats** — one line with commit count, contributors, and
   issues completed. Demonstrates velocity without belaboring it.

**Do**:
- Quantify where possible (N issues completed, N bugs fixed, N contributors)
- Use the daily reports (Step 3c) for incident timelines, durations, and
  merged-vs-deployed truth — they beat inferring these from git alone
- **Attribute who did what**, by name, throughout — in the summary's
  headlines and in the detailed themes. Sources: PR authors, commit
  authors, and the daily-report senders. The report goes out under
  Juan's name, so his own work is first person ("I built...") and
  he is "Juan" (never "Juani") when named in third person, and
  teammates are named ("Gleb built...", "Josh landed..."). A report that
  credits the team reads more credible, not less.
- Explain *why* work matters, not just *what* was done
- Be honest about challenges — investors respect transparency
- Group related work into themes rather than listing individual tickets
- If there were delays or scope changes, explain the root cause and how
  the team adapted

**Don't**:
- Use passive voice ("issues were resolved") — use active voice
  ("the team resolved", "we shipped")
- Minimize the work — if a bug fix took a week because it was genuinely
  hard, say why it was hard
- Include issue IDs or Git SHAs in the summary — those go in the
  detailed sections below
- Pad with filler — every sentence should carry information

### Final section: completed work in detail (optional reading)

The report ends with one appendix section inside the same file:
`## Appendix: completed work in detail (optional reading)`. Open it with
one STE line: "This section is optional. It lists the completed work of
the period." Then, per bot:

- **Work items completed** in the window, grouped by project/theme —
  one line per item, **issue first** (the issue is the main work item),
  with its associated PR(s) on the same line:
  `[RAI-<id>](https://linear.app/makeitrain/issue/RAI-<id>) — <short
  title> ([#<n>](https://app.graphite.dev/github/pr/<org>/<repo>/<n>))`.
  Associate a PR to an issue when the PR title or body references the
  issue ID (fetch PR bodies to build the mapping). An issue with no PR
  gets no parenthesis; an issue with several PRs lists them all.
- **PRs without a linked issue**: one line each,
  `[#<n>](<graphite-url>) — <title> (<author>)`, per repo. These still
  count as real work (see docs/linear-workflow.md).
- **Activity by person** — a table at the very end, one row per
  contributor: **issues closed** (Linear state Done, by assignee — never
  open/in-progress states, and Canceled/Duplicate do not count; the
  column label is "Issues closed"), PRs landed (by author, both repos),
  commits, and lines added/removed (both repos' default branches,
  in-window). **Scope: bot work only — defined by the repos and their
  surrounding logic, never by Linear project names.** Projects are
  transient (several exist per bot at any time, depending on the goal),
  so apply the Step 5 relevance judgment: an issue counts when its work
  serves one of the two repos or their surrounding logic, whatever
  project it sits in. A project that mixes bot and non-bot work (e.g. a
  token-launch ops project with oracle/website/setup tasks) must NOT be
  included wholesale. When describing the scope in the report, say
  "issues about the two bot repositories and their surrounding logic" —
  never enumerate Linear projects as the definition. The same scope
  applies to the appendix issue lists (grouping BY project for display
  is fine; scoping by project is not). Map handles
  to real names via the team map (memory: team-handle-names; Linear
  assignees like `juan1` = Juan). Unassigned Done issues get their own
  row. These are activity indicators, not performance scores — say so
  in one line under the table.

**Hyperlinks everywhere**: every issue and PR reference in the report —
body and appendix — is a link. Issues link to Linear
(`https://linear.app/makeitrain/issue/<ID>`); PRs link to Graphite
(`https://app.graphite.dev/github/pr/<org>/<repo>/<number>`, org is
`ST0x-Technology` for both bot repos).

**Counting rule (Graphite merge queue)**: a PR counts as landed when it
is GitHub-merged OR closed with the `externally-merged` label. The merge
queue closes PRs instead of merging them; the label (applied by the
externally-merged workflow and its push-to-master backstop) marks the
real merges. A closed PR without the label counts only if its commit is
on master. Never list a closed, unmerged, unlabeled PR as landed.

Lists are data: STE prose rules apply to the sentences, but the lists
themselves stay mechanical.

### Other supporting detail: conversation only, never saved

Apart from the optional completed-work appendix above, the report file
contains ONLY the STE document. Do not save any other appendix. During
the run, show in the conversation (for the user's review, not for
forwarding):

- The excluded-issues breakdown (hard rule 3) — grouped by project with
  counts and reasons, plus any borderline inclusion calls.
- Any material discrepancy the verification pass (Step 6b) found, and
  what changed because of it.
- The per-bot incident list if the user asks for drill-down.

## Step 6b — Verify every claim (mandatory, before saving)

This report goes to higher-ups who WILL poke at the numbers. A claim that
dies under one follow-up question poisons trust in the whole report. So
before saving anything: extract every checkable claim from the drafted
summary — every count, amount, date, duration, and status word ("merged",
"deployed", "in review", "live", "fixed") — and verify each one against a
**second, independent source**. One query feeding prose directly is how
the wrong-PR-count mistake happened.

Per claim type:

- **"In review" / "open"**: re-fetch PR state live at write time (never
  reuse a count fetched earlier in the session), AND confirm the changes
  are absent from master (`git log origin/master --grep` on a few
  titles). Bucket before citing (active / paused / stale — see Step 3b);
  name the stack structure if you cite a stack.
- **"Merged"**: the commit is on `origin/master`, or the PR is closed
  with the `externally-merged` label. A PR someone said was merged in
  chat does not count without one of those two.
- **"Deployed" / "live"**: a successful deploy run post-dating the merge,
  or a daily report explicitly stating the deploy happened. Merged is not
  deployed. **And check what the deploy run actually deployed**: a deploy
  workflow can ship only part of the tree (e.g. the NixOS system/infra
  profile without the new service build), so a successful run at commit X
  does NOT prove every change merged at X is live. Read the workflow/run
  to see which component it deploys, and corroborate with a second
  signal: a daily report naming the deploy's scope, or runtime evidence
  (version/health endpoint, observed behavior). If the scope cannot be
  confirmed, write "merged; deployment not confirmed" — never "deployed".
- **Counts** (PRs, issues, commits, contributors): recompute with a fresh
  query while writing, and sanity-check against a second angle (e.g.
  merged-PR count vs master commit count; issue count vs the state
  breakdown summing to it).
- **Money, PnL, durations, dates**: traceable verbatim to a specific
  source (a daily report, the PnL endpoint, a git/deploy timestamp).
  Never derive a new financial number by arithmetic the source didn't
  do — with one exception: the rate framings the summary requires (bps
  on volume, annualized return) MAY be computed from verified inputs,
  provided the inputs and formula are stated so the number is checkable,
  and annualized figures are labeled as extrapolations.
- **Attribution**: the named person matches the PR/commit author or the
  daily-report sender, not an assumption.

For each claim the check fails or can't be run: fix the claim, soften it
("about", "as of <date>", "reported as"), or cut it. Never ship a claim
you couldn't verify twice. If a verification materially changes a number
already discussed with the user, say so explicitly rather than silently
correcting.

## Step 7 — Output and save

1. **Print the full report** as text output so the user can read and
   copy-paste it.

2. **Save the report** to disk — ONE file, the STE report:

   ```bash
   # The single deliverable (STE, sendable as-is):
   #   ~/Github/dotagents/data/progress-tracking/reports/<project>-<YYYY-MM-DD>.md
   ```

   The file is the STE document plus the Period header — no appendix, no
   excluded-issues, no "Generated by" footer. It must stand alone: this
   is the artifact the user forwards. Supporting detail lives in the
   conversation output only.

   Use `Write` to save all three. If files for the same project and date
   already exist, overwrite them (it's a re-run).

3. **Update the last-run timestamp** in the config:

   ```bash
   # Read, update last_run to current ISO datetime, write back
   ```

   Read `~/Github/dotagents/data/progress-tracking.json`, update the
   project's `last_run` to the current datetime (ISO 8601), and write it
   back using `Write`.

4. **Confirm**:

   ```
   Report saved: ~/Github/dotagents/data/progress-tracking/reports/<project>-<date>.md
   Last run updated to: <datetime>

   To convert to PDF:
     cd ~/Github/dotagents/data/progress-tracking/reports && \
     TYPST_FONT_PATHS="/System/Library/Fonts:/System/Library/Fonts/Supplemental:/Library/Fonts:$HOME/Library/Fonts" \
     nix shell nixpkgs#pandoc nixpkgs#typst -c pandoc -f gfm <project>-<date>.md \
       -o <project>-<date>.pdf --pdf-engine=typst -V mainfont="Helvetica Neue" \
       -V papersize=a4 -V margin-x=2cm -V margin-y=2.2cm
   ```

   Print the PDF command with the real filename substituted — it is
   informational; do not run it unless asked. (`-f gfm` avoids pandoc's
   citation parsing on @-words; TYPST_FONT_PATHS lets nix-typst see the
   macOS fonts.)

## Hard rules

1. **Never modify the repo or Linear issues** — this is read-only.
2. **The report is written in ASD-STE100** (see the STE rules in Step 6).
   Do NOT load the `write-as-me` skill for it. Never oversell — frame
   progress against real completion ratios and name what is unfinished.
3. **Always show excluded issues in the conversation output** — the
   user needs to verify filtering. They are never part of the saved
   report.
4. **Always save the STE report to disk** (the single output file)
   before finishing.
5. **Always update last_run** after a successful run.
5b. **Always close the loop on the previous report's "By the next
   report" expectations** (Step 2b) — happened, slipped, or dropped,
   each with a one-line why. Never silently drop a prior commitment.
5c. **Every checkable claim must survive the Step 6b verification pass**
   (second independent source, fresh queries at write time) before the
   report is saved. A number that can't be verified twice gets softened
   or cut, never shipped as-is.
6. **Use `--json` for Linear queries** — parse structured data, don't
   scrape human-readable output.
7. **Expand `~` in repo paths** before passing to git commands.
8. If Linear or git commands fail, report what you could gather and note
   what was unavailable — don't fail silently.

## Failure modes

- **Linear auth expired**: tell the user to run `linear auth login`.
- **Repo path doesn't exist**: tell the user and suggest updating the
  config file at `~/Github/dotagents/data/progress-tracking.json`.
- **No issues found**: report git activity only, note no Linear activity.
- **No commits found**: report Linear activity only, note no git activity.
- **`/pnl` endpoint unreachable** (hedge-bot): fall back to
  daily-report-quoted PnL figures, marked "as reported on <date>, not
  independently verified"; note the endpoint was unavailable.
- **`tdl` not installed / not logged in / export fails**: fall back to the
  locally saved daily reports
  (`~/Github/dotagents/data/daily-report/reports/`); note that
  team-wide dev-channel context was unavailable. If those are empty too,
  note "daily-report context unavailable for this period" so the user
  knows the narrative leans on git/Linear/PRs alone.
- **First run (last_run is null)**: default to 14 days, tell the user.
