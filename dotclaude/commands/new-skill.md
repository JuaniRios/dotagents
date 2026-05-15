---
allowed-tools: Bash(git:*), Bash(test:*), Bash(ls:*), Read, Write, Edit, Glob, Grep, AskUserQuestion
description: Create a new Claude command, Claude skill, Codex skill, or paired Claude/Codex skill in the dotagents repo. Handles file creation, git commit, and symlink verification.
argument-hint: [claude-command|claude-skill|codex-skill|both] [name]
---

# New skill / command creator

Creates a new Claude Code command/skill or Codex skill in
`~/Github/dotagents`, which is git-tracked and symlinked into the relevant
agent config.

## Architecture context

```
~/Github/dotagents/          # git repo (source of truth)
  dotclaude/
    commands/                # Claude slash commands — one .md file each
    ci.md                    #   invoked as /ci
    pr-description.md        #   invoked as /pr-description
    review-loop.md
    review-pr.md
    skills/                  # Claude skills — subdirectory with SKILL.md each
      graphite/SKILL.md
      linear-cli/SKILL.md
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

### Claude commands vs Claude skills vs Codex skills

**Claude commands** (slash commands):
- Live at `dotclaude/commands/<name>.md`
- Invoked explicitly by the user as `/<name>`
- Single `.md` file with frontmatter + instructions
- Frontmatter fields: `allowed-tools`, `description`, `argument-hint` (optional)

**Claude skills**:
- Live at `dotclaude/skills/<name>/SKILL.md`
- Auto-triggered by Claude when the description matches the user's request
- Subdirectory with `SKILL.md` (can include sibling files for context)
- Frontmatter fields: `name`, `description`, `allowed-tools`

**Codex skills**:
- Live at `dotcodex/skills/<name>/SKILL.md`
- Auto-triggered by Codex when the description matches the user's request
- Subdirectory with `SKILL.md` (can include sibling `scripts/`,
  `references/`, and `assets/`)
- Frontmatter fields: `name`, `description`
- Do not include Claude-only tool metadata such as `allowed-tools`,
  `argument-hint`, `Agent`, `AskUserQuestion`, or `$ARGUMENTS` unless the body
  is explicitly documenting a Claude compatibility detail.

**When to use which:**
- Claude command: user will invoke it explicitly in Claude (`/deploy`,
  `/lint`, `/new-skill`)
- Claude skill: Claude should activate it automatically based on context (e.g.,
  graphite skill activates whenever git operations are mentioned)
- Codex skill: Codex should activate it automatically based on context.
- Both: create sibling Claude and Codex skills with the same intent but
  agent-specific wording and metadata. Do not symlink one exact `SKILL.md`
  between Claude and Codex unless it is genuinely agent-neutral.

## Step 1 — Determine type and name

Parse `$ARGUMENTS` for type and name. Accepted types:

- `claude-command`
- `claude-skill`
- `codex-skill`
- `both` (Claude skill plus Codex skill)
- Legacy aliases: `command` means `claude-command`; `skill` means ask whether
  the user wants `claude-skill`, `codex-skill`, or `both`.

If not provided or ambiguous, ask the user using `AskUserQuestion`:

1. **Type** — "Are you creating a Claude slash command, Claude skill, Codex
   skill, or both Claude and Codex skills?"
2. **Name** — kebab-case identifier (e.g., `deploy`, `run-tests`,
   `linear-api`). This becomes the filename or directory name.

## Step 2 — Collect metadata

Ask the user (batch into one `AskUserQuestion` if possible):

1. **Description** — one-line summary of when this skill/command should be
   used. For skills, this is critical because the agent matches against it to
   decide whether to activate. Be specific about trigger phrases.
2. **Allowed tools** — which tools the skill/command needs. Common patterns:
   - Read-only research: `Read, Grep, Glob`
   - Code modification: `Read, Edit, Write, Grep, Glob`
   - Shell commands: `Bash(git:*), Bash(cargo:*), ...` (prefix-matched)
   - Full agent: `Read, Edit, Write, Bash(*), Agent`
   - Ask the user what the skill needs to do and suggest appropriate tools.
   For Codex-only skills, skip `allowed-tools` in frontmatter and instead
   describe any required tools or commands in the body.
3. **Argument hint** (Claude commands only, optional) — e.g., `<pr-number>`,
   `[--stack]`, `[skill|command] [name]`

## Step 3 — Draft the content

Ask the user to describe what the skill/command should do. Based on their
description, draft the full `.md` file following the patterns established by
existing skills/commands in this repo:

- Start with a one-line summary of what it does
- Use numbered steps for the workflow
- Include specific instructions, not vague guidance
- Add a "Hard rules" section at the end for non-negotiable constraints
- Add a "Failure modes" section if there are meaningful error cases

Show the draft to the user and ask for approval or edits. Iterate until
they're satisfied.

## Step 4 — Create the file

For a **Claude command**:

```
~/Github/dotagents/dotclaude/commands/<name>.md
```

With frontmatter:

```yaml
---
allowed-tools: <tools>
description: <description>
argument-hint: <hint>  # only if provided
---
```

For a **Claude skill**:

```
~/Github/dotagents/dotclaude/skills/<name>/SKILL.md
```

With frontmatter:

```yaml
---
name: <name>
description: <description>
allowed-tools: <tools>
---
```

For a **Codex skill**:

```
~/Github/dotagents/dotcodex/skills/<name>/SKILL.md
```

With frontmatter:

```yaml
---
name: <name>
description: <description>
---
```

For **both**, create both skill files. Keep the workflow intent aligned, but
make the wording agent-native:
- Claude version may mention slash commands, `allowed-tools`, `Agent`, and
  `AskUserQuestion`.
- Codex version should mention Codex skills, direct tool use, concise user
  questions, and subagents only when explicitly requested by the user.

Write the file using the `Write` tool.

## Step 5 — Verify

1. Confirm the file exists and is reachable through the symlink:

   ```bash
   test -f ~/.claude/commands/<name>.md && echo "Claude command linked"
   test -f ~/.claude/skills/<name>/SKILL.md && echo "Claude skill linked"
   test -f ~/.codex/skills/<name>/SKILL.md && echo "Codex skill linked"
   ```

2. Print the file path and a summary of what was created.

## Step 6 — Commit

Stage and commit directly on master:

```bash
cd ~/Github/dotagents
git add dotclaude/commands/<name>.md
# or
git add dotclaude/skills/<name>/SKILL.md
# or
git add dotcodex/skills/<name>/SKILL.md
git commit -m "feat: add /<name> <type>"
```

## Step 7 — Offer to push

Tell the user the commit is ready and ask if they want to push:

```
New <type> "<name>" created and committed.

  File: <path>
  Commit: <sha>

Want me to push?
```

Wait for confirmation. If yes, run `git push`. If no, stop.

## Hard rules

1. Always create files in `~/Github/dotagents/`, never directly in
   `~/.claude/` or `~/.codex/`.
2. Never overwrite an existing skill or command without explicit confirmation.
3. Commit directly to master — no branches.
4. Show the full draft to the user before writing any file.
5. Verify the relevant symlink works after creating the file.
