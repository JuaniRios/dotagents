---
name: engineer-report
description: Generate an evidence-backed manager report for one engineer over a specified time period. Use when the user asks what an engineer worked on, how they are performing, what they delivered, what is blocked or paused, where they need support, or wants an individual performance or progress report with links.
argument-hint: "<engineer> [since <timeframe>|from <date> to <date>] [brief|full]"
---

# Engineer report

Generate a manager-facing report for one engineer.

The report combines Telegram work chats, the private Telegram conversation
with the engineer, Linear, GitHub, Git history, deployment evidence, incident
activity, and prior reports. It explains:

- What the engineer worked on
- What they completed
- What reached production
- What remains active, paused, blocked, or stale
- How they contributed through reviews and operational work
- Whether they followed through on commitments
- Where they performed well
- Where they need support or closer follow-up

This is an evidence report, not an employee score.

## Arguments

Supported examples:

- `/engineer-report Jakub`
- `/engineer-report Kais since last week`
- `/engineer-report Alex since 2026-08-21`
- `/engineer-report Rouzbeh from 2026-08-01 to 2026-08-31`
- `/engineer-report Gleb last 30 days brief`

Parse:

1. Engineer name or known handle
2. Start and end time
3. Output mode: `full` by default, or `brief`

If no time range is supplied, use the last 7 days.

Use the local timezone for date boundaries. Convert the boundaries to UTC
once for GitHub and Linear timestamp comparisons.

If the identity is ambiguous, show the possible matches and ask the user.
Do not merge two people because they have similar names.

## Step 1: Resolve the engineer's identity

Build an identity record with:

```json
{
  "name": "Jakub",
  "github": ["ueco-jb"],
  "linear": ["Jakub"],
  "telegram_user_ids": [5143544692],
  "telegram_usernames": ["jakubdev"],
  "git_names": ["Jakub"],
  "git_emails": []
}
```

Look for an existing mapping in:

`~/Github/dotagents/data/engineer-report/team.json`

If it does not exist:

1. Use `tdl chat ls` to match Telegram names, usernames, and private-chat IDs.
2. Use GitHub PR authors and Git commit identities.
3. Use Linear assignee names.
4. Ask the user only when a match remains ambiguous.
5. Save confirmed mappings for future reports.

Never print email addresses, API credentials, Telegram authentication data,
or other private account data in the report.

## Step 2: Pre-flight checks

Check all required sources before collection:

```bash
gh auth status
linear auth whoami
tdl chat ls
test -f ~/.config/daily-report-telegram-chats.txt
```

A missing source is a data limitation. It is not evidence of no activity.

If `jq` or `python3` is missing on NixOS, use a temporary shell:

```bash
nix shell nixpkgs#jq nixpkgs#python3 --command <command>
```

Do not modify the system configuration.

Use the work chats configured in:

`~/.config/daily-report-telegram-chats.txt`

Also inspect the private Telegram conversation with the selected engineer by
default. Do not inspect private conversations with anyone else.

## Step 3: Load continuity data

Reports are saved under:

`~/Github/dotagents/data/engineer-report/reports/`

Read the most recent report for the same engineer.

Extract:

- Prior active work
- Prior blockers
- Commitments and expected next steps
- Manager actions
- Items that were waiting for review or deployment

For each prior item, determine whether it:

- Completed
- Progressed
- Remained blocked
- Became stale
- Was dropped or replaced

Do not silently lose an item between reports.

## Step 4: Collect evidence in parallel

Run isolated read-only collectors for:

1. Telegram
2. Linear
3. GitHub and Git
4. Deployments and incidents

Each collector must use the same literal start and end timestamps.

Collectors return structured evidence, not a finished narrative.

### Telegram collector

Export every configured work chat and the selected engineer's private chat
with `--raw`:

```bash
tdl chat export \
  -c <chat-id> \
  -T time \
  -i "<start-epoch>,<end-epoch>" \
  --all \
  --with-content \
  --raw \
  -o <temporary-file>
```

The plain export does not identify senders. Use:

`raw.FromID.UserID`

Match that ID against the engineer's identity record.

Read:

- Daily and weekly reports
- Long incident write-ups
- Short messages around eventful periods
- Decisions
- Requests
- Review requests
- Commitments
- Blockers
- Operational interventions
- Questions that remained unanswered
- Direct feedback and support discussions in the private conversation

Detect status posts using both rules:

1. The first line contains `daily report`, `daily update`, `update`, `eod`,
   `logging off`, `catch-up`, or `weekly`; the message is at least 200 characters.
2. The message is at least 1,200 characters.

Do not use message count as a performance metric.

Do not quote private conversation text in the report. Paraphrase it and link
the underlying work item instead. Only quote it if the user explicitly asks.

For commitments, capture:

```json
{
  "date": "...",
  "commitment": "...",
  "expected_by": "...",
  "result": "completed|progressed|missed|superseded|unknown",
  "evidence": ["..."]
}
```

Only count explicit commitments. Do not turn casual ideas into promises.

