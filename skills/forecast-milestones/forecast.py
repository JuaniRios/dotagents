#!/usr/bin/env python3
"""Evidence-based Linear milestone forecaster.

Durations come from measured team throughput and scope growth, never from
effort guesses. Subcommands: fetch, backtest, forecast, record, score.
"""

import argparse
import collections
import datetime as dt
import json
import os
import random
import statistics
import subprocess
import sys

DATA = os.path.expanduser(
    os.environ.get("FORECAST_DATA", "~/Github/dotagents-private/data/forecast-milestones")
)
SNAPSHOT = os.path.expanduser(
    os.environ.get("FORECAST_SNAPSHOT", "~/.cache/forecast-milestones/snapshot.json")
)
LEDGER = os.path.join(DATA, "ledger.jsonl")
CALIBRATION = os.path.join(DATA, "calibration.json")

TRIALS = 5000
WINDOW_WEEKS = 8
MIN_ACTIVE_WEEKS = 3
QUANTILES = [10, 20, 30, 40, 50, 60, 70, 80, 90]

ISSUES_QUERY = """query($after:String){ issues(first:100, after:$after,
  filter:{project:{null:false}}, includeArchived:true){ nodes {
  identifier title createdAt startedAt completedAt canceledAt
  project { id name }
  projectMilestone { id name targetDate createdAt sortOrder }
  parent { projectMilestone { id name targetDate createdAt sortOrder } }
  children { nodes { id } }
} pageInfo{hasNextPage endCursor} } }"""

MILESTONES_QUERY = """query($after:String){ projectMilestones(first:100, after:$after){ nodes {
  id name targetDate createdAt sortOrder project { id name state targetDate }
} pageInfo{hasNextPage endCursor} } }"""


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def day(d):
    return d.date().isoformat()


def now():
    return dt.datetime.now(dt.timezone.utc)


def linear(query):
    out = subprocess.run(
        ["linear", "api", "--paginate", query], capture_output=True, text=True, check=True
    ).stdout
    data = json.loads(out)
    if isinstance(data, dict) and "errors" in data:
        sys.exit(f"Linear API error: {data['errors']}")
    return data


