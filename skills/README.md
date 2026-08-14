# skills/

Agent-neutral skills. One `SKILL.md` per workflow, served to every harness.

```
~/Github/dotagents/skills/<name>/SKILL.md   # source of truth
```

Wired as:

| Harness | How it sees this tree |
|---|---|
| Claude | per-entry symlink `~/.claude/skills/<name>` |
| Codex | symlink `dotcodex/skills/<name>` → `../../skills/<name>` |
| Grok | `[skills].paths` in `~/.grok/config.toml` points here |
| Antigravity (`agy`) | per-entry symlink `~/.gemini/config/skills/<name>` |

Do not put Claude-only tool names in the body. Optional frontmatter (`allowed-tools`, `argument-hint`) is fine — other hosts ignore it.

Claude- or Codex-specific copies still live under `dotclaude/` and `dotcodex/`. New shared work goes here.
