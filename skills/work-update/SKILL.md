---
name: work-update
allowed-tools: Bash(*), Read, Grep, Glob, Write
description: Draft the user's detailed team work update for Wednesdays and Fridays, covering work since the previous update. Use for mid-week progress updates, end of week progress updates, work updates, twice-weekly reports, or the former daily-report request. Collect sessions, git, GitHub, Linear, Telegram, and Zulip; explain direction, outcomes, discussions, next focus, and blockers, with PRs grouped by status at the end. The user guides and edits the draft before it is sent.
argument-hint: "[since <date or timeframe>]"
---

# Work update

Replace daily updates with a written standup every Wednesday and Friday.
Cover the work since the last update across all repos in `~/Github/`.
The main message explains the work, its direction, and its context. PRs
support the story and belong at the end. This is not a changelog.

The cadence starts the week of September 9, 2026, as a trial for a couple
of weeks. Adjust when the user gives feedback; do not automatically revert
at the end of the trial. Running this skill does not schedule or send
anything automatically. An explicit request on another day is valid.

## 1. Establish the reporting window and continuity

Use the user's local timezone. Resolve the period once and pass literal
start/end timestamps to all collectors; none may recompute their own window.

- `END_UTC` / `END_EPOCH_S`: the collection cutoff for this run.
- `START_UTC` / `START_EPOCH_S`: the previous finalized update's `period_end`,
  unless the user supplies a `since` override.
- `REPORT_DATE`: the local date for the update title and filename.
- Filter activity with `START < timestamp <= END`. Read older context when
  necessary, but do not count it as new work.

Read finalized updates from `~/Github/dotagents/data/work-update/reports/`.
Also inspect legacy `~/Github/dotagents/data/daily-report/reports/` when no
new-format update exists. Preserve those files; do not move or delete them.
A legacy sidecar has a date but no exact cutoff: start at that date's local
midnight, disclose the overlap, and deduplicate work against its narrative.
Never infer a precise cutoff from the filename or file modification time.

If there is no previous update, ask for the initial period while discovering
sources. Offer the previous scheduled update day as a default (Friday for a
Wednesday run, Wednesday for a Friday run); do not silently assume today's
work is the whole period. Date-only overrides mean local midnight. Resolve
relative overrides against the single run cutoff, using timezone-aware dates
that work on the current OS.

For a revision of the same update, reuse its original period start. An
unapproved draft never advances the next update's cutoff. A missed Wednesday
or Friday expands the window from the last actual update rather than dropping
the missed days.

Load the previous narrative and sidecar. Track what happened to its next
focus, blockers, open decisions, and pending PRs: completed, continued,
changed direction, or still waiting. Carry relevant unfinished items forward.

## 2. Pre-flight and discover sources

Check GitHub and Linear authentication and Telegram availability:

```bash
gh auth status
linear issue mine --sort priority --no-pager
tdl chat ls
```

Use the existing shared Telegram config
`~/.config/daily-report-telegram-chats.txt` (one work chat ID or @username per
line, `#` comments). Keep this filename for compatibility with other skills.
If it is missing, discover chats and ask which are work-related before
writing it. Never print credentials or source raw secret files into output.

Read the `zulip` skill and check Juan-Bot:

```bash
zulipctl --config ~/.zuliprc-bot me
zulipctl --config ~/.zuliprc-bot subscriptions --full
```

Choose relevant work channels using names, descriptions, and known repo/domain
context. Keep exact channel names and IDs. Stop that source on authentication,
TLS, organization mismatch, or permission errors. Report missing coverage and
continue with the available sources. Do not change identities, subscriptions,
or access permissions to generate an update.

Index conversation history across Claude, Codex, Grok, and Agy:

```bash
python3 ~/Github/dotagents/skills/work-update/sessions.py index <START_EPOCH_S>
```

The helper returns `sid|harness|project|n_prompts|path`. Group by project,
combining harnesses and folding worktrees into their parent repo. Retain the
actual harness and path; never invent a session path. A missing harness store
is normal; if all stores are absent, report that coverage gap.

## 3. Collect evidence

Collect independent sources in parallel when supported. For large session
sets, use isolated children per project group, each with the same literal
period and only its own session paths. Otherwise collect in the main thread.
Return facts with their source, timestamp, repo, PR/issue references, and
uncertainties. An unavailable source is not an empty activity list.

### Sessions and investigations

```bash
python3 ~/Github/dotagents/skills/work-update/sessions.py extract <harness> <path>
```

Never read raw session stores; they contain large amounts of tool noise. Read
the user's direction changes, adjacent assistant replies, and final outcome.
The index selects candidate sessions, not exclusively in-window events: check
the chronology before counting work, and treat uncertain timing as context.
Summarize the actual goal, outcomes, incidents, pivots, unfinished work, and
stated next focus. Do not infer the story from the opening prompt alone.

Read relevant `~/Github/traces/*/TRACE.md` entries in the period for ongoing
investigations. Use dated timeline entries; today's file modification time
alone does not describe activity across a multi-day window.

