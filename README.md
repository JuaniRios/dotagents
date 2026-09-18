# dotagents

Personal agent skills. One tree, every harness.

```
~/Github/dotagents/skills/<name>/SKILL.md
```

Shared T0 operational skills (`investigate`, `pnl-review`, `release-service`,
`breakglass`, ...) live in
[`T0Trade/agent-skills`](https://github.com/T0Trade/agent-skills), not here.
The installer clones it to `~/Github/agent-skills` when missing, fast-forwards
a clean `main` checkout, and links its skills next to these. A name in both
trees is an error.

Install (or refresh) the per-harness links (`rebuild` runs this too):

```nu
nu ~/Github/dotagents/scripts/install-skills.nu
```

| Harness | Link farm |
|---|---|
| Claude | `~/.claude/skills/<name>` |
| Codex | `~/.codex/skills/<name>` and `~/.codex-2/skills/<name>` (plus `.system` → `~/.codex/system-skills`) |
| Grok | `~/.grok/skills/<name>` and `[skills].paths` in `~/.grok/config.toml` |
| Antigravity | `~/.gemini/config/skills/<name>` and `~/.gemini/antigravity-cli/skills/<name>` |

Multi-lab orchestration (`review-loop`, `review-pr`, `critique-loop`,
`implement-issue`, `plan-issue`) follows `skills/panel-runtime.md`.

Shared runtime files live in `data/` (reports, teach logs, handoffs,
skill state, goal-loop) and `hooks/` (goal-loop Stop hook). Skills
persist there — never under a harness home dir. The installer also
registers that Stop hook on Grok, Codex, and Agy (Claude is already
in `~/.claude/settings.json`). All changes land on `main`.
