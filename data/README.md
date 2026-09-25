# data/

Runtime output for personal skills. Not harness-specific. Skills persist
here (`~/Github/dotagents/data/<skill>/`), never under `~/.claude`,
`~/.codex`, `~/.grok`, or `~/.gemini`.

Reports live in the private repository instead:
`~/Github/dotagents-private/data/<skill>/`. That covers `engineer-report`,
`work-update` (reports and day journals), `progress-tracking` (reports and
config), `state-of-engineering`, `lead-review`, and `linear-groom`, plus
legacy `daily-report` files. Those skills pull and push through
`~/Github/dotagents-private/scripts/data-sync.sh`, which keeps the
nix-darwin and NixOS machines in sync and moves any legacy report files
found here into the private repository.

What stays here, all gitignored:

- `teach-log/`: durable `/teach` learning logs
- `handoffs/`: `/handoff` summaries for a fresh session
- `goal-loop/`: directory-scoped Stop-hook goal state
- `finish-pr-review/`: review checkpoints