### Git, GitHub, and Linear

Read the `linear-cli` skill for Linear commands. Query the user's issues
updated in the period across all states and inspect relevant status changes
and comments. If unavailable, extract referenced issue IDs from sessions and
commit messages, marking their current status unverified.

Discover repos and GitHub orgs from `~/Github/*/` git remotes. Worktrees share
refs; scan each parent repo once. Use the configured git identity and
`gh api user` for attribution. Read commits and reflogs in the period; Graphite
amends and restacks alter commit dates, so repeated commits are not new work.

Fetch PRs opened, changed, landed, and reviewed in the period, plus pending
PRs carried over from the previous update. Search with a wider date window
when necessary, then filter event timestamps to the exact UTC window. Fetch
all pages needed for the window; the first page is not a complete inventory.
A PR merely updated in the period does not prove the user reviewed it: check
their submitted review timestamps and meaningful review comments.

Keep repo, number, title, URL, author, draft flag, current state, review/CI
status, merge timestamp, and linked issues. GitHub merged status or a closed
PR with `externally-merged` proves landing; otherwise verify the commit is on
the remote default branch before counting a closed PR as merged.

Fetch production deployment evidence for relevant changes:

- Liquidity production: `T0Trade/t0.devops`, `production-liquidity.yml`,
  including the pinned image in `terraform/production-liquidity/images.yaml`.
- Liquidity staging: `ST0x-Technology/st0x.liquidity`, `build-oci.yml`.
  A staging roll does not prove a production deployment.
- Issuance: inspect its current `deploy.yaml` and the target environment.
- Other repos: inspect their actual deployment workflow and target.

A successful deployment after a merge is insufficient by itself: verify that
it shipped the component and commit/image containing the change. Use the
production version or runtime evidence when available. Session/chat claims,
topic resolution, or a green infrastructure-only apply do not prove a code
change is live. If evidence conflicts, surface it for user review.

### Telegram conversations

Export each configured work chat over `START_EPOCH_S,END_EPOCH_S`:

```bash
tdl chat export -c "<chat>" -T time -i "<START_EPOCH_S>,<END_EPOCH_S>" \
  --all --with-content --raw -o "<unique-temp-path>.json"
```

Parse each export immediately. Preserve sender (`raw.FromID.UserID` when
present), timestamp, chat, and message ID. Inspect the schema if fields differ;
never mistake absent sender fields for anonymous statements. Read full relevant
messages and replies, not only truncated previews.

Collect decisions, asks directed at the user, incidents, commitments, and
context that explains why work happened. Include teammates' messages and
updates, not only the user's posts. A chat claim that an ask was addressed
must be checked against the work or later discussion.

### Zulip conversations

Follow the `zulip` skill, always selecting `--config ~/.zuliprc-bot`:

```bash
zulipctl --config ~/.zuliprc-bot messages --channel "<exact channel>" --limit 100
zulipctl --config ~/.zuliprc-bot messages --channel "<exact channel>" --topic "<exact topic>" --limit 100
```

Inspect both resolved and unresolved topics and include teammates' messages.
Page backward with `--anchor <oldest-message-id>` until reaching the period
start or exhausting accessible history. Deduplicate by message ID, check
response coverage, and flag partial coverage if pagination makes no progress.
Filter to the exact period; older replies may provide background only.

Read full relevant messages and thread context. Preserve channel, topic,
sender, timestamp, message ID, and a link when available for each decision,
ask, incident, commitment, or contextual finding. Inaccessible history is a
coverage gap, not evidence that no discussion occurred.

### Reconcile sources

Connect sessions, commits, issues, PRs, and conversations around actual work.
Count cross-posted updates and repeated discussions once; copied claims are
not independent evidence. Preserve attribution internally. In the update,
name collaborators when useful to explain a discussion or decision, while
keeping the user's work first person. Do not quote chat logs or claim someone
else's work as the user's. Separate proposals from agreed decisions and
reported outcomes from verified production state.

## 4. Get the user's direction and draft in their voice

Show a short evidence summary: likely focus, main outcomes, important
discussions, remaining uncertainties, and carried-over items. Ask for the
user's emphasis, corrections, intended next focus, and any missing decisions.
Continue verification while awaiting that input. Do not invent personal
intent or a team agreement from activity alone.

Read `write-as-me` before drafting. Use the six sections below in order; this
structure overrides the old daily-report status/stats/emoji template. Write
in first person, as the user would describe their work in a standup. Use
connected paragraphs or a few useful bullets, concrete language, and honest
limits. Allow enough detail to explain a multi-day period. There is no
one-screen limit or compressed daily-report mode. Use these report titles:

- Wednesday: "Mid-week progress update".
- Friday: "End of week progress update".

Add the report date to the title and the covered period underneath. For a
late or early run, use the intended Wednesday or Friday update's title;
honor an explicit title from the user. The skill command stays `/work-update`.

