---
name: work-update
allowed-tools: Bash(*), Read, Grep, Glob, Write
description: Draft the user's short team work update for Wednesdays and Fridays, covering work since the previous update. Run only from nix-darwin and collect local sessions plus NixOS sessions over SSH, along with git, GitHub, Linear, Telegram, and Zulip. Reconstruct Zulip workstreams from every in-window message rather than sampling topics. Use the team's short template (Projects, Since last, Outside projects, Surprises, Decisions, Need, Capacity, Next), readable in about 30 seconds, with no PR lists and project details left to Linear project updates. Deliver to Juan through Juan-Bot on Zulip as exactly one message of at most 10,000 characters. Never chunk the report. The user guides and edits the report before finalization. Use `save-today` to capture each day's evidence and leadership narrative under the private repo's data/work-update/days/ for richer multi-day reports.
argument-hint: "[save-today | since <date or timeframe>]"
---

# Work update

Replace daily updates with a written standup every Wednesday and Friday.
Cover the work since the last update across all repos in `~/Github/`.
The update is short: what happened outside projects, what was decided, and
who the user needs something from. Project details belong in Linear project
updates, and PR lists belong in GitHub. This is not a changelog.

The cadence starts the week of September 9, 2026, as a trial for a couple
of weeks. Adjust when the user gives feedback; do not automatically revert
at the end of the trial. Running this skill does not schedule future runs. Each run delivers the
report to Juan through the standing Zulip DM destination in Step 5. An explicit request on another day is valid.

## Mode routing

