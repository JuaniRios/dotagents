# dotagents

Personal agent workflows for Claude Code and Codex.

- `~/.claude/commands/` is a real directory with child links into `dotclaude/commands/`
- `~/.claude/skills/` is a real directory with child links into `dotclaude/skills/`
- `~/.codex/skills` is a symlink to `dotcodex/skills/`

Claude slash commands stay Claude-native. Codex workflows are stored as skills
with `SKILL.md` files in direct child folders under `dotcodex/skills/`.

Codex skills are not slash commands. Invoke them by natural language, e.g.
`use the pr-description skill`, not `/pr-description`.