1. **General direction**: what the user focused on, why, and where the work is
   going. Start with the actual direction, not a count of commits or PRs.
2. **What you worked on**: main outcomes since the last update, with useful
   context, incidents, changes of direction, and unfinished parts. Group by
   workstream and explain the result rather than narrating tools or commits.
3. **Discussions and decisions**: important conversations, who was involved
   when relevant, what was agreed, why, and what the team should remember.
   Make tentative ideas visibly tentative; open decisions belong in section 5.
4. **What you're continuing next**: the expected focus before the next update,
   grounded in the user's stated plan. Close the loop on previous intentions
   when they changed or slipped. Do not turn guesses into promises.
5. **Blockers and open decisions**: what is blocked, unclear, or waiting for
   input; who or what can unblock it when known. Distinguish blockers from
   routine planned work. If none, say so briefly only after confirming it.
6. **PRs**: the final section, using the categories below in this exact order.
   Omit empty categories. No stats, appendix, or concluding recap after it.

Do not pad a section with invented activity. If no material discussions or
PRs occurred, say so briefly. Use the user's own example as a style reference
when provided; until then follow this structure and their direct guidance.
The user owns the message: AI may collect and draft, but must not present an
unreviewed draft as their finalized account.

### PR categories

Re-fetch current state before finalizing. Link each PR to Graphite using its
actual org/repo. Use a short descriptive title and only a useful status note.
For authored work, assign one category; reviews of others' work go under
Reviewed. Do not repeat the whole narrative in the PR list.

- **Deployed**: the change is actually live in production, with evidence for
  that change's deployed component/version. Merged or live on staging is not
  deployed. A rollback means it is no longer deployed.
- **Merged, not deployed**: reached the default branch but is not live in
  production. If production deployment is unverified, explicitly annotate
  "deployment not confirmed" rather than claiming it is known absent. For
  docs/tooling with no production deployment, annotate "deployment not
  applicable" here rather than inventing a production rollout.
- **Ready for review**: the user is done and waiting for others. Confirm
  readiness from the user's intent and current checks/review state; an open,
  non-draft PR alone does not establish readiness.
- **In progress**: still being implemented or revised, including active work
  to address review feedback. Draft status is a signal, not the only evidence.
- **Blocked**: cannot progress because of a concrete dependency, unresolved
  decision, failing check, or other obstacle. State the blocker; ordinary
  waiting for review belongs under Ready for review.
- **Reviewed**: other people's PRs the user meaningfully reviewed in the
  period, with useful outcome/context if needed.

For an open authored PR, a verified blocker takes priority, then readiness,
then ongoing implementation. Archived, abandoned, or closed-unmerged work is
not forced into a false status; explain a material abandonment in the main
narrative. Keep any unresolved classification uncertainty visible for review.

## 5. Review, save, and optionally send

Show the full draft and ask the user to guide/edit it closely: does it sound
like them, reflect what actually happened, and say what the team needs to
know? Incorporate corrections and re-show the exact revised text. The initial
evidence review does not approve an unseen final draft. Never claim that AI
verification replaces the user's responsibility for the message.

Save unapproved drafts under `~/Github/dotagents/data/work-update/drafts/`.
After explicit finalization or successful authorized sending, save the exact
approved text under `~/Github/dotagents/data/work-update/reports/` as
`<REPORT_DATE>.md` (or `.html` for Telegram HTML), plus a JSON sidecar:

```json
{
  "date": "<REPORT_DATE>",
  "period_start": "<ISO 8601 with timezone>",
  "period_end": "<ISO 8601 with timezone>",
  "finalized": true,
  "sent": false,
  "general_direction": "...",
  "themes": ["..."],
  "next_focus": ["..."],
  "blockers": ["..."],
  "open_decisions": ["..."],
  "open_prs": [{"repo": "org/repo", "number": 123, "status": "In progress"}],
  "coverage_gaps": []
}
```

Only finalized sidecars set the next window. Preserve the original start for
revisions; use a distinct suffix for separate updates on the same date. Keep
source references and verification notes in the sidecar as needed, outside
the team-facing prose.

Sending is optional and requires explicit authorization for the destination
and exact message. For Telegram formatting/delivery, follow the
`telegram-message` skill, including HTML escaping and splitting at natural
boundaries. Show the rendered content and destination before the final send
approval unless both were already explicitly approved. Do not infer a chat
from mentions in the format announcement. On send failure, report it and
never mark the message sent; check for delivery before retrying an ambiguous
timeout. Report the saved artifact path and actual delivery status.

## Failure handling

- Surface unavailable sources and partial time/channel coverage during review.
  Continue useful collection; never interpret auth failures as no work.
- If chat services fail, use available local finalized work updates and legacy
  daily reports for context, marking what could not be independently checked.
- Soften or remove unverified claims; production state and user intent must
  not be guessed. Do not invent accomplishments when the window is quiet.
- No repo, PR, issue, or chat mutation is authorized merely by gathering an
  update. Any follow-up action needs its own user authorization.
