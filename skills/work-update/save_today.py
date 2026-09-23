#!/usr/bin/env python3
"""Collect one local day's work evidence for /work-update save-today.

Usage:
  save_today.py collect [--date YYYY-MM-DD] [--outdir DIR] [--zulip-tmp DIR]

Writes:
  <outdir>/YYYY-MM-DD.evidence.json   structured facts for the day
  <outdir>/YYYY-MM-DD.stub.md         machine summary (agent replaces with narrative)

The agent reads the evidence bundle and writes/updates YYYY-MM-DD.md using the
save-today template in the work-update skill. Re-running the same date refreshes
evidence.json and preserves any existing narrative block in the sidecar when present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = HOME / "Github" / "dotagents" / "data" / "work-update" / "days"
TELEGRAM_CHATS = HOME / ".config" / "daily-report-telegram-chats.txt"
USER_EMAIL = "juan@rainlang.xyz"
USER_ZULIP = "Juan Rios"
ZULIP_HEADER_COMBINED = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+#(?P<topic>[^\s]+)\s+"
    r"(?P<sender>.+?)\s+<(?P<email>[^>]+)>\s+id=(?P<id>\d+)\s*$",
    re.MULTILINE,
)
ZULIP_HEADER_PLAIN = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+(?P<sender>.+?)\s+<(?P<email>[^>]+)>\s+id=(?P<id>\d+)\s*$",
    re.MULTILINE,
)


def parse_zulip_user_messages(text: str, channel_topic: str, default_topic: str = "") -> list[dict]:
    matches = list(ZULIP_HEADER_COMBINED.finditer(text))
    plain = False
    if not matches:
        matches = list(ZULIP_HEADER_PLAIN.finditer(text))
        plain = True
    out = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if match.group("email") != USER_EMAIL and USER_ZULIP not in match.group("sender"):
            continue
        topic = match.group("topic") if not plain else default_topic
        out.append(
            {
                "channel_topic": channel_topic,
                "timestamp": match.group("ts"),
                "topic_tag": topic,
                "message_id": int(match.group("id")),
                "text": body[:2000],
            }
        )
    return out


def local_tz():
    return datetime.now().astimezone().tzinfo


def day_window(date_str: str | None) -> tuple[str, int, int, str, str]:
    tz = local_tz()
    if date_str:
        day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    else:
        now = datetime.now(tz)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        date_str = day.strftime("%Y-%m-%d")
    start = day
    end = day + timedelta(days=1)
    # If collecting "today", cap at now rather than midnight tomorrow.
    now = datetime.now(tz)
    if date_str == now.strftime("%Y-%m-%d") and now < end:
        end = now
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    return (
        date_str,
        start_epoch,
        end_epoch,
        start.isoformat(),
        end.isoformat(),
    )


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def gh_login() -> str | None:
    proc = run(["gh", "api", "user", "--jq", ".login"])
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def gh_json(args: list[str]) -> list | dict | None:
    proc = run(["gh"] + args)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def in_window(ts_text: str, start_epoch: int, end_epoch: int) -> bool:
    try:
        if ts_text.endswith("Z"):
            ts_text = ts_text[:-1] + "+00:00"
        ts = datetime.fromisoformat(ts_text).timestamp()
    except ValueError:
        return False
    return start_epoch < ts <= end_epoch


def collect_sessions(start_epoch: int) -> tuple[list[dict], str | None]:
    proc = run(
        ["python3", str(SKILL_DIR / "sessions.py"), "index-all", str(start_epoch)],
    )
    if proc.returncode != 0:
        return [], (proc.stderr or proc.stdout or "sessions index-all failed").strip()
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        sid, harness, project, n_prompts, path = parts
        rows.append(
            {
                "sid": sid,
                "harness": harness,
                "project": project,
                "n_prompts": int(n_prompts) if n_prompts.isdigit() else n_prompts,
                "path": path,
            }
        )
    return rows, None


def collect_github(login: str, start_epoch: int, end_epoch: int) -> dict:
    start_date = datetime.fromtimestamp(start_epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    end_date = datetime.fromtimestamp(end_epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    authored = gh_json(
        [
            "search",
            "prs",
            f"--author=@{login}",
            f"--updated={start_date}..{end_date}",
            "--sort",
            "updated",
            "--order",
            "asc",
            "--limit",
            "100",
            "--json",
            "number,title,repository,updatedAt,state,url,isDraft,mergedAt",
        ]
    ) or []
    reviewed = gh_json(
        [
            "search",
            "prs",
            f"--reviewed-by=@{login}",
            f"--updated={start_date}..{end_date}",
            "--sort",
            "updated",
            "--order",
            "asc",
            "--limit",
            "100",
            "--json",
            "number,title,repository,updatedAt,state,url",
        ]
    ) or []

    def slim(pr: dict) -> dict:
        repo = pr.get("repository") or {}
        name = repo.get("nameWithOwner") or repo.get("name") or "unknown"
        return {
            "repo": name,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("url"),
            "state": pr.get("state"),
            "updated_at": pr.get("updatedAt"),
            "is_draft": pr.get("isDraft"),
            "merged_at": pr.get("mergedAt"),
        }

    events = gh_json(["api", f"/users/{login}/events?per_page=100"]) or []
    pushes = []
    for ev in events:
        if ev.get("type") != "PushEvent":
            continue
        created = ev.get("created_at")
        if not created or not in_window(created, start_epoch, end_epoch):
            continue
        repo = (ev.get("repo") or {}).get("name")
        payload = ev.get("payload") or {}
        commits = payload.get("commits") or []
        pushes.append(
            {
                "repo": repo,
                "created_at": created,
                "ref": payload.get("ref"),
                "commit_messages": [c.get("message") for c in commits[:5]],
            }
        )

    return {
        "login": login,
        "authored_prs": [slim(p) for p in authored],
        "reviewed_prs": [slim(p) for p in reviewed],
        "push_events": pushes,
    }


def collect_linear(start_epoch: int, end_epoch: int) -> dict:
    proc = run(["linear", "issue", "mine", "--sort", "priority", "--no-pager"])
    if proc.returncode != 0:
        return {"issues": [], "error": (proc.stderr or proc.stdout or "linear failed").strip()}
    issues = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(RAI-\d+|\w+-\d+)\s+", line)
        if m:
            issues.append({"id": m.group(1), "line": line})
    return {"issues": issues[:50], "error": None}


def telegram_chat_ids() -> list[str]:
    if not TELEGRAM_CHATS.exists():
        return []
    ids = []
    for line in TELEGRAM_CHATS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line.split()[0])
    return ids


def collect_telegram(start_epoch: int, end_epoch: int) -> dict:
    chats = telegram_chat_ids()
    if not chats:
        return {"exports": [], "error": "no telegram chat config"}
    exports = []
    errors = []
    for chat in chats:
        out = Path(tempfile.gettempdir()) / f"work-update-day-tg-{chat}-{start_epoch}.json"
        proc = run(
            [
                "tdl",
                "chat",
                "export",
                "-c",
                chat,
                "-T",
                "time",
                "-i",
                f"{start_epoch},{end_epoch}",
                "--all",
                "--with-content",
                "--raw",
                "-o",
                str(out),
            ]
        )
        if proc.returncode != 0:
            errors.append(f"{chat}: {(proc.stderr or proc.stdout).strip()}")
            continue
        exports.append({"chat": chat, "path": str(out)})
    return {"exports": exports, "error": "; ".join(errors) if errors else None}


def collect_zulip(start_epoch: int, end_epoch: int, tmp_dir: Path) -> dict:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(SKILL_DIR / "zulip_topics.py"),
        "dump",
        str(start_epoch),
        str(end_epoch),
        "--outdir",
        str(tmp_dir),
    ]
    proc = run(cmd)

    channel_errors: list[str] = []
    topics = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 7:
            if parts[1] == "ERROR":
                channel_errors.append(line)
                continue
            topics.append(
                {
                    "channel": parts[0],
                    "topic": parts[1],
                    "messages": int(parts[2]) if parts[2].isdigit() else parts[2],
                    "first_ts": parts[3],
                    "last_ts": parts[4],
                    "coverage": parts[5],
                    "path": parts[6],
                }
            )

    user_messages = []
    for path in sorted(tmp_dir.glob("*.txt")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(errors="replace")
        channel_topic = path.stem.replace("__", " > ", 1)
        topic_name = path.stem.split("__", 1)[-1].replace("_", " ")
        user_messages.extend(parse_zulip_user_messages(text, channel_topic, topic_name))
    combined_dir = tmp_dir / "_combined"
    if combined_dir.is_dir():
        for path in sorted(combined_dir.glob("*.txt")):
            text = path.read_text(errors="replace")
            channel_topic = path.stem.replace("_", " ")
            user_messages.extend(parse_zulip_user_messages(text, channel_topic))
    user_messages.sort(key=lambda m: m["timestamp"])

    partial_error = "; ".join(channel_errors) if channel_errors else None
    if proc.returncode != 0 and not topics and not user_messages:
        err = (proc.stderr or proc.stdout or "zulip dump failed").strip()
        return {
            "dump_dir": str(tmp_dir),
            "user_messages": [],
            "topics": [],
            "channel_errors": channel_errors,
            "error": err,
        }

    return {
        "dump_dir": str(tmp_dir),
        "user_messages": user_messages,
        "topics": topics,
        "channel_errors": channel_errors,
        "error": partial_error,
    }


def collect_zulip_dms(start_epoch: int, end_epoch: int, tmp_dir: Path) -> dict:
    proc = run(
        [
            "python3",
            str(SKILL_DIR / "zulip_private.py"),
            str(start_epoch),
            str(end_epoch),
            "--outdir",
            str(tmp_dir),
        ]
    )
    if proc.returncode != 0:
        return {"dump_dir": str(tmp_dir), "error": (proc.stderr or "zulip dm dump failed").strip()}
    conversations = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) == 5:
            conversations.append(
                {"kind": parts[0], "conversation": parts[1], "messages": int(parts[2]),
                 "first_ts": parts[3], "last_ts": parts[4]}
            )
    return {"dump_dir": str(tmp_dir), "conversations": conversations}


def collect_traces(date_str: str) -> list[dict]:
    traces_root = HOME / "Github" / "traces"
    if not traces_root.is_dir():
        return []
    hits = []
    for trace in traces_root.glob("*/TRACE.md"):
        try:
            content = trace.read_text(errors="replace")
        except OSError:
            continue
        if date_str in content:
            hits.append({"path": str(trace), "slug": trace.parent.name})
    return hits


def load_existing_narrative(outdir: Path, date_str: str) -> dict | None:
    sidecar = outdir / f"{date_str}.json"
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text())
    except json.JSONDecodeError:
        return None
    return data.get("narrative")


def write_stub_md(path: Path, bundle: dict) -> None:
    ev = bundle["evidence"]
    lines = [
        f"# Work day | {bundle['date']}",
        "",
        f"Period: {bundle['period']['start_local']} through {bundle['period']['end_local']} (local).",
        f"Collected: {bundle['collected_at']}.",
        "",
        "## Evidence snapshot (machine)",
        "",
        f"- Sessions indexed: {len(ev.get('sessions', []))}",
        f"- GitHub authored PRs touched: {len(ev.get('github', {}).get('authored_prs', []))}",
        f"- GitHub PRs reviewed (search window): {len(ev.get('github', {}).get('reviewed_prs', []))}",
        f"- Zulip messages from you: {len(ev.get('zulip', {}).get('user_messages', []))}",
        f"- Linear issues (snapshot): {len(ev.get('linear', {}).get('issues', []))}",
        "",
        "Replace this stub with the save-today narrative template from the skill.",
        "",
    ]
    path.write_text("\n".join(lines))


def collect(date_str: str | None, outdir: Path, zulip_tmp: Path | None) -> int:
    if platform_darwin() is False:
        print("save-today must run from the nix-darwin machine", file=sys.stderr)
        return 1

    date_str, start_epoch, end_epoch, start_iso, end_iso = day_window(date_str)
    outdir.mkdir(parents=True, exist_ok=True)

    coverage: dict[str, bool | str | None] = {}
    errors: list[str] = []

    sessions, sess_err = collect_sessions(start_epoch)
    coverage["sessions"] = sess_err is None
    if sess_err:
        errors.append(f"sessions: {sess_err}")

    login = gh_login()
    coverage["github"] = login is not None
    github = collect_github(login, start_epoch, end_epoch) if login else {"error": "gh auth failed"}
    if not login:
        errors.append("github: gh auth failed")

    linear = collect_linear(start_epoch, end_epoch)
    coverage["linear"] = linear.get("error") is None
    if linear.get("error"):
        errors.append(f"linear: {linear['error']}")

    zdir = zulip_tmp or Path(tempfile.gettempdir()) / f"work-update-day-zulip-{date_str}"
    zulip = collect_zulip(start_epoch, end_epoch, zdir)
    coverage["zulip"] = bool(zulip.get("topics") or zulip.get("user_messages"))
    if zulip.get("error"):
        errors.append(f"zulip: {zulip['error']}")
    zulip_dms = collect_zulip_dms(start_epoch, end_epoch, zdir / "_private")
    if zulip_dms.get("error"):
        errors.append(f"zulip dms: {zulip_dms['error']}")

    telegram = collect_telegram(start_epoch, end_epoch)
    coverage["telegram"] = telegram.get("error") is None and bool(telegram.get("exports"))
    if telegram.get("error"):
        errors.append(f"telegram: {telegram['error']}")

    traces = collect_traces(date_str)

    existing_narrative = load_existing_narrative(outdir, date_str)

    bundle = {
        "date": date_str,
        "kind": "work-day",
        "period": {
            "start_local": start_iso,
            "end_local": end_iso,
            "start_epoch_exclusive": start_epoch,
            "end_epoch_inclusive": end_epoch,
        },
        "collected_at": datetime.now().astimezone().isoformat(),
        "user": {"email": USER_EMAIL, "github_login": login},
        "coverage": coverage,
        "coverage_gaps": errors,
        "evidence": {
            "sessions": sessions,
            "github": github,
            "linear": linear,
            "zulip": {
                "dump_dir": zulip.get("dump_dir"),
                "topics": zulip.get("topics", []),
                "user_messages": zulip.get("user_messages", []),
                "private": zulip_dms,
            },
            "telegram": telegram,
            "traces": traces,
        },
        "narrative": existing_narrative,
        "finalized": False,
    }

    evidence_path = outdir / f"{date_str}.evidence.json"
    sidecar_path = outdir / f"{date_str}.json"
    md_path = outdir / f"{date_str}.md"
    stub_path = outdir / f"{date_str}.stub.md"

    evidence_path.write_text(json.dumps(bundle, indent=2) + "\n")
    sidecar_path.write_text(
        json.dumps(
            {
                "date": date_str,
                "kind": "work-day",
                "period": bundle["period"],
                "collected_at": bundle["collected_at"],
                "evidence_path": str(evidence_path),
                "narrative_path": str(md_path),
                "coverage_gaps": errors,
                "finalized": False,
                "narrative": existing_narrative,
            },
            indent=2,
        )
        + "\n"
    )
    write_stub_md(stub_path, bundle)

    print(json.dumps({"date": date_str, "evidence": str(evidence_path), "sidecar": str(sidecar_path), "md": str(md_path)}, indent=2))
    if errors:
        print("coverage_gaps:", "; ".join(errors), file=sys.stderr)
    return 0


def platform_darwin() -> bool:
    import platform

    return platform.system() == "Darwin"


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily work evidence for work-update")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_collect = sub.add_parser("collect", help="Collect evidence for one local day")
    p_collect.add_argument("--date", help="YYYY-MM-DD (default: today local)")
    p_collect.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    p_collect.add_argument("--zulip-tmp", type=Path, default=None)
    args = parser.parse_args()
    if args.cmd == "collect":
        return collect(args.date, args.outdir, args.zulip_tmp)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
