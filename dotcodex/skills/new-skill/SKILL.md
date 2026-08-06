---
name: new-skill
description: "Use when the user asks to run the former Claude /new-skill workflow: Create a new Claude command, Claude skill, Codex skill, or paired Claude/Codex skill in the dotagents repo. Handles file creation, git commit, and symlink verification."
---

# new-skill

Codex adaptation of the Claude slash command `new-skill`. Follow the workflow below, but use Codex-native tools and normal user questions where the original mentions Claude-only mechanisms.

Compatibility notes:
- Treat `$ARGUMENTS` as the relevant arguments or intent from the user's request.
- Replace `AskUserQuestion` with a concise question to the user when a decision is required.
- Replace Claude `Agent` calls with Codex subagents only when the user explicitly asks for parallel agents; otherwise do the work locally.
- Ignore Claude `allowed-tools`, `argument-hint`, `TodoWrite`, and `Skill` tool references as tool-permission metadata.
- When the workflow mentions another slash command, use the corresponding Codex skill or follow that workflow directly.

# New skill / command creator

Creates a new Claude Code command/skill or Codex skill in
`~/Github/dotagents`, which is git-tracked and symlinked into the relevant
agent config.

## Architecture context

```
~/Github/dotagents/          # git repo (source of truth)
  dotclaude/
    commands/                # Claude slash commands — one .md file each
    ci.md                    #   invoked as the ci skill
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
  skills/                  # REAL dir, one symlink PER skill directory
    <name>  -> ~/Github/dotagents/dotclaude/skills/<name>

~/.codex/
  skills   -> ~/Github/dotagents/dotcodex/skills   # whole-dir symlink
```

There is no `dotclaude/commands/` directory. Claude Code merged custom slash
commands into skills, so a skill at `dotclaude/skills/<name>/SKILL.md` both
creates `/<name>` and can be auto-invoked when its `description` matches.
Never create a `.md` under `dotclaude/commands/`.

### Claude skills vs Codex skills

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
  `argument-hint`, `subagent`, `ask the user`, or `the user's requested arguments` unless the body
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

Parse `the user's requested arguments` for type and name. Accepted types:

- `claude-command`
- `claude-skill`
- `codex-skill`
- `both` (Claude skill plus Codex skill)
- Legacy aliases: `command` means `claude-command`; `skill` means ask whether
  the user wants `claude-skill`, `codex-skill`, or `both`.

If not provided or ambiguous, ask the user using `ask the user`:

1. **Type** — "Are you creating a Claude slash command, Claude skill, Codex
   skill, or both Claude and Codex skills?"
2. **Name** — kebab-case identifier (e.g., `deploy`, `run-tests`,
   `linear-api`). This becomes the filename or directory name.

## Step 2 — Collect metadata

Ask the user (batch into one `ask the user` if possible):

1. **Description** — one-line summary of when this skill/command should be
   used. For skills, this is critical because the agent matches against it to
   decide whether to activate. Be specific about trigger phrases.
2. **Allowed tools** — which tools the skill/command needs. Common patterns:
   - Read-only research: `Read, Grep, Glob`
   - Code modification: `Read, Edit, Write, Grep, Glob`
   - Shell commands: `Bash(git:*), Bash(cargo:*), ...` (prefix-matched)
   - Full agent: `Read, Edit, Write, Bash(*), subagent`
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
- Claude version may mention slash commands, `allowed-tools`, `subagent`, and
  `ask the user`.
- Codex version should mention Codex skills, direct tool use, concise user
  questions, and subagents only when explicitly requested by the user.

Write the file using the `Write` tool.

## Step 5 — Verify

1. Confirm the file exists and is reachable through the symlink:

   ```bash
   test -f ~/.claude/skills/<name>/SKILL.md && echo "Claude skill linked"
   test -f ~/.codex/skills/<name>/SKILL.md && echo "Codex skill linked"
   ```

2. Print the file path and a summary of what was created.

## Step 6 — Commit

`dotagents` is a personal repo: **all changes go on `main` -- never create or
switch to a feature branch.** The repo may already be sitting on some other
branch, so switch to `main` before staging (a newly written file follows the
switch):

```bash
cd ~/Github/dotagents
git checkout main
git add dotclaude/skills/<name>/SKILL.md
# or
git add dotcodex/skills/<name>/SKILL.md
git commit -m "feat: add /<name> <type>"
```

## Step 7 — Push

Immediately push the commit to origin — no confirmation needed:

```bash
cd ~/Github/dotagents
git push
```

Then report:

```
New <type> "<name>" created, committed, and pushed.

  File: <path>
  Commit: <sha>
```

If the push fails (e.g. no network, or the remote rejected it), report the error
and the local commit sha so the user can retry `git push` manually.

## Hard rules

1. Always create files in `~/Github/dotagents/`, never directly in
   `~/.claude/` or `~/.codex/`.
2. Never overwrite an existing skill or command without explicit confirmation.
3. Personal repo: all work lands on `main`. Never create or switch to a feature
   branch; if the repo is on another branch, `git checkout main` before staging
   (Step 6).
4. Show the full draft to the user before writing any file.
5. Verify the relevant symlink works after creating the file.
6. After committing, always push to origin automatically — never wait for
   confirmation.