- **`save-today`**: capture today's work into a daily journal file. No Zulip delivery. See
  [save-today mode](#save-today--daily-work-journal) below.
- **Default** (optionally `since <date>`): draft the Wednesday/Friday team update. Follow
  steps 1–5 below.

## save-today — daily work journal

Run `/work-update save-today` at end of day (or anytime) to record what actually happened
that day before memory fades. The user is a team lead: much of their work is coordinating,
reviewing, planning, and investigating — not only authored PRs. Daily files make the
multi-day report faithful to that work.

Daily artifacts live under `~/Github/dotagents-private/data/work-update/days/`:

- `YYYY-MM-DD.evidence.json` — structured facts collected for that local day
- `YYYY-MM-DD.json` — sidecar (period, paths, coverage gaps, optional narrative snapshot)
- `YYYY-MM-DD.md` — human-readable day narrative the agent writes from evidence

Re-running `save-today` on the same date refreshes evidence and updates the narrative;
preserve user corrections unless new evidence contradicts them.

### save-today steps

1. **Same pre-flight as the report** (Darwin gate, `gh auth status`, Linear, Telegram,
   Zulip access for the personal account). Do not send anything to Zulip.

2. **Collect evidence for today** (local midnight through now, or `--date` for a past day):

```bash
python3 ~/Github/dotagents/skills/work-update/save_today.py collect
# optional: --date 2026-09-18 --outdir ~/Github/dotagents-private/data/work-update/days
```

The helper writes `YYYY-MM-DD.evidence.json` with sessions, GitHub authored/reviewed
PRs and pushes, Linear snapshot, full Zulip dump path plus every in-window message from
the user, Juan's DMs and @-mentions (`evidence.zulip.private`), Telegram export
paths, and trace hits. It reads every Zulip channel Juan's personal account can
see. Record
`coverage_gaps` from stderr; do not treat a failed source as no activity.

3. **Rebuild context from evidence**, not from PR lists alone:

   - Read `evidence.zulip.user_messages` and load full workstream transcripts from
     `evidence.zulip.dump_dir` for topics where the user coordinated, decided, or
     investigated. Apply the same workstream clustering rules as Step 3 (entity-based,
     full transcript, state machine).
   - Read relevant sessions with `sessions.py extract` for goals, pivots, and outcomes.
   - Read Telegram exports when present for ops/product context.
   - Separate **leadership work** (coordinate, review, plan, investigate, unblock,
     assign, incident command) from **implementation work** (authored PRs, commits,
     deploys, config changes).

4. **Write or update `YYYY-MM-DD.md`** using this template (first person, concrete,
   honest limits; cite workstreams and message IDs internally in the sidecar, not as
   chat dumps in the prose):

```markdown
# Work day | <YYYY-MM-DD>

Period: <local start> through <local end>.

## Summary
One short paragraph: what the day was about.

## Leadership
### Coordinating
Who/what you moved; incident command; hands-on-deck; pauses/restores; assignments.
### Reviewing
Meaningful PR/issue reviews and outcomes (not just a list — what you blocked/unblocked).
### Planning
Sequencing, runbooks, Linear cleanup, design direction, next-step framing.
### Investigating
Root-cause work, false alarms ruled out, accounting, replay/drill planning.

## Implementation
Authored/shipped/config/deploy work with outcomes and deployment honesty.

## Discussions and decisions
Agreements and open threads worth remembering.

## Carried to tomorrow
Explicit open loops.
```

5. **Update `YYYY-MM-DD.json`** sidecar: copy `period`, `evidence_path`, `narrative_path`,
   `coverage_gaps`, and a compact `themes`, `leadership`, `workstreams`, and
   `open_threads` list for fast lookup. Keep `finalized: false` unless the user explicitly
   approves the day note.

6. **Push the day to the private repo** so the NixOS machine and the
   `linear-groom` skill see it:

```bash
~/Github/dotagents-private/scripts/data-sync.sh save \
  "docs: work day <YYYY-MM-DD>" data/work-update/days
```

7. **Tell the user** what was captured, coverage gaps, and where files were written. Do not
   treat a daily file as a team-facing report.

### How reports use daily files

When drafting the Wednesday/Friday update (Step 1 onward), after resolving the reporting
window load every `days/YYYY-MM-DD.md` and sidecar whose date falls in
`(START_LOCAL_DATE, END_LOCAL_DATE]`. Use them as the **primary timeline and attribution
source** for what the user did each day — especially coordination, review, planning, and
investigation. Cross-check against raw collectors; prefer daily narrative for emphasis and
ordering when consistent with evidence. If a day in the window has no daily file, collect
that day normally and note the gap.

## 1. Establish the reporting window and continuity

Use the user's local timezone. Resolve the period once and pass literal
start/end timestamps to all collectors; none may recompute their own window.

- `END_UTC` / `END_EPOCH_S`: the collection cutoff for this run.
- `START_UTC` / `START_EPOCH_S`: the previous finalized update's `period_end`,
  unless the user supplies a `since` override.
- `REPORT_DATE`: the local date for the update title and filename.
- Filter activity with `START < timestamp <= END`. Read older context when
  necessary, but do not count it as new work.

All report data lives in the private repository
`~/Github/dotagents-private/data/`, which syncs Juan's machines through git.
Pull before reading (a failed pull is a coverage gap):

```bash
~/Github/dotagents-private/scripts/data-sync.sh pull
```

Read finalized updates from `~/Github/dotagents-private/data/work-update/reports/`.
Also inspect legacy `~/Github/dotagents-private/data/daily-report/reports/` when no
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

For a revision of the same update, reuse its original period start. Start from
the latest corrected draft and its delivery sidecar, not an older or longer
version. Preserve accumulated corrections to emphasis, attribution, next steps,
and PR coverage; change only what the new feedback requires. Record which
artifact supersedes the previous draft. An unapproved draft never advances the
next update's cutoff. A missed Wednesday
or Friday expands the window from the last actual update rather than dropping
the missed days.

Load the previous narrative and sidecar. Track what happened to its next
focus, blockers, open decisions, and pending PRs: completed, continued,
changed direction, or still waiting. Carry relevant unfinished items forward.

Load daily journals from `~/Github/dotagents-private/data/work-update/days/` for every
date in the reporting window (see [How reports use daily files](#how-reports-use-daily-files)).
Start the evidence summary from those day narratives before re-collecting raw sources.

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

Read the `zulip` skill. Read Zulip as Juan's personal account, which sees
every channel and Juan's DMs. Check both identities (the bot only delivers):

```bash
zulipctl --config ~/.zuliprc-personal me
zulipctl --config ~/.zuliprc-personal channels
zulipctl --config ~/.zuliprc-bot me
```

Collect every channel the personal account can see, subscribed or not.
Keep exact channel names and IDs. Stop that source on authentication,
TLS, organization mismatch, or permission errors. Report missing coverage and
continue with the available sources. Do not change identities, subscriptions,
or access permissions to generate an update.

This skill must run from the `juanrios-m2` nix-darwin machine so it can collect
that machine's conversations and SSH to the NixOS dev server for the second
local session store. Gate the run before collecting anything:

```bash
test "$(uname -s)" = Darwin || {
  echo "work-update must run from the nix-darwin machine" >&2
  exit 1
}
```

Do not continue from NixOS or another non-Darwin host. Ask the user to rerun
the skill from nix-darwin instead.

Index conversation history across Claude, Codex, Grok, and Agy on both
nix-darwin and the NixOS dev server:

```bash
python3 ~/Github/dotagents/skills/work-update/sessions.py index-all <START_EPOCH_S>
```

The helper indexes local stores first, then uses non-interactive SSH to
`juan-dev-server`. It sends its current collector code over stdin, so the
server does not need an up-to-date checkout. Remote paths are returned as
`ssh://juan-dev-server/<absolute-path>` and `extract` transparently reads them
over SSH. It otherwise returns `sid|harness|project|n_prompts|path`. Group by
project, combining harnesses and folding worktrees into their parent repo.
Retain the actual harness and path; never invent a session path. Deduplicate a
session present on both machines by harness and session ID. Prefer the local
nix-darwin copy when the contents are equivalent.

A missing harness store is normal. If the NixOS SSH attempt fails, record the
exact remote coverage gap and continue with the nix-darwin sessions and other
sources. Never silently treat an unreachable machine as having no activity. If
all stores are absent, report that coverage gap.

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
and comments. For the Projects line, fetch every Linear project where the user
is lead or driver and that moved in the period: name, URL, current health from
its latest project update, and target date, including whether the date moved. If unavailable, extract referenced issue IDs from sessions and
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

Follow the `zulip` skill. Read with `--config ~/.zuliprc-personal`, never the
bot. Reconstruct
each workstream from the full in-window transcript. Do not sample the first and
last N lines, filter to the user's messages, grep for outcome verbs, or infer
status from topic titles and last-message snippets.

Dump every topic in the work channels, then read:

```bash
python3 ~/Github/dotagents/skills/work-update/zulip_topics.py inventory
python3 ~/Github/dotagents/skills/work-update/zulip_topics.py dump \
  <START_EPOCH_S> <END_EPOCH_S> --outdir "<unique-temp-dir>"
```

With no `--channel`, the helper dumps every channel Juan's account can see.
Pass `--channel` to restrict. Also dump Juan's DMs, group DMs, and @-mentions:

```bash
python3 ~/Github/dotagents/skills/work-update/zulip_private.py \
  <START_EPOCH_S> <END_EPOCH_S> --outdir "<unique-temp-dir>/private"
```

Use DMs for context, decisions, and asks. The update is read by the team, so
paraphrase DM content and never quote someone else's DM. The helper pages each topic to
completion, filters `START < ts <= END`, and writes one cleaned transcript per
topic plus `_combined/<channel>.txt`. Stdout and `_manifest.tsv` record
`channel|topic|n|first_ts|last_ts|coverage|path`. Treat `stalled`,
`truncated`, `history-limited`, or `error:` as coverage gaps, not empty
discussions. Inaccessible history is a coverage gap, not evidence that no
discussion occurred.

Then reconstruct in this order:

1. Inventory every topic in those channels, resolved and unresolved.
2. Cluster topics into workstreams by the entity they are about (asset,
   incident, deploy, person, decision), including untitled topics and
   `#channel > topic` cross-links. Do not treat a topic title as its own
   workstream.
3. For each workstream, load **every** in-window message from every topic in
   that cluster: every sender, timestamp, topic, message ID, and body, sorted
   by time. Include teammates. Do not read a preview, a head/tail sample, or a
   Juan-only subset. Older out-of-window replies are background only.
4. Write the state machine from that transcript: what triggered the thread,
   what the user did, what a teammate later confirmed or reversed, and what is
   still open. A confirmation, reversal, or "done" lives in whoever said it,
   often not the user and often not the last line.
5. If the combined dump is too large for one context, split by workstream.
   Give each isolated child the **entire** transcript for its cluster, not a
   sample, and merge the state machines. Never split by taking the first and
   last slices of a transcript.

Preserve channel, topic, sender, timestamp, message ID, and a link when
available for each decision, ask, incident, commitment, or contextual finding.

### Reconcile sources

Include an incident only when evidence shows the user spent time investigating,
recovering, coordinating, or reviewing its fix. State their contribution and
the outcome. Merely seeing an alert, being in the chat, or working on the same
service does not qualify. Omit unrelated team incidents and alert inventories.
Separate the triggering change from the user's investigation and recovery.
When supported by a specific PR, deployment record, or clear incident account,
name who made the triggering change and explain what happened. Do not leave
wording that implies the responder caused the incident. Authorship of an
unrelated change, service ownership, reviewing, approving, or deploying a fix
does not establish causation. Explain the known cause and the user's response;
name who made the triggering change only when evidence supports it. Keep
untraced authorship in internal evidence notes, not repeated report disclaimers
such as "the introducing change hasn't been identified." Never invent blame
or imply the user was uninvolved without evidence. Keep material uncertainty
about impact, recovery, and deployment status visible. Keep attribution factual
and neutral, including the user's own role when they did introduce the problem.


Treat the user's notes as primary evidence for emphasis and intended next
steps. Distinguish completed work, unchecked TODOs, and ideas discussed in a
call. Do not claim a proposal was agreed or a task completed without evidence.
Supporting work delegated to the user's agent should stay secondary when the
user says another engineer owns the initiative.


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

Read `write-as-me` before drafting. Use the short template below. It
replaces the old six-section narrative (General direction, What I worked on,
Discussions, Next, Blockers, PRs) and the old daily-report template. The team
adopted it on 2026-10-09 ([announcement](https://raingroup.zulipchat.com/#narrow/channel/632881-engineering/topic/Progress.20Updates)).

The split the team agreed on:

- **Linear project update** (Wed and Fri, per project): health, target date,
  milestones, project PRs, and project decisions. This skill does not write
  those.
- **Zulip progress update** (this skill): everything that does not fit in a
  project, plus one line per project. Never repeat project details here.

Write in first person. A reader should get the important things in about
30 seconds. Short is the default, not a cap: an incident period can need more
lines, or a link to the issue. Aim for roughly 2,000 characters in a normal
period. The hard 10,000-character limit in Step 5 still applies.

Title: "Wed update · Juan" or "Fri update · Juan", followed by the covered
period, for example "(Sep 30 → Oct 2)". For a late or early run, use the
intended day. Honor an explicit title from the user. The skill command stays
`/work-update`.

```markdown
**Wed update · Juan** (<period start> → <period end>)
**Projects:** <project link> 🟢/🟡/🔴 <target date> (<short note if moved or at risk>)
**Since last:** what the previous update said I'd do: ✅ done / ❌ not done (why)
**Outside projects:** incidents, ops, support, planning. Add the $ impact if there was one
**Surprises:** anything unexpected: findings, money at risk, external parties, billing, infra changes
**Decisions:** one line each + who agreed. Open questions too, + who decides
**Need:** @person + what
**Capacity:** only if reduced (sick, off, on-call heavy)
**Next:** 1-2 lines
```

Section rules:

- **Projects**: one line per Linear project where the user is the driver or
  tech lead and that moved in the period. Use the project's current health and
  target date from Linear. Do not invent a health: if Linear has none, ask the
  user. Link the project. Use ` · ` between projects.
- **Since last**: check each "Next" and "Need" item of the previous finalized
  update (for an old-format update, its "What I'm continuing next" and
  "Blockers" sections). Mark ✅ or ❌. Give a short reason for ❌. Use ` · ` between items when
  they fit on one line. An item that slipped with no reason is still listed.
- **Outside projects**: bullets with a bold lead-in. One to three sentences
  each. Say the result, not the steps. Keep the $ amount and the exposure when
  money was at risk. Link the issue for the long story.
- **Surprises**: unexpected findings only. A surprise that is also an
  incident goes under Outside projects, not both.
- **Decisions**: every decision in the period, including ones made in DMs
  (paraphrased). Name who agreed or decided. Put open questions here with the
  person who decides.
- **Need**: every blocker and every review the user waits on, each with a
  named person. If evidence does not show who, ask the user. Never leave a
  blocker without an owner. Use silent mentions (`@_**Name**`) for asks that
  are already resolved.
- **Capacity**: only when reduced. Otherwise omit.
- **Next**: one or two lines, grounded in the user's stated plan. Do not turn
  guesses into promises.

Global rules:

- Skip any section that is empty. Do not write "none".
- No PR lists. No "Reviewed" lists. GitHub has them. Reference a PR inline
  only when it carries an outcome or a reader must act on it.
- No implementation narrative. Describe outcomes. The details live in the
  PRs, the issues, and the Linear project updates.
- Use bold labels exactly as in the template. Zulip renders them well.

Do not pad a section with invented activity. The user owns the message: AI
may collect and draft, but must not present an unreviewed draft as their
finalized account.

### PR classification (internal only)

PRs no longer appear as a list in the report. Still classify the user's PRs
internally, in the sidecar, so "Since last", "Need", and the next window stay
correct. Re-fetch current state before finalizing.

- **Deployed**: live in production, with evidence for that change's deployed
  component and version. Merged or live on staging is not deployed.
- **Merged, not deployed**: on the default branch but not live in production.
  Annotate "deployment not confirmed" or "deployment not applicable".
- **Ready for review**: the user is done and waits for others. Candidates for
  the Need line.
- **In progress**: still in implementation or revision.
- **Blocked**: a concrete dependency, decision, or failing check stops it.
  Candidates for the Need line, with the owner of the blocker.
- **Reviewed**: other people's PRs the user meaningfully reviewed. Internal
  only. Mention one in the report only when the review produced a decision
  or a surprise.

## 5. Send through Zulip, review, and save

Deliver the full draft to Juan through Zulip as one DM of at most 10,000 characters, using the standing delivery
instructions below, then ask the user to guide/edit it closely: does it sound
like them, reflect what actually happened, and say what the team needs to
know? Incorporate corrections and re-show the exact revised text. The initial
evidence review does not approve an unseen final draft. Never claim that AI
verification replaces the user's responsibility for the message.

Save unapproved drafts under `~/Github/dotagents-private/data/work-update/drafts/`.
Record draft delivery in its sidecar with `sent: true` and `finalized: false`;
private delivery for review does not finalize the report or advance continuity.
After the user explicitly finalizes the report, save the exact approved text under `~/Github/dotagents-private/data/work-update/reports/` as
`<REPORT_DATE>.md` in Zulip-compatible Markdown, plus a JSON sidecar:

```json
{
  "date": "<REPORT_DATE>",
  "period_start": "<ISO 8601 with timezone>",
  "period_end": "<ISO 8601 with timezone>",
  "finalized": true,
  "sent": false,
  "projects": [{"name": "...", "url": "...", "health": "onTrack", "target": "YYYY-MM-DD"}],
  "since_last": [{"item": "...", "done": true, "note": "..."}],
  "themes": ["..."],
  "decisions": ["..."],
  "open_decisions": [{"question": "...", "decider": "..."}],
  "needs": [{"person": "...", "what": "..."}],
  "next_focus": ["..."],
  "open_prs": [{"repo": "org/repo", "number": 123, "status": "In progress"}],
  "coverage_gaps": []
}
```

Then commit and push the finalized report and sidecar. Drafts stay local
(`drafts/` is gitignored):

```bash
~/Github/dotagents-private/scripts/data-sync.sh save \
  "docs: work update <REPORT_DATE>" data/work-update/reports
```

Only finalized sidecars set the next window. Preserve the original start for
revisions; use a distinct suffix for separate updates on the same date. Keep
source references and verification notes in the sidecar as needed, outside
the team-facing prose.

### Standing delivery: Juan-Bot to Juan

Always deliver the report through Zulip, **exactly one complete direct message of at most 10,000 characters**, from
**Juan-Bot** (`juan-bot@raingroup.zulipchat.com`) to **Juan Rios**
(`juan@rainlang.xyz`) at `https://raingroup.zulipchat.com`.
This is the user's standing authorization for private report delivery and
requested revisions. Do not ask again whether to send or which destination
to use. Honor an explicit instruction to withhold delivery or use another
channel for a particular run.

Follow the `zulip` skill. Verify the bot identity with
`zulipctl --config ~/.zuliprc-bot me` and resolve Juan's account before sending.
Use the bot profile explicitly; never substitute the personal account.

```bash
zulipctl --config ~/.zuliprc-bot dm juan@rainlang.xyz < <report-path>.md
```

The complete report **must be 10,000 characters or fewer and sent as one
message**. This is a hard user requirement, even if the server permits more.
Never chunk, split into parts, or move required report content to a follow-up
message or attachment to evade the limit.

Before sending, discover the realm's actual `max_message_length` through
Zulip's register API (`fetch_event_types: ["realm"]`). Use the smaller of that
limit and 10,000. If discovery is unavailable, retain the 10,000-character cap
and verify stored content after delivery. Normalize outer whitespace, then
count the exact final Markdown in Unicode code points (Python `len(text)`),
including headings, spaces, newlines, and link destinations. Assert the count
is within the cap before making any send call; never send an oversized draft.

If the draft is over the cap, tighten wording. Keep the user's priorities,
$ impact, decisions, owners in Need, and verified attribution. Do not cut off
the end or drop a required section to fit. Before delivery, check that every
non-empty section uses its template label, and that every item in Need names a
person. Send the complete validated Markdown through stdin in one call.

A successful API acknowledgement does not prove complete delivery: Zulip can
silently truncate an oversized message. Fetch the returned message ID with
`apply_markdown=false` and compare its raw content exactly with the intended
text. Normalize outer whitespace before sending (Zulip strips it), and save
the exact sent text. Verify sender and recipient too. Never report complete delivery based
only on the CLI's `verified` field or send acknowledgement. If content differs,
record the mismatch and correct it using the verified limit before claiming
success. Do not blindly resend after an ambiguous timeout; inspect first.

For revisions, prefer updating the existing report DM in place using Zulip's
edit-message API. Resolve the latest message ID from the sidecar, fetch it,
and verify the bot sender, Juan recipient, and report identity before editing.
Apply the same size/content checks and readback verification as for a new send.
Do not send a new copy for each wording correction. If editing is unavailable,
explain the restriction before creating a replacement; never silently accumulate
report copies or use another identity to bypass edit permissions.

When the user explicitly requests deletion of earlier report messages, inspect
the actual DM history and delete only the matching bot-authored reports within
that request's scope. Verify removal. A report cleanup request in Zulip does
not authorize deleting unrelated messages or local evidence. If the bot's
deletion window has expired, the user's explicit cleanup request permits using
Juan's personal admin profile for those verified deletions: announce the
identity change and check it first. Never change permissions to enable cleanup,
and continue sending the replacement as Juan-Bot. Preserve deletion IDs and
the replacement ID in the sidecar. Do not infer standing deletion authorization
from ordinary drafting or revision requests.

Private delivery is authorized; forwarding
or posting to a team channel still needs authorization. Record the message ID,
identity, destination, actual limit, and content-comparison results in the
sidecar. Mark complete delivery only after the complete message passes readback. Keep
`finalized: false` until the user explicitly finalizes the report.

## Failure handling

- Surface unavailable sources and partial time/channel coverage during review.
  Continue useful collection; never interpret auth failures as no work.
- If chat services fail, use available local finalized work updates and legacy
  daily reports for context, marking what could not be independently checked.
- Soften or remove unverified claims; production state and user intent must
  not be guessed. Do not invent accomplishments when the window is quiet.
- Beyond the standing report DM in Step 5, no repo, PR, issue, or chat
  mutation is authorized merely by gathering an update. Other follow-up
  actions need their own user authorization.
