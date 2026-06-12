---
name: night-shift
description: "Use when the user asks Codex to run an autonomous night-shift: agree on a bounded plan, work without further prompts, keep a log, avoid irreversible actions, and stop only at completion or a real blocker."
---

# night-shift

Codex-native port of the former Claude slash command `night-shift`.

Run a bounded autonomous work session after agreeing on the goal and constraints.
This workflow is for long-running repo work where the user will not be present
to answer small questions.

## Codex Goal Tools

When available, use Codex goal tools for persistence:
- `create_goal` once the user has approved the plan.
- `get_goal` periodically during long work.
- `update_goal` with `complete` only when the agreed goal is achieved.
- `update_goal` with `blocked` only after the same blocker has repeated for the
  required consecutive goal turns and no meaningful progress remains.

Do not use Claude-specific shell scripts in Codex.

## Workflow

1. Clarify the mission.
   - Define the objective, repo, branch/stack scope, verification expectations,
     and actions that are forbidden overnight.
   - Identify allowed external actions such as PR submission, Linear updates,
     or CI polling.

2. Produce a short plan and ask for approval before entering autonomous mode.
   The plan must include:
   - completion criteria,
   - stop conditions,
   - verification commands,
   - whether version-control mutations are allowed,
   - where the log will be written.

3. After approval, create the goal:
   - Objective: the approved completion criteria.
   - Token budget: only if the user explicitly gave one.

4. Maintain `NIGHT-SHIFT-LOG.md` in the repo root unless the user specifies a
   different path. Append concise entries for:
   - decisions,
   - files changed,
   - tests/checks run,
   - failures and fixes,
   - CI/PR/Linear links,
   - blockers.

5. Work autonomously.
   - Do not ask preference questions that can be resolved from repo docs or the
     approved plan.
   - Make conservative implementation choices.
   - Avoid irreversible or high-risk actions unless explicitly allowed in the
     approved plan.
   - Use `review-loop`, `ci`, `ci-fix`, `linear-cli`, and `graphite` skills
     when their trigger conditions arise.

6. Stop only when:
   - the goal is complete,
   - the same blocker has met the Codex blocked threshold,
   - an unapproved irreversible action is required,
   - credentials/secrets/user authorization are required,
   - continuing would risk unrelated user work.

7. Final report.
   Include what changed, verification, goal status, remaining risks, and the log
   path.

## Hard Rules

- Get plan approval before autonomous work begins.
- Do not perform irreversible production actions unless they are explicitly
  listed in the approved plan.
- Do not silently skip verification; record failures and fixes in the log.
- Do not mark a goal complete until the agreed completion criteria are actually
  satisfied.
- Do not mark a goal blocked merely because work is hard or slow.
