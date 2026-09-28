---
name: forecast-milestones
description: Forecast and set Linear milestone target dates from measured team throughput, then learn from how long milestones really took. Use when the user asks to estimate, forecast, set or update deadlines or target dates for Linear milestones or projects, asks when a milestone or project will land, asks to re-forecast or recalibrate milestones, or asks how accurate past forecasts were. Do not use to estimate a single issue's effort.
argument-hint: "[project name | all | score]"
---

# Forecast milestones

Sets Linear milestone and project target dates from evidence, and improves
itself as milestones finish. `forecast.py` below means
`python3 ~/Github/dotagents/skills/forecast-milestones/forecast.py`; run
`--help` on any subcommand. The Linear pull is cached in
`~/.cache/forecast-milestones/snapshot.json`. The rest of the data lives in
`~/Github/dotagents-private/data/forecast-milestones/`:

- `ledger.jsonl`: every forecast ever made, append-only.
- `calibration.json`: the learned `bias` and `spread`.
- `lessons.md`: why past forecasts missed, one line per miss.

Pull before reading this data and save after writing it (see below).

## Why this method

A model's instinct for "how long" comes from years of hand-written software,
so it guesses effort. With agents writing the code, effort is no longer the
constraint. Elapsed time now goes to review queues, CI, deploys and
production gates, external parties, decisions, soak periods, incidents that
take priority, and scope found along the way. Those costs are already inside
the team's measured history. They are not in a model's prior.

So these rules are absolute:

1. **You never produce a duration or a date from judgement.** Every date comes
   from `forecast.py`, which samples the team's own history.
2. Your job is the *structure* the numbers cannot see: dependencies,
   fixed calendar dates, soak periods, milestones that have no issues yet.
3. Report a range (P50/P80/P90), never a single date without its percentile.
4. Every forecast is recorded, so it can be scored when the milestone ends.

The model is two outside views blended 50/50 per trial:

- **Flow**: resample the project's weekly issue throughput from the last
  8 active weeks (Monte Carlo, Vacanti/Magennis style). The remaining work is
  the open issues plus sampled scope growth. New projects fall back to how
  every project performed in its first weeks.
- **Reference class**: sample a finished milestone, take its days per
  initial issue, and scale by this milestone's open issues (Flyvbjerg).
  Scope growth is already inside that ratio.

`calibration.json` then shifts the result (`bias` multiplies durations) and
widens or narrows it around the median (`spread`). Milestones closed within one
day of their first start are record-keeping, not real work, and are
excluded as evidence.

## Every run starts here

Whatever the mode, do these steps first. `learn` runs on every invocation,
so the model improves from each milestone that finishes.

1. `~/Github/dotagents-private/scripts/data-sync.sh pull`
2. `forecast.py fetch`
3. `forecast.py learn`. On the first run it sets `calibration.json`
   from a replay of history. After that it updates `bias` and `spread` once
   5 or more recorded forecasts have finished since its last update. It uses
   each finished forecast once, so frequent runs do not count the same
   evidence twice. It moves each number at most 25% per update and keeps
   `bias` in [0.5, 2.0] and `spread` in [1.0, 3.0]. Report any change as
   old → new.