def linear_one(query, variables):
    out = subprocess.run(
        ["linear", "api", query, "--variables-json", json.dumps(variables)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    if "errors" in data:
        sys.exit(f"Linear API error: {data['errors']}")
    return data


def load():
    if not os.path.exists(SNAPSHOT):
        sys.exit("No snapshot. Run: forecast.py fetch")
    snap = json.load(open(SNAPSHOT))
    leaves = []
    for i in snap["issues"]:
        for k in ("createdAt", "startedAt", "completedAt", "canceledAt"):
            i[k] = ts(i[k])
        # A parent issue is a container: its sub-issues are the work, so count
        # only leaves. A sub-issue without a milestone belongs to its parent's.
        if i.get("children", {}).get("nodes"):
            continue
        if not i["projectMilestone"] and (i.get("parent") or {}).get("projectMilestone"):
            i["projectMilestone"] = i["parent"]["projectMilestone"]
        leaves.append(i)
    snap["issues"] = leaves
    return snap


def calibration():
    if os.path.exists(CALIBRATION):
        return json.load(open(CALIBRATION))
    return {"bias": 1.0, "spread": 1.3}


# ---------- evidence ----------


def weekly_throughput(issues, project_id, t0):
    """Issues completed per week in the project over the window before t0.

    Weeks before the project's first started issue are excluded, so a new
    project is not penalised for time it did not exist.
    """
    mine = [i for i in issues if i["project"]["id"] == project_id and not i["canceledAt"]]
    starts = [i["startedAt"] for i in mine if i["startedAt"] and i["startedAt"] < t0]
    if not starts:
        return []
    first = min(starts)
    weeks = []
    for w in range(WINDOW_WEEKS):
        hi = t0 - dt.timedelta(weeks=w)
        lo = hi - dt.timedelta(weeks=1)
        if hi <= first:
            break
        weeks.append(sum(1 for i in mine if i["completedAt"] and lo <= i["completedAt"] < hi))
    return weeks


def reference_throughput(issues, t0):
    """Weekly throughput of every project during its first active weeks (outside view)."""
    pool = []
    for pid in {i["project"]["id"] for i in issues}:
        mine = [i for i in issues if i["project"]["id"] == pid and not i["canceledAt"]]
        starts = [i["startedAt"] for i in mine if i["startedAt"] and i["startedAt"] < t0]
        if not starts:
            continue
        first = min(starts)
        for w in range(6):
            lo = first + dt.timedelta(weeks=w)
            hi = lo + dt.timedelta(weeks=1)
            if hi > t0:
                break
            pool.append(sum(1 for i in mine if i["completedAt"] and lo <= i["completedAt"] < hi))
    return pool or [1]


def milestone_groups(issues):
    groups = collections.defaultdict(list)
    for i in issues:
        if i["projectMilestone"] and not i["canceledAt"]:
            groups[i["projectMilestone"]["id"]].append(i)
    return groups


def completed_milestones(issues, before=None):
    """Milestones whose issues are all done, with start, end, size, growth."""
    out = []
    for mid, iss in milestone_groups(issues).items():
        if not all(i["completedAt"] for i in iss):
            continue
        starts = [i["startedAt"] or i["completedAt"] for i in iss]
        start, end = min(starts), max(i["completedAt"] for i in iss)
        if before and end >= before:
            continue
        if (end - start) < dt.timedelta(days=1):
            continue  # bulk-closed bookkeeping, not real flow
        initial = sum(1 for i in iss if i["createdAt"] <= start + dt.timedelta(days=1))
        out.append(
            {
                "id": mid,
                "milestone": iss[0]["projectMilestone"],
                "project": iss[0]["project"],
                "issues": iss,
                "start": start,
                "end": end,
                "size": len(iss),
                "initial": max(initial, 1),
                "growth": len(iss) / max(initial, 1) - 1,
            }
        )
    return out


# ---------- simulation ----------


def rcf_days(past, work_issues, rng):
    """Reference-class sample: days per initial issue from a finished milestone, times work."""
    m = rng.choice(past)
    return (m["end"] - m["start"]).total_seconds() / 86400 / m["initial"] * work_issues



def simulate(milestones, throughput, growth, sizes, t0, cal, rng):
    """Monte Carlo over weekly throughput. Returns {milestone_id: [days...]}.

    milestones: ordered list of dicts with id, lane, open, initial, total,
    unknown (optional [lo, hi]), soak_days, floor (date or None).
    """
    result = {m["id"]: [] for m in milestones}
    lanes = {}
    for m in milestones:
        lanes.setdefault(m.get("lane", "main"), []).append(m)
    lane_names = list(lanes)
    for _ in range(TRIALS):
        remaining = {}
        for m in milestones:
            if m.get("unknown"):
                lo, hi = m["unknown"]
                base = rng.randint(lo, hi)
            elif m["total"] == 0:
                base = rng.choice(sizes)
            else:
                base = None
            if base is not None:
                work = base * (1 + rng.choice(growth))
            else:
                final = m["initial"] * (1 + rng.choice(growth))
                work = m["open"] + max(0.0, final - m["total"])
            remaining[m["id"]] = max(work, 0.0)
        done = {}
        cursor = dict.fromkeys(lane_names, 0)
        week = 0
        while len(done) < len(milestones) and week < 520:
            cap = rng.choice(throughput) * cal["bias_inv"]
            active = []
            for name in lane_names:
                if cursor[name] < len(lanes[name]):
                    active.append(name)
            share = cap / max(len(active), 1)
            for lane in active:
                budget = share
                while cursor[lane] < len(lanes[lane]) and budget > 0:
                    m = lanes[lane][cursor[lane]]
                    need = remaining[m["id"]]
                    if need <= budget:
                        frac = need / share if share else 1
                        done[m["id"]] = (week + min(frac, 1)) * 7
                        budget -= need
                        remaining[m["id"]] = 0
                        cursor[lane] += 1
                    else:
                        remaining[m["id"]] -= budget
                        budget = 0
            week += 1
        for m in milestones:
            d = done.get(m["id"], 520 * 7) + m.get("soak_days", 0)
            finish = t0 + dt.timedelta(days=d)
            if m.get("floor"):
                finish = max(finish, dt.datetime.fromisoformat(m["floor"] + "T00:00:00+00:00"))
            result[m["id"]].append((finish - t0).total_seconds() / 86400)
    return result


def spread_quantiles(days, cal):
    qs = statistics.quantiles(days, n=100)
    med = qs[49]
    return {f"p{q}": med + (qs[q - 1] - med) * cal["spread"] for q in QUANTILES}


def prepare_cal(cal):
    c = dict(cal)
    c["bias_inv"] = 1 / c.get("bias", 1.0)
    return c


def evidence(issues, project_id, t0):
    tp = weekly_throughput(issues, project_id, t0)
    source = "project"
    if len(tp) < MIN_ACTIVE_WEEKS or sum(tp) == 0:
        tp = reference_throughput(issues, t0)
        source = "reference-class"
    if not any(tp):
        tp = [1]
    past = completed_milestones(issues, before=t0)
    growth = [m["growth"] for m in past] or [0.3]
    sizes = [m["size"] for m in past] or [5]
    return tp, source, growth, sizes


# ---------- commands ----------


def cmd_fetch(_):
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    snap = {
        "fetched_at": now().isoformat(),
        "issues": linear(ISSUES_QUERY),
        "milestones": linear(MILESTONES_QUERY),
    }
    json.dump(snap, open(SNAPSHOT, "w"))
    print(f"{len(snap['issues'])} issues, {len(snap['milestones'])} milestones -> {SNAPSHOT}")


def prior_all(issues, t0):
    """Issues as known at t0: completion after t0 is hidden."""
    out = []
    for i in issues:
        if i["createdAt"] > t0:
            continue
        j = dict(i)
        if j["completedAt"] and j["completedAt"] > t0:
            j["completedAt"] = None
        out.append(j)
    return out


def backtest_rows(issues, method, cal, min_size):
    """Replay: forecast each finished milestone from its start, using only prior evidence."""
    rng = random.Random(7)
    rows = []
    for m in completed_milestones(issues):
        t0 = m["start"]
        if m["size"] < min_size:
            continue
        prior = prior_all(issues, t0)
        tp, source, growth, sizes = evidence(prior, m["project"]["id"], t0)
        spec = [{"id": m["id"], "open": m["initial"], "initial": m["initial"], "total": m["initial"]}]
        past = completed_milestones(prior_all(issues, t0), before=t0)
        if method == "flow":
            days = simulate(spec, tp, growth, sizes, t0, cal, rng)[m["id"]]
        elif method == "rcf":
            if len(past) < 5: continue
            days = [rcf_days(past, m["initial"], rng) * cal["bias"] for _ in range(TRIALS)]
        else:
            if len(past) < 5: continue
            a = simulate(spec, tp, growth, sizes, t0, cal, rng)[m["id"]]
            days = [x if rng.random() < 0.5 else rcf_days(past, m["initial"], rng) * cal["bias"] for x in a]
        q = spread_quantiles(days, cal)
        actual = (m["end"] - t0).total_seconds() / 86400
        target = m["milestone"]["targetDate"]
        human = None
        if target and ts(m["milestone"]["createdAt"]) <= t0 + dt.timedelta(days=2):
            human = (dt.datetime.fromisoformat(target + "T23:59:59+00:00") - t0).total_seconds() / 86400
        pit = sum(1 for d in days if d <= actual) / len(days)
        rows.append((m, source, q, actual, human, pit))
    return rows


def cmd_backtest(args):
    snap = load()
    cal = prepare_cal(calibration() if args.calibrated else {"bias": 1.0, "spread": 1.0})
    rows = backtest_rows(snap["issues"], args.method, cal, args.min_size)
    if not rows:
        sys.exit("No finished milestones to backtest.")
    print(f"{'project':22} {'milestone':26} {'src':4} {'p50':>6} {'p80':>6} {'actual':>7} {'human':>6} {'pit':>5}")
    for m, source, q, actual, human, pit in sorted(rows, key=lambda r: r[0]["start"]):
        print(
            f"{m['project']['name'][:22]:22} {m['milestone']['name'][:26]:26} {source[:4]:4} "
            f"{q['p50']:6.1f} {q['p80']:6.1f} {actual:7.1f} {human if human is None else round(human,1)!s:>6} {pit:5.2f}"
        )
    summarize(
        [(r[2], r[3]) for r in rows],
        [(r[4], r[3]) for r in rows if r[4] and r[4] > 0],
    )


def summarize(model, human):
    n = len(model)
    hit50 = sum(1 for q, a in model if a <= q["p50"]) / n
    hit80 = sum(1 for q, a in model if a <= q["p80"]) / n
    ratio = statistics.median(a / max(q["p50"], 0.5) for q, a in model)
    print(f"\nmodel: n={n}  P50 hit={hit50:.0%} (want 50%)  P80 hit={hit80:.0%} (want 80%)  median actual/P50={ratio:.2f}")
    if human:
        hh = sum(1 for t, a in human if a <= t) / len(human)
        hr = statistics.median(a / t for t, a in human)
        print(f"human targets: n={len(human)}  on-time={hh:.0%}  median actual/planned={hr:.2f}")
    print(f"suggested calibration: bias={ratio:.2f} (multiply durations), spread: "
          f"{'widen' if hit80 < 0.72 else 'narrow' if hit80 > 0.88 else 'keep'}")


def rcf_finish(spec, past, sizes, t0, cal, rng):
    """Reference-class finish days per milestone; `after` chains a milestone behind another."""
    by_name = {s["name"]: s for s in spec}
    out = {s["id"]: [] for s in spec}
    for _ in range(TRIALS):
        fin = {}

        def finish(s):
            if s["id"] in fin:
                return fin[s["id"]]
            if s.get("unknown"):
                work = rng.randint(*s["unknown"])
            elif s["total"] == 0:
                work = rng.choice(sizes)
            else:
                work = s["open"]
            begin = finish(by_name[s["after"]]) if s.get("after") in by_name else 0.0
            d = begin + rcf_days(past, work, rng) * cal["bias"] + s.get("soak_days", 0)
            if s.get("floor"):
                floor = dt.datetime.fromisoformat(s["floor"] + "T00:00:00+00:00")
                d = max(d, (floor - t0).total_seconds() / 86400)
            fin[s["id"]] = d
            return d

        for s in spec:
            out[s["id"]].append(finish(s))
    return out


def cmd_forecast(args):
    snap = load()
    issues = snap["issues"]
    t0 = now()
    plan = json.load(open(args.plan)) if args.plan else {}
    ms = [
        m for m in snap["milestones"]
        if args.project.lower() in (m["project"]["name"].lower(), m["project"]["id"])
    ]
    if not ms:
        sys.exit(f"No milestones for project {args.project!r}")
    project_id = ms[0]["project"]["id"]
    names = {m["name"] for m in ms}
    bad = [k for k in plan if k not in names]
    bad += [v["after"] for v in plan.values() if v.get("after") and v["after"] not in names]
    if bad:
        sys.exit(f"Plan names no milestone in this project: {bad}. Names: {sorted(names)}")
    groups = milestone_groups(issues)
    spec = []
    for m in sorted(ms, key=lambda m: m["sortOrder"]):
        iss = groups.get(m["id"], [])
        open_ = [i for i in iss if not i["completedAt"]]
        if iss and not open_:
            continue
        p = plan.get(m["name"], {})
        weights = p.get("weights", {})
        open_weight = sum(weights.get(i["identifier"], 1) for i in open_)
        started = [i["startedAt"] for i in iss if i["startedAt"]]
        start = min(started) if started else t0
        initial = sum(1 for i in iss if i["createdAt"] <= start + dt.timedelta(days=1)) or len(iss)
        spec.append(
            {
                "id": m["id"], "name": m["name"], "target": m["targetDate"],
                "open": open_weight, "total": len(iss) + open_weight - len(open_),
                "initial": initial + open_weight - len(open_),
                "lane": p.get("lane", "main"), "unknown": p.get("unknown"),
                "soak_days": p.get("soak_days", 0), "floor": p.get("floor"),
                "order": p.get("order", 0), "after": p.get("after"),
            }
        )
    spec.sort(key=lambda s: s["order"])
    cal = prepare_cal(calibration())
    tp, source, growth, sizes = evidence(issues, project_id, t0)
    rng = random.Random(args.seed)
    flow = simulate(spec, tp, growth, sizes, t0, cal, rng)
    past = completed_milestones(issues, before=t0)
    res = flow
    if len(past) >= 5:
        rcf = rcf_finish(spec, past, sizes, t0, cal, rng)
        pick = [rng.random() < 0.5 for _ in range(TRIALS)]
        res = {k: [f if p else r for f, r, p in zip(flow[k], rcf[k], pick)] for k in flow}
    out = {
        "run_at": t0.isoformat(), "project": ms[0]["project"]["name"], "project_id": project_id,
        "throughput": tp, "throughput_source": source,
        "growth_median": statistics.median(growth), "calibration": calibration(), "milestones": [],
    }
    print(f"{out['project']}  throughput/wk={tp} ({source})  median scope growth={out['growth_median']:.0%}  median milestone size={statistics.median(sizes):g} issues  cal={out['calibration']}")
    print(f"{'milestone':34} {'open':>4} {'target':>10} {'P50':>10} {'P80':>10} {'P90':>10}")
    for s in spec:
        q = spread_quantiles(res[s["id"]], cal)
        dates = {k: day(t0 + dt.timedelta(days=v)) for k, v in q.items()}
        print(f"{s['name'][:34]:34} {s['open']:4} {s['target'] or '-':>10} {dates['p50']:>10} {dates['p80']:>10} {dates['p90']:>10}")
        out["milestones"].append({**{k: s[k] for k in ("id", "name", "target", "open", "total", "lane", "unknown", "soak_days", "floor", "after")}, "quantiles": dates})
    # The project ends when its last milestone ends, in each simulated future.
    # This is later than the latest milestone P80 when milestones overlap.
    if spec:
        last = [max(res[s["id"]][t] for s in spec) for t in range(TRIALS)]
        q = spread_quantiles(last, cal)
        for k in q:
            q[k] = max([q[k]] + [spread_quantiles(res[s["id"]], cal)[k] for s in spec])
        dates = {k: day(t0 + dt.timedelta(days=v)) for k, v in q.items()}
        target = ms[0]["project"].get("targetDate")
        print(f"{'PROJECT (last milestone done)':34} {sum(s['open'] for s in spec):4} {target or '-':>10} {dates['p50']:>10} {dates['p80']:>10} {dates['p90']:>10}")
        out["project_forecast"] = {"target": target, "quantiles": dates}
    loose = [i for i in issues if i["project"]["id"] == project_id and not i["projectMilestone"]
             and not i["completedAt"] and not i["canceledAt"]]
    if loose:
        print(f"\nwarning: {len(loose)} open issues in this project have no milestone and are not in the project date: "
              + ", ".join(i["identifier"] for i in loose[:15]))
    out["unassigned_open"] = [i["identifier"] for i in loose]
    if args.out:
        json.dump(out, open(args.out, "w"), indent=2)
        print(f"\nwrote {args.out}")


def cmd_record(args):
    os.makedirs(DATA, exist_ok=True)
    f = json.load(open(args.forecast))
    applied = set(args.applied or [])
    with open(LEDGER, "a") as led:
        for m in f["milestones"]:
            led.write(json.dumps({
                "run_at": f["run_at"], "project": f["project"], "milestone_id": m["id"],
                "name": m["name"], "quantiles": m["quantiles"], "open": m["open"],
                "previous_target": m["target"], "applied": m["name"] in applied or m["id"] in applied,
                "throughput_source": f["throughput_source"], "calibration": f["calibration"],
            }) + "\n")
        if f.get("project_forecast"):
            led.write(json.dumps({
                "run_at": f["run_at"], "project": f["project"], "milestone_id": "project:" + f["project_id"],
                "name": "(project)", "quantiles": f["project_forecast"]["quantiles"],
                "previous_target": f["project_forecast"]["target"], "applied": "project" in applied,
                "throughput_source": f["throughput_source"], "calibration": f["calibration"],
            }) + "\n")
    print(f"recorded {len(f['milestones'])} forecasts -> {LEDGER}")


def scored_rows(snap):
    """Ledger forecasts whose milestone or project has since finished.

    Returns (key, record, quantile days, actual days); one per target per day.
    """
    if not os.path.exists(LEDGER):
        return []
    ends = {m["id"]: m["end"] for m in completed_milestones(snap["issues"])}
    by_project = collections.defaultdict(list)
    for iss in milestone_groups(snap["issues"]).values():
        by_project[iss[0]["project"]["id"]].extend(iss)
    for pid, iss in by_project.items():
        if all(i["completedAt"] for i in iss):
            ends["project:" + pid] = max(i["completedAt"] for i in iss)
    rows, seen = [], set()
    for line in open(LEDGER):
        r = json.loads(line)
        end = ends.get(r["milestone_id"])
        key = f"{r['milestone_id']}@{r['run_at'][:10]}"
        if not end or key in seen:
            continue
        seen.add(key)
        run = ts(r["run_at"])
        q = {k: (dt.datetime.fromisoformat(v + "T23:59:59+00:00") - run).total_seconds() / 86400
             for k, v in r["quantiles"].items()}
        rows.append((key, r, q, (end - run).total_seconds() / 86400, end))
    return rows


def cmd_score(args):
    """Score ledger forecasts against milestones that have since finished."""
    rows = scored_rows(load())
    if not rows:
        sys.exit("No recorded forecast has finished yet.")
    for _, r, _, _, end in rows:
        print(f"{r['run_at'][:10]} {r['project'][:20]:20} {r['name'][:30]:30} "
              f"P50={r['quantiles']['p50']} P80={r['quantiles']['p80']} actual={day(end)}")
    summarize([(q, a) for _, _, q, a, _ in rows], [])


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def cmd_learn(args):
    os.makedirs(DATA, exist_ok=True)
    """Update calibration from forecasts that finished since the last update.

    Each finished forecast is used once, so running this every time does not
    compound the same evidence. Numbers move at most 25% per update.
    """
    snap = load()
    if not os.path.exists(CALIBRATION):
        rows = backtest_rows(snap["issues"], "blend", prepare_cal({"bias": 1.0, "spread": 1.0}), 3)
        ratio = statistics.median(a / max(q["p50"], 0.5) for _, _, q, a, _, _ in rows)
        cal = {"bias": round(clamp(ratio, 0.5, 2.0), 3), "spread": 1.3,
               "source": f"backtest {day(now())} n={len(rows)}", "learned": [], "misses_reported": []}
        json.dump(cal, open(CALIBRATION, "w"), indent=2)
        print(f"learn: bootstrapped from backtest: bias={cal['bias']} spread={cal['spread']} (n={len(rows)})")
        return
    cal = json.load(open(CALIBRATION))
    cal.setdefault("learned", [])
    cal.setdefault("misses_reported", [])
    rows = [r for r in scored_rows(snap) if not r[1]["milestone_id"].startswith("project:")]
    new = [r for r in rows if r[0] not in cal["learned"]]
    misses = [r for r in new if r[0] not in cal["misses_reported"] and not (r[2]["p10"] <= r[3] <= r[2]["p90"])]
    for key, r, q, actual, end in misses:
        side = "late" if actual > q["p90"] else "early"
        print(f"miss: {r['project']} | {r['name']} | {side} | forecast {r['run_at'][:10]} P10={r['quantiles']['p10']} "
              f"P90={r['quantiles']['p90']} actual={day(end)}")
        cal["misses_reported"].append(key)
    if len(new) < 5:
        print(f"learn: {len(new)} newly finished forecasts; need 5 to update. "
              f"Calibration unchanged: bias={cal['bias']} spread={cal['spread']}")
    else:
        # Undo the bias each forecast was made with, so the target is absolute.
        raw = statistics.median(
            a / max(q["p50"] / r["calibration"].get("bias", 1.0), 0.5) for _, r, q, a, _ in new
        )
        old = (cal["bias"], cal["spread"])
        cal["bias"] = round(clamp(clamp(raw, old[0] * 0.75, old[0] * 1.25), 0.5, 2.0), 3)
        hit80 = sum(1 for _, _, q, a, _ in new if a <= q["p80"]) / len(new)
        step = 0.1 if hit80 < 0.72 else -0.1 if hit80 > 0.88 else 0.0
        cal["spread"] = round(clamp(old[1] + step, 1.0, 3.0), 2)
        cal["learned"] += [r[0] for r in new]
        cal["source"] = f"ledger {day(now())} n={len(new)} P80 hit={hit80:.0%}"
        print(f"learn: n={len(new)} P80 hit={hit80:.0%} bias {old[0]} -> {cal['bias']}, spread {old[1]} -> {cal['spread']}")
    json.dump(cal, open(CALIBRATION, "w"), indent=2)


NOTE_TAG = "(forecast-milestones"


def cmd_note(args):
    """Keep one forecast line at the end of each forecast milestone's description."""
    f = json.load(open(args.forecast))
    run = f["run_at"][:10]
    for m in f["milestones"]:
        q = m["quantiles"]
        line = (f"**Forecast** {NOTE_TAG}, {run}): P50 {q['p50']} · P80 {q['p80']} · P90 {q['p90']}"
                f" · {f['throughput_source']} throughput")
        cur = linear_one("query($id:String!){ projectMilestone(id:$id){ description } }", {"id": m["id"]})
        desc = (cur["data"]["projectMilestone"]["description"] or "").rstrip()
        kept = [l for l in desc.split("\n") if NOTE_TAG not in l]
        new = ("\n".join(kept).rstrip() + "\n\n" + line).strip()
        if args.dry_run:
            print(f"--- {m['name']}\n{new}\n")
            continue
        linear_one(
            "mutation($id:String!,$d:String!){ projectMilestoneUpdate(id:$id, input:{description:$d}){ success } }",
            {"id": m["id"], "d": new},
        )
        print(f"noted {m['name']}: {line}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)
    b = sub.add_parser("backtest")
    b.add_argument("--min-size", type=int, default=3)
    b.add_argument("--method", choices=["flow", "rcf", "blend"], default="blend")
    b.add_argument("--calibrated", action="store_true", help="apply calibration.json")
    b.set_defaults(fn=cmd_backtest)
    f = sub.add_parser("forecast")
    f.add_argument("--project", required=True)
    f.add_argument("--plan", help="JSON of per-milestone overrides keyed by milestone name")
    f.add_argument("--out")
    f.add_argument("--seed", type=int, default=7)
    f.set_defaults(fn=cmd_forecast)
    r = sub.add_parser("record")
    r.add_argument("--forecast", required=True)
    r.add_argument("--applied", nargs="*", help="milestone names or ids whose target date was changed")
    r.set_defaults(fn=cmd_record)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    sub.add_parser("learn").set_defaults(fn=cmd_learn)
    n = sub.add_parser("note")
    n.add_argument("--forecast", required=True)
    n.add_argument("--dry-run", action="store_true")
    n.set_defaults(fn=cmd_note)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
