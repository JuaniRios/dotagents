#!/usr/bin/env python3
"""Dump Juan's Zulip DMs and @-mentions inside a time window.

zulipctl cannot narrow by `is:dm` or `is:mentioned`, or stop at a timestamp,
so this pages the REST API directly. Read-only.

Usage:
  zulip_private.py <START_EPOCH_S> <END_EPOCH_S> --outdir DIR [--kind dm|mentioned ...]

Writes:
  DIR/<kind>.jsonl                  one message per line: id, ts, sender, conversation, text
  DIR/<kind>/<conversation>.txt     chronological transcript per DM partner set or channel/topic
stdout: kind|conversation|n|first_ts|last_ts

Uses ~/.zuliprc-personal (Juan's human account) unless --config is passed:
DMs are only visible to their participants.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".zuliprc-personal"
PAGE_LIMIT = 1000
MAX_PAGES = 50


def zulip_get(config: Path, endpoint: str, params: dict) -> dict:
    parser = configparser.ConfigParser()
    if not parser.read(config):
        raise RuntimeError(f"Zulip credentials not found at {config}")
    api = parser["api"]
    token = base64.b64encode(f"{api['email']}:{api['key']}".encode()).decode()
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{api['site'].rstrip('/')}/api/v1/{endpoint}?{query}",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {endpoint}: HTTP {exc.code}") from exc
    if data.get("result") == "error":
        raise RuntimeError(data.get("msg") or "zulip error")
    return data


def clean(raw: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def conversation(msg: dict, me: str) -> str:
    if msg["type"] == "stream":
        return f"{msg['display_recipient']} > {msg['subject']}"
    others = sorted(r["full_name"] for r in msg["display_recipient"] if r["email"] != me)
    return "dm: " + (", ".join(others) or "self")


def fetch(config: Path, kind: str, start: int, end: int) -> list[dict]:
    narrow = json.dumps([{"operator": "is", "operand": kind}])
    anchor: int | str = "newest"
    rows: list[dict] = []
    for _ in range(MAX_PAGES):
        page = zulip_get(
            config,
            "messages",
            {
                "anchor": anchor,
                "num_before": PAGE_LIMIT,
                "num_after": 0,
                "narrow": narrow,
                "apply_markdown": "true",
                "include_anchor": "true" if anchor == "newest" else "false",
            },
        )
        messages = page.get("messages", [])
        rows.extend(m for m in messages if start < m["timestamp"] <= end)
        if page.get("found_oldest") or not messages or messages[0]["timestamp"] <= start:
            break
        anchor = messages[0]["id"]
    else:
        print(f"warning: {kind} hit MAX_PAGES; window may be truncated", file=sys.stderr)
    return sorted({m["id"]: m for m in rows}.values(), key=lambda m: m["id"])


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--kind", action="append", choices=["dm", "mentioned"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    me = zulip_get(args.config, "users/me", {})["email"]
    for kind in args.kind or ["dm", "mentioned"]:
        messages = fetch(args.config, kind, args.start, args.end)
        (args.outdir / kind).mkdir(parents=True, exist_ok=True)
        grouped: dict[str, list[dict]] = {}
        with (args.outdir / f"{kind}.jsonl").open("w") as out:
            for m in messages:
                row = {
                    "id": m["id"],
                    "ts": fmt(m["timestamp"]),
                    "sender": m["sender_full_name"],
                    "from_me": m["sender_email"] == me,
                    "conversation": conversation(m, me),
                    "text": clean(m["content"]),
                }
                out.write(json.dumps(row) + "\n")
                grouped.setdefault(row["conversation"], []).append(row)
        for name, rows in sorted(grouped.items()):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
            with (args.outdir / kind / f"{safe}.txt").open("w") as out:
                for r in rows:
                    out.write(f"[{r['ts']}] {r['sender']} (#{r['id']}): {r['text']}\n")
            print(f"{kind}|{name}|{len(rows)}|{rows[0]['ts']}|{rows[-1]['ts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