### Linear collector

Use the whole-team query and filter by the resolved assignee:

```bash
linear issue query \
  --team RAI \
  --all-assignees \
  --all-states \
  --updated-after <start-utc> \
  --limit 0 \
  --json \
  --no-pager
```

Use `linear issue view <ID> --json` for important or ambiguous issues.

Use the raw API only when the CLI does not expose:

- Status transitions
- Assignment changes
- Comments
- `startedAt`
- `completedAt`

Capture:

- Issues created
- Issues started
- Issues completed
- Current active issues
- Paused issues
- Blocked issues
- Reopened issues
- Issues that changed assignee
- Issues with no recent movement

An issue counts as completed only if it transitioned to `Done` in the report
window. Do not count `Canceled` or `Duplicate` as completed delivery.

Use assignment history when available. Do not credit the current assignee for
work completed before they received the issue.

### GitHub and Git collector

Discover relevant repositories from:

- Local repositories under `~/Github`
- Linear issue links
- Telegram PR links
- The engineer's GitHub activity

Collect:

- PRs opened
- PRs merged
- Graphite PRs externally merged
- PRs reviewed
- Review outcomes
- Commits on default branches
- Reverts and hotfixes
- Open and draft PRs
- CI state
- PR age
- Merge lead time
- Linked Linear issues

Graphite can close a PR instead of marking it merged.

A PR counts as merged only when one of these is true:

1. GitHub reports it as merged.
2. It has the `externally-merged` label.
3. Its commit exists on the default branch.

Deduplicate rebased and amended commits. Report PR outcomes, not every
temporary commit.

A review counts once per teammate PR. Exclude:

- Bot reviews
- Self-reviews
- Repeated review submissions on the same PR

Classify open work:

- Active: changed recently or explicitly in progress
- Blocked: waiting for a named dependency or decision
- Paused: intentionally stopped
- Stale: no meaningful activity for 5 business days
- Draft: intentionally incomplete

Do not describe every open PR as "in review."

### Deployment and incident collector

For every merged PR, inspect deployment runs.

A change counts as deployed only when:

1. A successful deployment post-dates the merge.
2. The deployment includes that component.
3. A second source confirms the deployed version or behavior.

If this cannot be verified, write:

`Merged; deployment not confirmed.`

Capture incidents where the engineer:

- Detected the issue
- Diagnosed the cause
- Coordinated the response
- Applied a manual recovery
- Delivered the permanent fix
- Created follow-up work

Keep these roles separate.

Do not say an engineer caused an incident unless the root cause and
attribution are clear from two sources.

For each incident, capture:

- Start and recovery timestamps
- Customer or financial impact
- Funds at risk or lost
- Manual recovery
- Permanent fix status
- Follow-up issue
- Engineer's role

## Step 5: Reconcile the evidence

Connect Telegram, Linear, PR, commit, and deployment evidence into one work
item. Do not count the same work once per source.

For each item, determine:

```json
{
  "title": "...",
  "role": "owner|co-owner|reviewer|operator|advisor",
  "state": "deployed|merged|in_review|in_progress|blocked|paused|stale",
  "business_impact": "...",
  "issue": "...",
  "prs": [],
  "evidence": [],
  "confidence": "high|medium|low"
}
```

Use `deployed` and `merged` precisely.

If chat says "shipped" but the deployment failed, the deployment evidence
wins.

If two sources disagree, explain the discrepancy in the conversation and use
the more conservative claim.

## Step 6: Calculate performance metrics

Metrics describe the period. They do not define the person.

### Delivery metrics

- Issues completed
- PRs opened
- PRs merged
- PRs deployed
- Merge-to-deploy gap
- Median PR lead time
- 75th percentile PR lead time
- Active work count
- Stale work count

### Collaboration metrics

- Unique teammate PRs reviewed
- Reviews that requested changes
- Workstreams unblocked for others
- Cross-team decisions or coordination led

A high change-request count is not automatically negative. It can show careful
review.

### Ownership and follow-through metrics

- Explicit commitments completed
- Explicit commitments progressed
- Explicit commitments missed
- Blockers escalated with a clear owner
- Incidents diagnosed
- Incidents recovered
- Permanent follow-ups created
- Permanent follow-ups completed

Show the commitment denominator. For example:

`4 of 5 explicit commitments completed; 1 moved after the scope changed.`

Do not calculate a follow-through percentage from inferred commitments.

### Quality and reliability indicators

Report only evidence-backed indicators:

- Reverts
- Emergency hotfixes
- Production regressions linked to the engineer's change
- Repeat incidents after a claimed fix
- CI failures that remained unresolved
- Review findings that caused substantial rework
- Preventive reliability work
- Tests, health checks, or monitoring added

Give system context. A hotfix can indicate strong incident ownership even when
the original change had a defect.

### Metrics that must not become performance scores

Do not rank or score engineers using:

- Commit count
- Lines changed
- Message count
- Raw issue count
- Raw PR count
- Hours online
- Number of comments

These values can appear as workload context only.

