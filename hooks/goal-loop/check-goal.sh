#!/usr/bin/env bash
# Stop hook: keep a session working toward a directory-scoped goal.
#
# Reads the Stop-hook JSON from stdin. If an active goal state file exists for
# the session's cwd, blocks stopping and returns the goal condition as the
# continuation directive, incrementing a turn counter. Releases (allows stop)
# when the goal file is gone, the turn cap is exceeded, or the state is corrupt.
# Any session without a goal file falls straight through to a normal stop.
#
# Works on Claude, Grok, Codex, and Agy. Output vocabulary differs only for
# Agy (`decision: continue`); the others use Claude's `decision: block`.
#
# Intentionally keeps blocking across turns (a goal loop must) rather than
# honoring stop_hook_active's "block once" convention. The runaway guard is the
# explicit max_turns counter, not that flag. Grok still hard-caps a single
# turn at 8 Stop continuations — the next user message starts a fresh count.

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./goal-lib.sh
. "${here}/goal-lib.sh"

# Degrade to a normal stop if jq is unavailable rather than erroring the hook.
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"

# Grok fires an extra observe-only Stop at session end; do not count it.
stop_reason="$(printf '%s' "$input" | jq -r '.reason // empty')"
if [ -n "$stop_reason" ] && [ "$stop_reason" != "end_turn" ]; then
  exit 0
fi

# Agy already hit a harness-level hard stop — don't fight it.
term="$(printf '%s' "$input" | jq -r '.terminationReason // empty')"
case "$term" in
  max_steps_exceeded|error) exit 0 ;;
esac

cwd="$(printf '%s' "$input" | jq -r '.cwd // .workspaceRoot // .workspacePaths[0] // empty')"
[ -n "$cwd" ] || exit 0

state_file="$(goal_state_file "$cwd")"
[ -f "$state_file" ] || exit 0

# Silence jq stderr: corrupt state should degrade to a clean stop, not noise.
condition="$(jq -r '.condition // empty' "$state_file" 2>/dev/null)"
max_turns="$(jq -r '.max_turns // 0' "$state_file" 2>/dev/null)"
turns="$(jq -r '.turns // 0' "$state_file" 2>/dev/null)"

# Non-numeric turn/cap (corrupt) -> treat as empty so we clear and allow stop.
case "$max_turns" in '' | *[!0-9]*) max_turns=0 ;; esac
case "$turns" in '' | *[!0-9]*) turns=0 ;; esac

# Corrupt/empty state -> clear it and allow stop rather than loop on garbage.
if [ -z "$condition" ]; then
  rm -f "$state_file"
  exit 0
fi

turns=$((turns + 1))

# Runaway guard: past the cap, clear the goal and allow the stop.
if [ "$max_turns" -gt 0 ] && [ "$turns" -gt "$max_turns" ]; then
  rm -f "$state_file"
  exit 0
fi

# Persist the incremented turn count.
tmp="$(mktemp)"
jq --argjson turns "$turns" '.turns = $turns' "$state_file" > "$tmp" && mv "$tmp" "$state_file"

reason="$(cat <<EOF
<objective>
${condition}
</objective>

Keep working toward this objective without asking the user anything (goal loop, turn ${turns}/${max_turns}). Surface verification (test/check output) in your turns so progress is visible across the loop.

When the objective is fully met, release the loop by clearing the goal:
  ${here}/goal-clear.sh
If you are genuinely blocked, state the blocker plainly, clear the goal, and stop.
EOF
)"

# Agy is the only harness that continues with decision=continue.
if printf '%s' "$input" | jq -e 'has("workspacePaths") or has("terminationReason")' >/dev/null 2>&1; then
  jq -n --arg reason "$reason" '{decision:"continue", reason:$reason}'
else
  jq -n --arg reason "$reason" '{decision:"block", reason:$reason}'
fi
exit 0
