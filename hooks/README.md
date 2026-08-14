# hooks/

Goal-loop scripts used by `night-shift`. Shared across harnesses —
skills call `goal-loop/goal-set.sh` / `goal-clear.sh`. Claude's Stop
hook is pointed at `goal-loop/check-goal.sh`; other harnesses can
invoke the same scripts from the skill.
