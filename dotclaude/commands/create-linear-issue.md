---
allowed-tools: Bash(linear:*), Bash(cat:*), Bash(mktemp:*), Bash(grep:*), Read, Write, AskUserQuestion
description: Create a well-scoped Linear issue via a draft-then-confirm flow. Drafts a tightly-scoped issue, then interactively confirms project, priority, milestone, assignee, and labels before creating. Use whenever the user asks to file/open/create a Linear issue or ticket.
argument-hint: [what the issue should be about]
---

# Create Linear issue

Create a single Linear issue through a disciplined **draft -> confirm metadata ->
create** flow. This command exists because calling `linear` directly tends to
(a) produce sprawling, unfocused issue bodies and (b) silently guess the
project/priority/assignee instead of letting the user choose. This command fixes
both.

The `linear-cli` skill owns the CLI mechanics (auth, flag discovery, file-based
markdown). **Defer to it** — do not re-document `linear` flags here. Always run
`linear <subcommand> --help` before guessing flags, and pass markdown via
`--description-file`, never inline `--description`.

## Hard rules

1. **One issue per invocation.** If the user describes several distinct pieces
   of work, propose bundling under a parent issue (see
   `docs/linear-workflow.md`) and confirm before creating multiple.
2. **Never invent project / milestone / label / assignee names.** Discover them
   live (`linear project list`, `linear label list --team RAI`, the project's
   milestones) and only offer real values in the confirmation prompt.
3. **Default team is RAI** (Rain, workspace `makeitrain`). Never default to GUA
   or anything else unless the user explicitly names another team.
4. **Always confirm metadata interactively before creating** (Step 3). Do not
   create the issue with guessed project/priority/milestone/assignee.
5. **Read-only until the final create.** Do not modify code or other issues as a
   side effect.

## Step 1 — Draft a tightly-scoped issue

Write the issue to name **one concrete thing**, not a narrative.

- **Title**: the specific change or problem, imperative and precise. Good:
  "Set max_log_files retention on the tracing file appender". Bad: "Logging
  problems on prod".
- **Body**: short. Prefer this skeleton, dropping any section that adds nothing:
  - **Problem** — the precise gap, with file/symbol references where known.
  - **Desired outcome** — the end state, behaviour-focused.
  - **Implementation** — only if a concrete approach is already known (e.g. the
    exact API/flag to use); otherwise omit and leave it to the implementer.
  - **Acceptance** — how we'll know it's done.
  - **Context** — at most a short paragraph. If this issue came out of an
    incident or investigation, the incident is *context*, not the subject —
    one or two lines, not a writeup.

Scope discipline (this is the whole point of the command):
- Describe the **problem or the specific fix**, not a tour of everything nearby.
- No operational remediation, RPC asides, timelines, or status-report prose
  unless they are literally what the issue is to track.
- If you find yourself writing more than ~25 lines for a routine fix, you are
  almost certainly over-scoping — cut.

Per `docs/linear-workflow.md`, issues describe the desired outcome; the PR
(linked later) describes the solution. For a fix issue it is fine to name the
concrete fix, but keep it to the change, not the journey.

Write the body to a temp markdown file with `Write` (for `--description-file`).

## Step 2 — Determine placement, then discover real options

1. Decide issue-vs-project and project fit per `docs/linear-workflow.md` (default
   to filing an issue; place it in an existing project when it fits that
   project's goal).
2. Discover the actual selectable values so the confirmation prompt offers only
   real ones:
   - Projects: `linear project list`
   - Labels: `linear label list --team RAI` (plus Workspace-scoped labels;
     team-scoped labels from other teams will not apply to a RAI issue)
   - Milestones: the chosen project's milestones (discover via the project; do
     not hardcode)

If discovery for a field fails, say so and offer "leave unset" rather than
guessing a value.

## Step 3 — Confirm metadata interactively (required)

Use **AskUserQuestion** to confirm, in one prompt, the fields the user should
own. Offer your recommended option first, labelled "(Recommended)", based on
Step 2:

- **Project** — recommended project (or "No project") from `project list`.
- **Priority** — Urgent / High / Medium / Low.
- **Milestone** — real milestones of the chosen project, or "No milestone".
- **Assignee** — "You (self)" / "Unassigned" / someone else.
- **Labels** — relevant real labels (use `multiSelect: true`), or none.

Also show the drafted **title** and a one-line summary of the body so the user
can redirect scope before anything is created. If the user's free-text answer
changes scope, revise the draft (Step 1) before proceeding.

Do not skip this step even when the user gave a project up front — confirm the
remaining fields.

## Step 4 — Create

Build the `linear issue create` call from the confirmed values:

- `--team RAI` (unless the user named another team)
- `--project`, `--priority`, `--milestone`, `--assignee`, `--label` (repeatable)
  as confirmed — omit any left unset
- `--description-file <temp.md>` and `--title "<title>"`

Run `linear issue create --help` first to confirm current flag names. After
creation, print the returned issue URL. If the work relates to a chained PR or
parent issue, note that per `docs/linear-workflow.md` — but do not invent links.

## Step 5 — Report

Give the user: the issue ID + URL, the final title, and the confirmed
project/priority/milestone/assignee/labels in one or two lines. Do not paste the
full body back.
