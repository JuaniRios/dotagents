#!/usr/bin/env python3
"""Index and extract conversation history from every harness.

Harnesses (not models):
  claude  ~/.claude/history.jsonl + ~/.claude/projects/*/<sid>.jsonl
  codex   ~/.codex/history.jsonl + ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
  grok    ~/.grok/sessions/<urlencoded-cwd>/prompt_history.jsonl
          + <sid>/chat_history.jsonl
  agy     ~/.gemini/antigravity-cli/ (history.jsonl, conversation_summaries.db,
          conversation_metadata.json, brain/<sid>/.../transcript.jsonl)

Usage:
  sessions.py index <START_EPOCH_S>
      prints: sid|harness|project|n_prompts|path
  sessions.py extract <harness> <path>
      prints: [user|assistant] <text>
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

HOME = Path.home()
CLAUDE_HIST = HOME / ".claude" / "history.jsonl"
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CODEX_HIST = HOME / ".codex" / "history.jsonl"
CODEX_SESS = HOME / ".codex" / "sessions"
GROK_SESS = HOME / ".grok" / "sessions"
AGY_ROOT = HOME / ".gemini" / "antigravity-cli"
AGY_HIST = AGY_ROOT / "history.jsonl"
AGY_SUMMARIES = AGY_ROOT / "conversation_summaries.db"
AGY_META = AGY_ROOT / "cache" / "conversation_metadata.json"
AGY_LAST = AGY_ROOT / "cache" / "last_conversations.json"


def parse_ts(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts / 1000.0 if ts > 1e12 else ts
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return 0.0


def normalize_project(raw: str | None) -> str:
    if not raw:
        return "unknown"
    path = raw.replace("file://", "").rstrip("/")
    home = str(HOME)
    if path == home or path == "~":
        return "home"
    if "/Github/" in path:
        path = path.split("/Github/", 1)[1]
    elif path.startswith(home + "/"):
        rest = path[len(home) + 1 :]
        if not rest.startswith("Github/"):
            return "home"
        path = rest.split("Github/", 1)[-1]
    name = path.split("/")[0] if path else "unknown"
    if "-worktrees" in name:
        name = name.split("-worktrees", 1)[0]
    if name.endswith(".test-wt"):
        name = name[: -len(".test-wt")]
    return name or "unknown"


_GITHUB_REPO = re.compile(r"/Github/([^/\s\"']+)")


def infer_project_from_text(text: str) -> str:
    match = _GITHUB_REPO.search(text or "")
    if not match:
        return "unknown"
    return normalize_project("/Github/" + match.group(1))


def decode_cwd_dir(name: str) -> str:
    return urllib.parse.unquote(name)


def load_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def flatten_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in (None, "text", "input_text", "output_text"):
                    parts.append(block.get("text") or block.get("content") or "")
        return " ".join(p for p in parts if p)
    if isinstance(content, dict):
        return flatten_text(content.get("text") or content.get("content"))
    return str(content)


def unwrap_user(text: str) -> str:
    for tag in ("user_query", "USER_REQUEST"):
        open_tag = f"<{tag}>"
        close_tag = f"</{tag}>"
        if open_tag in text and close_tag in text:
            start = text.find(open_tag) + len(open_tag)
            end = text.find(close_tag, start)
            if end > start:
                return text[start:end].strip()
    return text.strip()


def skip_noise(text: str) -> bool:
    if not text:
        return True
    prefixes = (
        "<system-reminder",
        "<command-name",
        "<local-command-stdout",
        "<local-command-caveat",
        "<task-notification",
        "<user_info",
        "<recommended_plugins",
        "Caveat:",
        "This session is being continued from a previous conversation",
        "Base directory for this skill:",
    )
    stripped = text.lstrip()
    return stripped.startswith(prefixes)


def keep_messages(msgs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if len(msgs) <= 120:
        return msgs
    keep: list[tuple[str, str]] = []
    for i, msg in enumerate(msgs):
        if msg[0] == "user":
            if i and msgs[i - 1][0] == "assistant" and (not keep or keep[-1] is not msgs[i - 1]):
                keep.append(msgs[i - 1])
            keep.append(msg)
    if msgs and msgs[-1][0] == "assistant" and (not keep or keep[-1] is not msgs[-1]):
        keep.append(msgs[-1])
    return keep


def print_messages(msgs: list[tuple[str, str]]) -> None:
    for role, text in keep_messages(msgs):
        print(f"[{role}] {text[:300]}")


# --- index -----------------------------------------------------------------


def index_claude(start: float, out: dict) -> None:
    if CLAUDE_HIST.is_file():
        for entry in load_jsonl(CLAUDE_HIST):
            if parse_ts(entry.get("timestamp")) < start:
                continue
            sid = entry.get("sessionId") or "unknown"
            key = ("claude", sid)
            rec = out.setdefault(
                key,
                {
                    "harness": "claude",
                    "sid": sid,
                    "project": normalize_project(entry.get("project")),
                    "prompts": 0,
                    "path": "",
                },
            )
            rec["prompts"] += 1
            if entry.get("project") and rec["project"] == "unknown":
                rec["project"] = normalize_project(entry.get("project"))
    else:
        for path in CLAUDE_PROJECTS.glob("*/*.jsonl"):
            if path.stat().st_mtime >= start:
                sid = path.stem
                key = ("claude", sid)
                out.setdefault(
                    key,
                    {
                        "harness": "claude",
                        "sid": sid,
                        "project": normalize_project(path.parent.name),
                        "prompts": 1,
                        "path": str(path),
                    },
                )

    for rec in out.values():
        if rec["harness"] != "claude" or rec["path"]:
            continue
        matches = glob(str(CLAUDE_PROJECTS / "*" / f"{rec['sid']}.jsonl"))
        if matches:
            rec["path"] = matches[0]


def index_codex(start: float, out: dict) -> None:
    if CODEX_HIST.is_file():
        for entry in load_jsonl(CODEX_HIST):
            if parse_ts(entry.get("ts")) < start:
                continue
            sid = entry.get("session_id") or "unknown"
            key = ("codex", sid)
            rec = out.setdefault(
                key,
                {
                    "harness": "codex",
                    "sid": sid,
                    "project": "unknown",
                    "prompts": 0,
                    "path": "",
                },
            )
            rec["prompts"] += 1

    if not CODEX_SESS.is_dir():
        return
    for path in CODEX_SESS.glob("*/*/*/rollout-*.jsonl"):
        name = path.name
        # filename: rollout-<iso>-<uuid>.jsonl ; uuid is last 5 hyphen groups
        parts = name[len("rollout-") : -len(".jsonl")].split("-")
        sid = "-".join(parts[-5:]) if len(parts) >= 5 else path.stem
        fresh = path.stat().st_mtime >= start
        key = ("codex", sid)
        if key not in out and not fresh:
            continue
        rec = out.setdefault(
            key,
            {
                "harness": "codex",
                "sid": sid,
                "project": "unknown",
                "prompts": 1 if fresh else 0,
                "path": str(path),
            },
        )
        rec["path"] = rec["path"] or str(path)
        if rec["project"] == "unknown":
            for entry in load_jsonl(path):
                if entry.get("type") == "session_meta":
                    rec["project"] = normalize_project(
                        (entry.get("payload") or {}).get("cwd")
                    )
                    break


def index_grok(start: float, out: dict) -> None:
    if not GROK_SESS.is_dir():
        return
    for hist in GROK_SESS.glob("*/prompt_history.jsonl"):
        cwd = decode_cwd_dir(hist.parent.name)
        project = normalize_project(cwd)
        if hist.is_file():
            for entry in load_jsonl(hist):
                if parse_ts(entry.get("timestamp")) < start:
                    continue
                sid = entry.get("session_id") or "unknown"
                key = ("grok", sid)
                rec = out.setdefault(
                    key,
                    {
                        "harness": "grok",
                        "sid": sid,
                        "project": project,
                        "prompts": 0,
                        "path": str(hist.parent / sid / "chat_history.jsonl"),
                    },
                )
                rec["prompts"] += 1
        # mtime fallback when prompt_history is missing or stale
        for chat in hist.parent.glob("*/chat_history.jsonl"):
            sid = chat.parent.name
            key = ("grok", sid)
            if key in out:
                out[key]["path"] = str(chat)
                continue
            summary = chat.parent / "summary.json"
            stamp = 0.0
            if summary.is_file():
                try:
                    info = json.loads(summary.read_text())
                    stamp = max(
                        parse_ts(info.get("updated_at")),
                        parse_ts(info.get("last_active_at")),
                        parse_ts(info.get("created_at")),
                    )
                    cwd = (info.get("info") or {}).get("cwd") or cwd
                    project = normalize_project(cwd)
                except (OSError, json.JSONDecodeError):
                    stamp = chat.stat().st_mtime
            else:
                stamp = chat.stat().st_mtime
            if stamp >= start:
                out[key] = {
                    "harness": "grok",
                    "sid": sid,
                    "project": project,
                    "prompts": 1,
                    "path": str(chat),
                }


def _agy_workspaces() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if AGY_LAST.is_file():
        try:
            data = json.loads(AGY_LAST.read_text())
            if isinstance(data, dict):
                for cwd, sid in data.items():
                    if isinstance(sid, str):
                        mapping[sid] = cwd
        except (OSError, json.JSONDecodeError):
            pass
    if AGY_META.is_file():
        try:
            data = json.loads(AGY_META.read_text())
            convs = data.get("conversations", data) if isinstance(data, dict) else {}
            if isinstance(convs, dict):
                for sid, rec in convs.items():
                    summary = rec.get("summary") if isinstance(rec, dict) else {}
                    uris = (summary or {}).get("WorkspaceURIs") or rec.get(
                        "workspace_uris"
                    )
                    if uris:
                        mapping.setdefault(sid, uris[0])
        except (OSError, json.JSONDecodeError):
            pass
    if AGY_SUMMARIES.is_file():
        try:
            con = sqlite3.connect(f"file:{AGY_SUMMARIES}?mode=ro", uri=True)
            for sid, uris in con.execute(
                "select conversation_id, workspace_uris from conversation_summaries"
            ):
                if uris:
                    try:
                        parsed = json.loads(uris)
                        if parsed:
                            mapping.setdefault(sid, parsed[0])
                    except json.JSONDecodeError:
                        mapping.setdefault(sid, uris)
            con.close()
        except sqlite3.Error:
            pass
    return mapping


def index_agy(start: float, out: dict) -> None:
    workspaces = _agy_workspaces()

    if AGY_HIST.is_file():
        for entry in load_jsonl(AGY_HIST):
            if parse_ts(entry.get("timestamp")) < start:
                continue
            sid = entry.get("conversationId") or "unknown"
            if sid == "unknown":
                continue
            key = ("agy", sid)
            rec = out.setdefault(
                key,
                {
                    "harness": "agy",
                    "sid": sid,
                    "project": normalize_project(
                        entry.get("workspace") or workspaces.get(sid)
                    ),
                    "prompts": 0,
                    "path": "",
                },
            )
            rec["prompts"] += 1

    if AGY_SUMMARIES.is_file():
        try:
            con = sqlite3.connect(f"file:{AGY_SUMMARIES}?mode=ro", uri=True)
            for sid, last_in, last_mod, uris, steps in con.execute(
                "select conversation_id, last_user_input_time, "
                "last_modified_time, workspace_uris, step_count "
                "from conversation_summaries"
            ):
                stamp = max(parse_ts(last_in), parse_ts(last_mod))
                if stamp < start and ("agy", sid) not in out:
                    continue
                key = ("agy", sid)
                cwd = workspaces.get(sid)
                if uris:
                    try:
                        parsed = json.loads(uris)
                        if parsed:
                            cwd = parsed[0]
                    except json.JSONDecodeError:
                        cwd = cwd or uris
                rec = out.setdefault(
                    key,
                    {
                        "harness": "agy",
                        "sid": sid,
                        "project": normalize_project(cwd),
                        "prompts": int(steps or 1),
                        "path": "",
                    },
                )
                if rec["project"] == "unknown":
                    rec["project"] = normalize_project(cwd)
            con.close()
        except sqlite3.Error:
            pass

    if AGY_META.is_file():
        try:
            data = json.loads(AGY_META.read_text())
            convs = data.get("conversations", {}) if isinstance(data, dict) else {}
            for sid, rec in convs.items():
                stamp = parse_ts(rec.get("last_modified_time") if isinstance(rec, dict) else None)
                if stamp < start and ("agy", sid) not in out:
                    continue
                summary = rec.get("summary") if isinstance(rec, dict) else {}
                uris = (summary or {}).get("WorkspaceURIs")
                cwd = uris[0] if uris else workspaces.get(sid)
                out.setdefault(
                    ("agy", sid),
                    {
                        "harness": "agy",
                        "sid": sid,
                        "project": normalize_project(cwd),
                        "prompts": 1,
                        "path": "",
                    },
                )
        except (OSError, json.JSONDecodeError):
            pass

    brain = AGY_ROOT / "brain"
    if brain.is_dir():
        for transcript in brain.glob("*/.system_generated/logs/transcript.jsonl"):
            sid = transcript.parent.parent.parent.name
            key = ("agy", sid)
            stamp = 0.0
            for entry in load_jsonl(transcript):
                stamp = max(stamp, parse_ts(entry.get("created_at")))
            if stamp < start and key not in out:
                continue
            rec = out.setdefault(
                key,
                {
                    "harness": "agy",
                    "sid": sid,
                    "project": normalize_project(workspaces.get(sid)),
                    "prompts": 1,
                    "path": str(transcript),
                },
            )
            rec["path"] = str(transcript)
            if rec["prompts"] == 0:
                rec["prompts"] = 1
            if rec["project"] == "unknown":
                snippet = transcript.read_text(errors="replace")[:8000]
                inferred = infer_project_from_text(snippet)
                if inferred != "unknown":
                    rec["project"] = inferred

    for rec in list(out.values()):
        if rec["harness"] != "agy" or rec["path"]:
            continue
        candidate = (
            AGY_ROOT
            / "brain"
            / rec["sid"]
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        if candidate.is_file():
            rec["path"] = str(candidate)
        else:
            db = AGY_ROOT / "conversations" / f"{rec['sid']}.db"
            if db.is_file():
                rec["path"] = str(db)


def cmd_index(start: float) -> None:
    out: dict[tuple[str, str], dict] = {}
    index_claude(start, out)
    index_codex(start, out)
    index_grok(start, out)
    index_agy(start, out)
    rows = sorted(out.values(), key=lambda r: (r["project"], r["harness"], r["sid"]))
    for rec in rows:
        if rec["prompts"] <= 0 and not rec["path"]:
            continue
        print(
            f"{rec['sid']}|{rec['harness']}|{rec['project']}|"
            f"{rec['prompts']}|{rec['path']}"
        )


# --- extract ---------------------------------------------------------------


def extract_claude(path: Path) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    for entry in load_jsonl(path):
        if entry.get("isSidechain"):
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        text = flatten_text((entry.get("message") or {}).get("content"))
        text = unwrap_user(text)
        if skip_noise(text):
            continue
        msgs.append((entry["type"], text[:300]))
    return msgs


def extract_codex(path: Path) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    for entry in load_jsonl(path):
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload") or {}
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in ("user", "assistant"):
            continue
        text = unwrap_user(flatten_text(payload.get("content")))
        if skip_noise(text):
            continue
        msgs.append((role, text[:300]))
    return msgs


def extract_grok(path: Path) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    for entry in load_jsonl(path):
        kind = entry.get("type")
        if kind not in ("user", "assistant"):
            continue
        if entry.get("synthetic_reason") in (
            "compaction_meta",
            "system_reminder",
            "compaction",
        ):
            continue
        text = unwrap_user(flatten_text(entry.get("content")))
        if skip_noise(text):
            continue
        msgs.append((kind, text[:300]))
    return msgs


def extract_agy_transcript(path: Path) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    for entry in load_jsonl(path):
        kind = entry.get("type")
        source = entry.get("source")
        text = unwrap_user(flatten_text(entry.get("content")))
        if skip_noise(text):
            continue
        if kind == "USER_INPUT" or source == "USER_EXPLICIT":
            msgs.append(("user", text[:300]))
        elif kind in (
            "PLANNER_RESPONSE",
            "AGENT_RESPONSE",
            "MODEL_RESPONSE",
            "FINAL_RESPONSE",
        ) or source == "MODEL":
            if text:
                msgs.append(("assistant", text[:300]))
    return msgs


def extract_agy_sqlite(path: Path) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = con.execute(
            "select step_type, step_payload from steps order by idx"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return msgs
    for step_type, payload in rows:
        if not payload:
            continue
        chunks: list[str] = []
        cur: list[str] = []
        for byte in payload:
            if 32 <= byte < 127:
                cur.append(chr(byte))
            else:
                if len(cur) >= 24:
                    chunks.append("".join(cur))
                cur = []
        if len(cur) >= 24:
            chunks.append("".join(cur))
        text = unwrap_user("\n".join(chunks))
        if skip_noise(text):
            continue
        # 14 = user-ish, 15/2 = model-ish in observed DBs
        role = "user" if step_type in (14, 8) else "assistant"
        if step_type in (14, 15, 2, 8) and text:
            msgs.append((role, text[:300]))
    return msgs


def cmd_extract(harness: str, path_str: str) -> None:
    path = Path(os.path.expanduser(path_str))
    if not path.exists():
        return
    if harness == "claude":
        msgs = extract_claude(path)
    elif harness == "codex":
        msgs = extract_codex(path)
    elif harness == "grok":
        msgs = extract_grok(path)
    elif harness == "agy":
        if path.suffix == ".db":
            msgs = extract_agy_sqlite(path)
        else:
            msgs = extract_agy_transcript(path)
    else:
        sys.stderr.write(f"unknown harness: {harness}\n")
        sys.exit(2)
    print_messages(msgs)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("index", "extract"):
        sys.stderr.write(__doc__ or "")
        return 2
    if argv[1] == "index":
        if len(argv) < 3:
            sys.stderr.write("index needs START_EPOCH_S\n")
            return 2
        cmd_index(float(argv[2]))
        return 0
    if len(argv) < 4:
        sys.stderr.write("extract needs <harness> <path>\n")
        return 2
    cmd_extract(argv[2], argv[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
