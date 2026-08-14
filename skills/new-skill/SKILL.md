---
name: new-skill
description: >
  Create a new skill in the shared ~/Github/dotagents/skills tree, commit
  it on main, push, and install links so every harness can see it. Use
  when the user asks to make or add a skill.
argument-hint: "<name>"
allowed-tools: Bash(*), Read, Write
---

# New skill

Creates one agent-neutral skill in `~/Github/dotagents/skills/<name>/`.
Then runs `scripts/install-skills.nu` so Claude, Codex, Grok, and
Antigravity can load it.

## Architecture

```
~/Github/dotagents/skills/<name>/SKILL.md   # source of truth
```

`scripts/install-skills.nu` puts a per-entry symlink into each harness
dir. Do not write files under `~/.claude/`, `~/.codex/`, `~/.grok/`,
or `~/.gemini/`.

Frontmatter: `name`, `description` (a **trigger**, not a summary).
Optional frontmatter (`allowed-tools`, `argument-hint`,
`disable-model-invocation`) is fine — hosts that do not use those
keys ignore them.

Body: host-neutral. Say "ask the user", "the user's arguments",
"an isolated child", "the `foo` skill". Never name a harness-specific
tool.

If the skill fans out models, say "follow
`~/Github/dotagents/skills/panel-runtime.md`" instead of inventing
another catalogue. Harnesses are claude/codex/grok/agy; models are
opus 5, fable 5, sol 5.6, grok 4.6, flash 3.7. Do not mix the two.

## Steps

1. Name (kebab-case). Refuse to overwrite without confirmation.
2. Collect description (when to fire) and what it should do.
3. Draft the full `SKILL.md`. Show it. Iterate until the user is happy.
4. Write `~/Github/dotagents/skills/<name>/SKILL.md`.
5. `nu ~/Github/dotagents/scripts/install-skills.nu`
6. Verify: `test -f ~/Github/dotagents/skills/<name>/SKILL.md`
7. On `main` only:

```bash
cd ~/Github/dotagents
git checkout main
git add skills/<name>/SKILL.md
git commit -m "feat: add /<name> skill"
git push
```

## Hard rules

1. Files go in `~/Github/dotagents/skills/`, never in a harness dir.
2. Personal repo: land on `main`. Never a feature branch.
3. Show the draft before writing.
4. Run the install script after writing.
5. Push after commit.
