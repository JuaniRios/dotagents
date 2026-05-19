---
name: edit-skill
description: Modify, update, or refactor an existing Claude command, Claude skill, Codex skill, or paired workflow in the dotagents repo. Use when the user asks to edit, change, update, fix, improve, or tweak a skill or command. Supports "/edit-skill improve" to auto-diagnose and fix the last skill/command that ran in this session.
allowed-tools: Bash(git:*), Bash(test:*), Bash(ls:*), Read, Edit, Write, Grep, Glob, AskUserQuestion
argument-hint: "improve | <command-or-skill> [change description]"
---

# Edit skill / command

Modify an existing Claude Code command/skill or Codex skill in
`~/Github/dotagents`, which is git-tracked and symlinked into `~/.claude/` or
`~/.codex/`.

## Architecture context

```
~/Github/dotagents/          # git repo (source of truth)
  dotclaude/
    commands/                # Claude slash commands — one .md file each
    ci.md                    #   invoked as /ci
    pr-description.md        #   invoked as /pr-description
    review-loop.md
    review-pr.md
    worktree.md
    new-skill.md
    skills/                  # Claude skills — subdirectory with SKILL.md each
      graphite/SKILL.md
      linear-cli/SKILL.md
      edit-skill/SKILL.md    #   this skill
  dotcodex/
    skills/                  # Codex skills — subdirectory with SKILL.md each
      ci/SKILL.md
      graphite/SKILL.md

~/.claude/
  commands -> ~/Github/dotagents/dotclaude/commands
  skills   -> ~/Github/dotagents/dotclaude/skills

~/.codex/
  skills   -> ~/Github/dotagents/dotcodex/skills
```

### File formats

**Claude commands** — `dotclaude/commands/<name>.md`:
```yaml
---
allowed-tools: <tools>
description: <one-line>
argument-hint: <hint>  # optional
---
```

**Claude skills** — `dotclaude/skills/<name>/SKILL.md`:
```yaml
---
name: <name>
description: <one-line — Claude matches against this>
allowed-tools: <tools>
---
```

**Codex skills** — `dotcodex/skills/<name>/SKILL.md`:
```yaml
---
name: <name>
description: <one-line — Codex matches against this>
---
```

Codex skill bodies should use Codex-native language. Remove or rewrite
Claude-only references such as `allowed-tools`, `argument-hint`, `$ARGUMENTS`,
`Agent`, `AskUserQuestion`, and slash-command invocation unless the file is
explicitly documenting compatibility with a Claude workflow.

## "improve" mode

When invoked as `/edit-skill improve` (with the argument `improve` and
nothing else), follow this alternative flow instead of Steps 1–3:

### Improve Step 1 — Find the last skill/command that ran

Scan the current conversation history (above this point) to identify the
most recent skill or command that was invoked. Look for patterns like:
- `<command-name>/something</command-name>` tags
- Skill tool calls with a `skill` parameter
- References to a skill activating (e.g. "activating skill: ...")

Exclude `/edit-skill` itself — find the one *before* it.

If no prior skill/command can be found in this session, tell the user:
"No prior skill or command found in this session. Run a skill first, then
use `/edit-skill improve`." — and stop.

### Improve Step 2 — Analyze what went wrong

Review the full execution of that skill/command in the conversation:
- Did it produce errors, retries, or unexpected behavior?
- Did the agent misunderstand the intent or take a wrong path?
- Did the user have to correct or redirect the agent?
- Did the agent hit a tool permission issue, missing context, or
  ambiguity that better instructions would have prevented?

If the execution was clean with no issues, tell the user:
"The last skill/command (`/<name>`) ran without issues — nothing to
improve." — and stop.

### Improve Step 3 — Diagnose and fix

For each issue found:
1. Identify the root cause in the skill/command's description/instructions
2. Determine what change to the `.md` file would prevent it
3. Apply the edit (proceed to Step 2 below to read the file, then Step 4
   to apply edits, then Steps 5–7 as normal)

Present your diagnosis to the user before editing:

```
Last skill/command: /<name>
Issue: <what went wrong>
Root cause: <what in the skill description caused or failed to prevent it>
Proposed fix: <what you'll change>
```

Wait for user confirmation, then proceed with the edit.

---

## Step 1 — Identify the target

Determine which skill or command the user wants to edit from the
conversation context. If ambiguous, list what's available and ask:

