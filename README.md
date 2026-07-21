# dotagents

Personal agent workflows for Claude Code and Codex.

- `~/.claude/skills/` is a real directory with child links into `dotclaude/skills/`
- `~/.codex/skills` is a symlink to `dotcodex/skills/`

Everything on the Claude side is a skill. Claude Code merged custom slash
commands into skills, so `dotclaude/skills/<name>/SKILL.md` both creates
`/<name>` and lets Claude invoke it on its own when the `description` matches.
There is no `dotclaude/commands/` directory. Add `disable-model-invocation: true`
to a skill that should stay slash-only.

Codex workflows are stored as skills with `SKILL.md` files in direct child
folders under `dotcodex/skills/`. They are kept separate from the Claude
versions on purpose — the bodies use Codex-native language.

Codex skills are not slash commands. Invoke them by natural language, e.g.
`use the pr-description skill`, not `/pr-description`.
