---
name: new-skill
allowed-tools: Bash(git:*), Bash(test:*), Bash(ls:*), Bash(ln:*), Read, Write, Edit, Glob, Grep, AskUserQuestion
description: Create a new Claude skill, Codex skill, or paired Claude/Codex skill in the dotagents repo. Handles file creation, git commit, and symlink verification. Use when the user asks to make/add/create a new skill or slash command.
argument-hint: [claude-skill|codex-skill|both] [name]
---

# New skill creator

Creates a new Claude skill or Codex skill in
`~/Github/dotagents`, which is git-tracked and symlinked into the relevant
agent config.

## Architecture context

```
~/Github/dotagents/          # git repo (source of truth)
  dotclaude/
    skills/                  # Claude skills — subdirectory with SKILL.md each
      ci/SKILL.md            #   invoked as /ci
      pr-description/SKILL.md   # invoked as /pr-description
      graphite/SKILL.md
      linear-cli/SKILL.md
  dotcodex/
    skills/                  # Codex skills — subdirectory with SKILL.md each
      ci/SKILL.md
      graphite/SKILL.md

~/.claude/
  skills/                  # REAL dir — one symlink PER skill directory
    <name>  -> ~/Github/dotagents/dotclaude/skills/<name>

~/.codex/
  skills   -> ~/Github/dotagents/dotcodex/skills   # whole-dir symlink
```

Link granularity matters when adding something new:
- `~/.claude/skills` is a **real directory** whose entries are individually
  symlinked. Creating a skill in the repo does **not** make it appear — you
  must create the per-entry symlink yourself (Step 4b).
- `~/.codex/skills` is a **whole-directory** symlink, so a new Codex skill shows
  up automatically with no extra linking.

### Claude skills vs Codex skills

There is no `dotclaude/commands/` directory. Claude Code merged custom slash
commands into skills, so one skill both creates `/<name>` and can be
auto-invoked by Claude. Never create a new `.md` under `dotclaude/commands/`.

**Claude skills**:
- Live at `dotclaude/skills/<name>/SKILL.md`
- Invoked explicitly by the user as `/<name>`, **and** auto-triggered by Claude
  when the `description` matches the user's request
- Subdirectory with `SKILL.md` (can include sibling files for context)
- Frontmatter fields: `name`, `description`, `allowed-tools`, `argument-hint`
  (optional), `disable-model-invocation: true` (optional — makes it slash-only,
  for workflows with side effects that Claude should never start on its own)
- Write the `description` as a **trigger**, not a summary: say when to use it
  ("Use whenever the user says …"), or Claude will never auto-invoke it

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
- Claude skill: for use in Claude, whether the user invokes it as `/<name>` or
  Claude activates it from context (e.g. the graphite skill activates whenever
  git operations are mentioned). Both work from one file.
- Codex skill: Codex should activate it automatically based on context.
- Both: create sibling Claude and Codex skills with the same intent but
  agent-specific wording and metadata. Do not symlink one exact `SKILL.md`
  between Claude and Codex unless it is genuinely agent-neutral.

## Step 1 — Determine type and name

Parse `$ARGUMENTS` for type and name. Accepted types:

- `claude-skill`
- `codex-skill`
- `both` (Claude skill plus Codex skill)
- Legacy aliases: `command` and `claude-command` both mean `claude-skill`;
  `skill` means ask whether the user wants `claude-skill`, `codex-skill`, or
  `both`.

If not provided or ambiguous, ask the user using `AskUserQuestion`:

1. **Type** — "Are you creating a Claude skill, Codex skill, or both?"
2. **Name** — kebab-case identifier (e.g., `deploy`, `run-tests`,
   `linear-api`). This becomes the directory name.

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
3. **Argument hint** (Claude only, optional) — e.g., `<pr-number>`,
   `[--stack]`, `[skill|command] [name]`
4. **Invocation** (Claude only) — should Claude be able to start this on its
   own, or is it slash-only? Set `disable-model-invocation: true` for anything
   with side effects the user must time themselves (deploys, sends, long
   autonomous runs).

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
argument-hint: <hint>              # only if provided
disable-model-invocation: true     # only if slash-only
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

## Step 4b — Create the symlink (Claude skill only)

`~/.claude/skills` is a real directory with per-entry symlinks, so a newly
written repo file is **not** reachable until you link it. Link the whole skill
directory:

```bash
ln -s ~/Github/dotagents/dotclaude/skills/<name> ~/.claude/skills/<name>
```

For a **Codex skill**: skip this — `~/.codex/skills` is a whole-directory
symlink, so the new skill is already reachable.

## Step 5 — Verify

1. Confirm the entry exists and resolves through its symlink (`test -L` checks
   the link exists, `test -f`/`-e` that it resolves to the real file):

   ```bash
   test -L ~/.claude/skills/<name> && test -f ~/.claude/skills/<name>/SKILL.md && echo "Claude skill linked"
   test -f ~/.codex/skills/<name>/SKILL.md && echo "Codex skill linked"
   ```

   If the Claude check fails, the per-entry symlink from Step 4b is missing —
   create it and re-verify.

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
2. Never overwrite an existing skill without explicit confirmation.
3. Personal repo: all work lands on `main`. Never create or switch to a feature
   branch; if the repo is on another branch, `git checkout main` before staging
   (Step 6).
4. Show the full draft to the user before writing any file.
5. For a Claude skill, create the per-entry symlink (Step 4b) — writing
   the repo file alone does not make it reachable. Codex skills need no link.
6. Verify the relevant symlink resolves after creating the file.
7. After committing, always push to origin automatically — never wait for
   confirmation.
