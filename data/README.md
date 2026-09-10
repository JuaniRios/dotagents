# data/

Runtime output for personal skills. Not harness-specific. Every skill
that needs to persist something points here
(`~/Github/dotagents/data/<skill>/`), never at `~/.claude`, `~/.codex`,
`~/.grok`, or `~/.gemini`.

- `progress-tracking.json` — last-run config for `progress-tracking`
- `work-update/reports/` — finalized Wednesday/Friday updates and continuity sidecars (gitignored)
- `work-update/drafts/` — unapproved update drafts (gitignored)
- `daily-report/reports/` — legacy daily reports, retained for continuity (gitignored)
- `progress-tracking/reports/` — generated progress reports (gitignored)
- `teach-log/` — durable `/teach` learning logs (gitignored)
- `handoffs/` — `/handoff` summaries for a fresh session (gitignored)
- `goal-loop/` — directory-scoped Stop-hook goal state (gitignored)
