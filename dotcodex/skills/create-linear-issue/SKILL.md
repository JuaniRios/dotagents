---
name: create-linear-issue
description: "Use when the user asks to create or file a new Linear issue from a description, bug report, follow-up, review finding, or task idea. Drafts the issue, confirms metadata, then creates it with the Linear CLI."
---

# create-linear-issue

Codex-native port of the former Claude slash command `create-linear-issue`.

Create exactly one high-quality Linear issue from the user's request. This
workflow is deliberately conservative: draft first, discover valid metadata
from Linear, ask for confirmation, then create.

## Required companion skill

Before creating or updating Linear data, use the `linear-cli` Codex skill. In
particular:
- Default to team `RAI` unless the user explicitly names another team.
- Run `linear <subcommand> --help` for the exact command before guessing flags.
- Use `--description-file` for markdown descriptions; do not inline markdown
  through shell flags.

## Workflow

1. Understand the request.
   - Extract the problem, expected behavior, evidence, and any constraints.
   - If the request contains multiple unrelated tasks, create only the first
     issue and state that the remaining items need separate issues.
   - Do not invent product decisions, owners, labels, milestones, or deadlines.

2. Check for obvious duplicates when the title or topic is specific:
   ```bash
   linear issue query --team RAI --search "<short search phrase>" --json
   ```
   If a likely duplicate exists, tell the user and ask whether to comment on the
   existing issue or continue creating a new one.

3. Discover metadata from Linear instead of guessing:
   ```bash
   linear issue create --help
   linear label list --team RAI
   linear project list
   linear cycle list --team RAI
   ```
   Run only the metadata commands relevant to the user's request.

4. Draft the issue:
   - Title: imperative or outcome-oriented, specific enough to scan in a list.
   - Description: concise markdown with `## Problem`, `## Expected outcome`,
     and `## Notes` when useful.
   - Acceptance criteria: include when the work has concrete observable
     completion conditions.
   - Links/evidence: preserve URLs, logs, issue IDs, PRs, or file paths the user
     supplied.

5. Confirm before creating.
   Present the proposed title, team, project/milestone/cycle if any, labels,
   priority if any, and description summary. Ask a concise confirmation
   question. Do not create the issue until the user confirms.

6. Create the issue with a temp description file under `.tmp/`:
   ```bash
   mkdir -p .tmp
   # write the markdown description to .tmp/linear-issue-<slug>.md
   linear issue create --team RAI --title "<title>" --description-file .tmp/linear-issue-<slug>.md
   ```
   Add only flags verified by `linear issue create --help`.

7. Report the created issue ID and URL. If the user asked for follow-up work,
   mention the next concrete action, such as linking it to a PR or starting the
   issue.

## Hard Rules

- Create one Linear issue per invocation unless the user explicitly asks for a
  batch.
- Read-only Linear operations are allowed before confirmation; issue creation is
  not.
- Never use inline markdown descriptions or comments when a file flag exists.
- Never create a RAI issue with labels from another team's label set.
- If metadata is ambiguous, ask; do not guess.