Do not compare two engineers unless the user explicitly asks. Different roles
produce different evidence.

## Step 7: Produce the manager assessment

Assess four dimensions:

1. Delivery
2. Quality and reliability
3. Ownership and follow-through
4. Collaboration and leverage

For each dimension provide:

- Assessment: `strong`, `on track`, `needs attention`, or `insufficient evidence`
- Two or three concrete facts
- Confidence: `high`, `medium`, or `low`

Do not produce one overall numeric score.

Use `needs attention` only when evidence shows a repeated or material problem,
such as:

- Repeated missed commitments
- Stale work without escalation
- Regressions without follow-up
- Persistent review or CI failures
- A blocker left uncommunicated

A single difficult incident is not poor performance.

Distinguish:

- Engineer-controlled outcomes
- Team dependencies
- External dependencies
- Deployment or approval delays outside the engineer's control

## Step 8: Write the report

Use Simplified Technical English style:

- Short sentences
- Active voice
- One idea per sentence
- Concrete numbers
- No corporate filler
- No unsupported praise or criticism
- No em dashes

Every issue and PR reference must be clickable.

Use Linear links:

`https://linear.app/makeitrain/issue/<ID>`

Use Graphite links:

`https://app.graphite.dev/github/pr/<org>/<repo>/<number>`

### Full report structure

```markdown
# Engineer report: <name>

**Period:** <start> to <end>
**Evidence confidence:** <high|medium|low>

## Manager summary

<Three to five sentences. State the main outcome, current focus, biggest
strength, and biggest concern.>

## What <name> worked on

### <Outcome or workstream>

- Role:
- Result:
- Why it matters:
- State:
- Evidence:

## Current work

| Work item | Role | State | Last movement | Evidence |
|---|---|---|---|---|

## Blocked, paused, or stale

| Work item | Status | Blocker | Age | Next action | Owner needed |
|---|---|---|---:|---|---|

Write `None found` when the evidence supports that conclusion.

## Performance readout

| Dimension | Assessment | Evidence | Confidence |
|---|---|---|---|
| Delivery | | | |
| Quality and reliability | | | |
| Ownership and follow-through | | | |
| Collaboration and leverage | | | |

## Metrics

| Metric | Value | Context |
|---|---:|---|
| Issues completed | | |
| PRs opened | | |
| PRs merged | | |
| PRs deployed | | |
| Median PR lead time | | |
| Unique teammate PRs reviewed | | |
| Explicit commitments completed | | |
| Active work | | |
| Stale work | | |
| Incidents handled | | |

Only include rows supported by reliable data.

## What went well

- <Evidence-backed strength>

## Needs attention or support

- <Actionable management observation>

## Manager actions

- <Decision, review, access, staffing, or escalation needed from the lead>

## Follow-through from the previous report

- <Previous item>: completed, progressed, slipped, or dropped. <Reason.>

## Expected by the next report

- <Concrete and realistic expectation>

## Evidence limitations

- <Missing source, ambiguous attribution, or incomplete deployment data>
```

### Brief report structure

The brief report contains:

- Manager summary
- Three main outcomes
- Current blockers
- Performance readout
- Manager actions
- Five to eight metrics

Keep it below 30 lines.

## Step 9: Verify every claim

Before saving, verify each checkable claim against a second source.

This includes:

- Counts
- Dates
- Durations
- Monetary amounts
- Issue states
- PR states
- Deployment states
- Attribution
- Commitments
- Incident causes

Re-fetch live PR and issue state at write time.

If a claim cannot be verified twice:

- Soften it
- Mark it as reported
- Lower its confidence
- Remove it

Never silently convert an inference into a fact.

## Step 10: Show and save

Show the full report in the conversation.

Save:

`~/Github/dotagents/data/engineer-report/reports/<engineer>-<start>-<end>.md`

Also save a JSON sidecar:

```json
{
  "engineer": "...",
  "period": {"start": "...", "end": "..."},
  "metrics": {},
  "active_work": [],
  "blocked_work": [],
  "commitments": [],
  "manager_actions": [],
  "confidence": "..."
}
```

The sidecar provides continuity for the next report.

Do not send the report to Telegram, email, or another service unless the user
explicitly asks.

## Hard rules

1. Use only work-related data sources.
2. Inspect the selected engineer's private Telegram conversation by default.
3. Never inspect private conversations with anyone else.
4. Never expose private message text, credentials, or personal data.
5. Attribute work only when the evidence supports it.
6. Separate authored work, reviews, operations, and advice.
7. Distinguish merged work from deployed work.
8. Treat missing data as a limitation, not inactivity.
9. Do not rank engineers unless the user explicitly requests comparison.
10. Do not calculate one overall performance score.
11. Do not use commits, lines, messages, or issue volume as performance proxies.
12. State external and team dependencies separately from engineer-controlled outcomes.
13. Verify material claims with two independent sources.
14. Always include links for issues and PRs.
15. Always show blockers, paused work, stale work, and manager actions.
16. Save the report and continuity sidecar after a successful run.
