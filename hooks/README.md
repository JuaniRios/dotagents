# hooks/

Goal-loop scripts used by `night-shift`. Shared across harnesses —
skills call `goal-loop/goal-set.sh` / `goal-clear.sh`. State lives in
`~/Github/dotagents/data/goal-loop/` (gitignored).

`goal-loop/check-goal.sh` is the Stop hook. Register it on every
harness (the installer does this):

| Harness | Config |
|---|---|
| Claude | `~/.claude/settings.json` → `hooks.Stop` |
| Grok | `~/.grok/hooks/goal-loop.json` |
| Codex | `~/.codex/hooks.json` (trust once with `/hooks`) |
| Agy | `~/.gemini/config/hooks.json` |

Templates for the last three are in `goal-loop/register/`. Refresh with:

```nu
nu ~/Github/dotagents/scripts/install-skills.nu
```

Grok hard-caps a Stop gate at 8 continuations per turn. Codex treats a
`decision: block` as a new user prompt. Agy uses `decision: continue`.
The script emits the right shape per harness.