```bash
echo "Claude commands:"
ls ~/Github/dotagents/dotclaude/commands/*.md 2>/dev/null | xargs -I{} basename {} .md
echo ""
echo "Claude skills:"
ls -d ~/Github/dotagents/dotclaude/skills/*/SKILL.md 2>/dev/null | xargs -I{} dirname {} | xargs -I{} basename {}
echo ""
echo "Codex skills:"
ls -d ~/Github/dotagents/dotcodex/skills/*/SKILL.md 2>/dev/null | xargs -I{} dirname {} | xargs -I{} basename {}
```

Then ask the user which one to edit using `AskUserQuestion`.

Resolve the file path:
- Claude command `<name>`: `~/Github/dotagents/dotclaude/commands/<name>.md`
- Claude skill `<name>`: `~/Github/dotagents/dotclaude/skills/<name>/SKILL.md`
- Codex skill `<name>`: `~/Github/dotagents/dotcodex/skills/<name>/SKILL.md`

**Always probe for a paired counterpart.** After resolving the target file,
check whether a same-named file exists in the other agent's tree (Claude
`commands/<name>.md` or `skills/<name>/SKILL.md` ↔ Codex `skills/<name>/SKILL.md`):

```bash
ls ~/Github/dotagents/dotclaude/commands/<name>.md \
   ~/Github/dotagents/dotclaude/skills/<name>/SKILL.md \
   ~/Github/dotagents/dotcodex/skills/<name>/SKILL.md 2>/dev/null
```

If a paired file exists, edit **both by default** — skills with the same name
are kept in sync, and the user expects a change to apply everywhere. Only edit
one side when the user explicitly scopes the request ("only the Claude
version", "Codex only", "just the command", etc.). When editing both, preserve
each agent's idioms (Claude `allowed-tools`/`argument-hint`/`AskUserQuestion`
on the Claude side; plain language on the Codex side); do not force identical
text.

If no paired file exists, proceed with the single target.

## Step 2 — Read and understand

Read the full file. Understand:
- The frontmatter (tools, description, argument-hint)
- The workflow steps
- The hard rules
- The overall structure

Present a brief summary to confirm you're editing the right thing:

```
Editing: <type> "<name>"
  File: <path>
  Description: <description from frontmatter>
```

## Step 3 — Understand the requested changes

The user has either already described what they want changed (in the
conversation leading to this skill activating) or needs to be asked.

If the changes are clear from context, summarize what you'll do and
proceed. If not, ask the user what specifically they want to change.

## Step 4 — Apply edits

Use the `Edit` tool for surgical changes. Use `Write` only if the file
needs a complete rewrite (rare — prefer incremental edits).

When editing:
- Preserve the existing structure and style of the file
- Keep frontmatter fields up to date (especially `description` if the
  behavior changed, `allowed-tools` if new tools are needed)
- Don't reformat or restructure parts the user didn't ask to change
- If adding new steps, number them consistently with the existing scheme
- For Codex skills, do not add Claude `allowed-tools` or `argument-hint`
  frontmatter. Describe required commands or tools in the body instead.
- For paired Claude/Codex edits, make the semantic change in both files, but
  keep each version idiomatic for that agent.

## Step 5 — Show the result

After editing, show the user what changed. Do NOT run `git diff` expecting
the user to see the output — instead, summarize the changes in prose:

```
Changes to <type> "<name>":
  - <change 1>
  - <change 2>
  - ...

Updated file: <path>
```

If the changes are substantial, read the file back and present the full
updated content so the user can review.

Ask the user if they're satisfied or want further adjustments. Iterate
until they approve.

## Step 6 — Commit

Stage and commit directly on master:

```bash
cd ~/Github/dotagents
git add <path(s)>
git commit -m "refactor: update /<name> <type>"
```

When editing a paired Claude/Codex skill, stage **both** files in the same
commit so the two sides never drift.

Use an appropriate commit prefix:
- `refactor:` for restructuring or improving
- `feat:` for adding new capabilities
- `fix:` for correcting broken behavior
- `docs:` for documentation-only changes

## Step 7 — Offer to push

```
Updated <type> "<name>" — committed.

  File: <path>
  Commit: <sha>

Want me to push?
```

Wait for confirmation. If yes, run `git push`. If no, stop.

## Hard rules

1. Always edit files in `~/Github/dotagents/`, never directly in `~/.claude/`
   or `~/.codex/`.
2. Never delete a skill or command file without explicit confirmation —
   editing means modifying, not removing.
3. Commit directly to master — no branches.
4. Show the user what changed before committing.
5. Keep frontmatter in sync with content — if behavior changes, update
   the `description` field.
6. Don't reformat or restructure parts the user didn't ask to change.
7. If a skill or command has a paired counterpart (same name in both
   `dotclaude` and `dotcodex`), edit both files in the same operation
   unless the user explicitly scopes the change to one side.