4. For every `miss:` line that `learn` prints, find the cause (see
   [Learning from misses](#learning-from-misses)) before going on.

Then run the mode. The user's argument selects it. If there is none, ask
which project.

## `<project>` or `all`: forecast, note, and propose dates

For `all`, repeat the steps for every started or planned project that has
open milestones.

1. Read every open milestone in the project: its name, description, issues,
   and recent comments (`linear milestone view <id> --all`, the `linear-cli`
   skill). Write a plan file that says only what history cannot know. Key it
   by the exact milestone name. The script rejects a name it does not know.

   ```json
   {
     "M3: RKLB pilot": {"after": "M2: Cutover readiness", "soak_days": 5},
     "M4: Full rollout": {"after": "M3: RKLB pilot"},
     "M5: Remove legacy": {"unknown": [3, 8]},
     "Live sign-off": {"floor": "2026-11-02", "lane": "ops"}
   }
   ```

   - `after`: this milestone cannot start until that one finishes. Add it
     only when the work really depends on the other milestone, not just
     because of the numbering.
   - `soak_days`: required live running after the last issue closes,
     for example a pilot that must trade for a week.
   - `floor`: the earliest possible date set by the outside world, such as a
     vendor go-live, a market calendar, or a contract date. Cite the source.
   - `unknown`: `[lo, hi]` issue count for a milestone with no issues yet or
     with obviously missing issues. Count in the team's usual issue size
     (the script prints the median milestone size). Do not count hours.
   - `lane`: milestones in different lanes share project throughput in
     parallel. By default all milestones are in one lane, in Linear sort order.
   - `weights`: `{"RAI-123": 4}` counts one open issue as that many typical
     issues. The script counts only leaf issues: a parent issue is a
     container, and its sub-issues are the work. So a big issue that
     already has sub-issues needs no weight. For a big issue without
     sub-issues, first propose splitting it in Linear, because real
     sub-issues become real evidence. Use a weight only when the user does
     not want to split. Judge the weight against the team's median issue,
     never in hours, and write the reason next to it.

2. `forecast.py forecast --project "<name>" --plan plan.json --out run.json`
3. `forecast.py note --forecast run.json`. This keeps one line at
   the end of each forecast milestone's description:
   `**Forecast** (forecast-milestones, <date>): P50 … · P80 … · P90 …`.
   It replaces the previous line and leaves the rest of the description
   unchanged. The user approved these notes once for all runs, so they need
   no approval each time. Use `--dry-run` to preview.
4. Show the user a table: milestone, open issues, current target, P50, P80,
   P90, and the plan assumptions for each milestone. Say where the evidence
   is thin: `reference-class` throughput, fewer than 5 finished milestones, or
   a throughput history of mostly zeros.
5. Propose **P80** as the new target date, the date the team commits to.
   Also give P50 as the likely date. Propose a change only when the new P80
   differs from the current target by more than max(3 days, 15% of the time
   left). Dates that move a little every run are noise and lose the team's
   trust. Mark a milestone that is already past its target as **overdue**,
   and never propose a date in the past.
6. Propose the **project** target date in the same way, from the `PROJECT`
   row. That row is the date the last milestone finishes in each simulated
   future. Never use the latest milestone P80 instead: when milestones
   overlap, their risks add up, and the project date is later than any one
   milestone's. The script warns about open project issues that have no
   milestone. They are not in the project date. Ask the user whether each
   one belongs in a milestone, or is backlog that does not block the project.
7. Ask the user which date changes to apply. For each approved change:
   `linear milestone update <id> --target-date YYYY-MM-DD`, and for the
   project `linear project update <id> --target-date YYYY-MM-DD`.
8. `forecast.py record --forecast run.json --applied "<name>"... [project]`
   Record every run, even when nothing was applied; the ledger scores
   forecasts, not decisions.
9. `data-sync.sh save "forecast-milestones: <project>" data/forecast-milestones`

## `score`: how accurate past forecasts were

1. `forecast.py score` prints each finished milestone and project
   against what was forecast for it, the P50 and P80 hit rates, and the
   median actual/P50.
2. `forecast.py backtest --calibrated` replays every finished
   milestone from its start date, using only the evidence that existed then.
   It also shows how accurate the human target dates were.
3. Report both results in plain language. Say how many forecasts each
   result rests on.

## Learning from misses

1. **Causes.** For every `miss:` line from `learn` (a forecast that
   landed outside its P10–P90), read the milestone's issue history, PRs,
   and comments. Append one line to `lessons.md`:
   `YYYY-MM-DD | project | milestone | early/late by N days | cause | evidence link`.
   Causes: `scope-growth`, `external-wait`, `review-ci-queue`,
   `deploy-gate`, `preempted-by-incident`, `hidden-dependency`,
   `bad-decomposition`, `oversized-issue`, `record-keeping`, `other:<text>`.
   For every weighted issue that finished, compare its cycle time with
   weight × the team's median cycle time, and note if weights run high or low.
2. **Method.** When one cause appears 3 or more times in `lessons.md`,
   propose a concrete change to this skill or to `forecast.py`. Examples: a
   new plan field, a different throughput window, or excluding a class of
   issues. Run `backtest --calibrated` before and after, and show both
   results. Apply it only after the user approves, through the `edit-skill`
   skill. Never change the method without a backtest showing it is better.

## Output

Link every milestone and project the user reads. Keep the report short:
the table, what changed in Linear, how much evidence the forecast rests on,
and the current calibration (its source, and any change `learn` made).

## Hard rules

1. No duration or date from judgement. Only from `forecast.py`.
2. Target dates change in Linear only after the user approves each change.
   Forecast notes in milestone descriptions are approved for every run.
3. Run `learn` at the start of every invocation, and record every forecast
   run in the ledger.
4. `learn` may change the numeric calibration within its bounds. Method or
   skill changes need a backtest and the user's approval.
5. Never commit the snapshot or any Linear data to the public `dotagents` repo.
