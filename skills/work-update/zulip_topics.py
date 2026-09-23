#!/usr/bin/env python3
"""Inventory Zulip topics and dump every in-window message.

Usage:
  zulip_topics.py inventory [--channel NAME ...]
      prints: channel|topic|max_id

  zulip_topics.py dump <START_EPOCH_S> <END_EPOCH_S> --outdir DIR [--channel NAME ...] [--topic NAME ...]
      pages every topic to completion and writes:
        DIR/_inventory.tsv
        DIR/_manifest.tsv
        DIR/<channel>__<topic>.txt     full cleaned in-window transcript
        DIR/_combined/<channel>.txt    chronological dump of that channel
      stdout: channel|topic|n|first_ts|last_ts|coverage|path

Default channels: every channel the account can see (subscribed or not).
Always uses ~/.zuliprc-personal (Juan's account) unless --config is passed.
Juan-Bot is only for sending messages to Juan, never for reading.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import html
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".zuliprc-personal"
PAGE_LIMIT = 1000
MAX_PAGES = 100


def load_zuliprc(config: Path) -> tuple[str, str]:
    parser = configparser.ConfigParser()
    if not parser.read(config):
        raise RuntimeError(f"Zulip credentials not found at {config}")
    section = parser["api"]
    site = section["site"].rstrip("/")
    email = section["email"]
    api_key = section["key"]
    token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
    return site, token


def zulip_get(config: Path, endpoint: str, params: dict) -> dict:
    site, token = load_zuliprc(config)
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{site}/api/v1/{endpoint.lstrip('/')}?{query}",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {endpoint}: HTTP {exc.code}") from exc
    if isinstance(data, dict) and data.get("result") == "error":
        raise RuntimeError(data.get("msg") or "zulip error")
    return data


def zulipctl(config: Path, *args: str) -> dict:
    cmd = ["zulipctl", "--config", str(config), "--compact", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"{' '.join(cmd)}: {err}")
    if not proc.stdout.strip():
        raise RuntimeError(f"{' '.join(cmd)}: empty stdout")
    data = json.loads(proc.stdout)
    if isinstance(data, dict) and data.get("result") == "error":
        raise RuntimeError(data.get("msg") or json.dumps(data))
    return data


def clean_html(raw: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?i)</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_name(value: str) -> str:
    value = value.strip() or "(no-topic)"
    value = re.sub(r"[^\w.+-]+", "_", value, flags=re.UNICODE)
    return (value[:120] or "topic").strip("_") or "topic"


def fmt_ts(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def all_channels(config: Path) -> list[str]:
    data = zulipctl(config, "channels")
    return sorted(s["name"] for s in data.get("streams") or [])


def list_topics(config: Path, channel: str) -> list[dict]:
    data = zulipctl(config, "topics", channel)
    return data.get("topics") or []


def fetch_page(
    config: Path, channel: str, topic: str, anchor: str | None
) -> dict:
    if topic == "":
        params = {
            "num_before": str(PAGE_LIMIT),
            "num_after": "0",
            "narrow": json.dumps(
                [
                    {"operator": "channel", "operand": channel},
                    {"operator": "topic", "operand": ""},
                ]
            ),
            "allow_empty_topic_name": "true",
        }
        params["anchor"] = anchor if anchor is not None else "newest"
        return zulip_get(config, "messages", params)
    args = [
        "messages",
        "--channel",
        channel,
        "--topic",
        topic,
        "--limit",
        str(PAGE_LIMIT),
    ]
    if anchor is not None:
        args.extend(["--anchor", anchor])
    return zulipctl(config, *args)


def dump_topic(
    config: Path,
    channel: str,
    topic: str,
    start: int,
    end: int,
) -> tuple[list[dict], str]:
    """Return (in-window messages, coverage)."""
    seen: set[int] = set()
    kept: list[dict] = []
    coverage = "ok"
    anchor: str | None = None
    newest_at_or_before_start = False

    for _ in range(MAX_PAGES):
        try:
            page = fetch_page(config, channel, topic, anchor)
        except RuntimeError as exc:
            return kept, f"error:{exc}"

        messages = page.get("messages") or []
        new_messages = [m for m in messages if m.get("id") not in seen]
        if not new_messages:
            if page.get("found_oldest"):
                break
            coverage = "stalled"
            break

        for msg in new_messages:
            seen.add(msg["id"])
            ts = int(msg["timestamp"])
            if ts > start and ts <= end:
                kept.append(msg)

        timestamps = [int(m["timestamp"]) for m in new_messages]
        oldest_id = min(m["id"] for m in new_messages)
        if max(timestamps) <= start:
            newest_at_or_before_start = True
            break
        if page.get("found_oldest"):
            break
        if page.get("history_limited") and min(timestamps) > start:
            coverage = "history-limited"
        anchor = str(oldest_id)
    else:
        coverage = "truncated"

    if newest_at_or_before_start and not kept:
        coverage = "ok"
    kept.sort(key=lambda m: (int(m["timestamp"]), int(m["id"])))
    return kept, coverage


def write_transcript(
    path: Path,
    channel: str,
    topic: str,
    start: int,
    end: int,
    messages: list[dict],
    coverage: str,
) -> None:
    lines = [
        f"channel: {channel}",
        f"topic: {topic or '(no topic)'}",
        f"n: {len(messages)}",
        f"window: {start} < ts <= {end}",
        f"coverage: {coverage}",
        "",
    ]
    for msg in messages:
        sender = msg.get("sender_full_name") or "unknown"
        email = msg.get("sender_email") or ""
        who = f"{sender} <{email}>" if email else sender
        body = clean_html(msg.get("content") or "")
        lines.append(
            f"[{fmt_ts(int(msg['timestamp']))}] {who} id={msg['id']}"
        )
        lines.append(body)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_combined(path: Path, channel: str, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda m: (int(m["timestamp"]), int(m["id"])))
    lines = [f"channel: {channel}", f"n: {len(rows)}", ""]
    for msg in rows:
        topic = msg.get("subject") or "(no topic)"
        sender = msg.get("sender_full_name") or "unknown"
        email = msg.get("sender_email") or ""
        who = f"{sender} <{email}>" if email else sender
        body = clean_html(msg.get("content") or "")
        lines.append(
            f"[{fmt_ts(int(msg['timestamp']))}] #{topic} {who} id={msg['id']}"
        )
        lines.append(body)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def cmd_inventory(config: Path, channels: list[str]) -> int:
    for channel in channels:
        try:
            topics = list_topics(config, channel)
        except RuntimeError as exc:
            print(f"{channel}|ERROR|{exc}", file=sys.stderr)
            continue
        for topic in topics:
            name = topic.get("name") or ""
            print(f"{channel}|{name}|{topic.get('max_id', '')}")
    return 0


def cmd_dump(
    config: Path,
    channels: list[str],
    start: int,
    end: int,
    outdir: Path,
    only_topics: list[str] | None,
) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "_combined").mkdir(exist_ok=True)
    inventory_lines = ["channel\ttopic\tmax_id"]
    manifest_lines = ["channel\ttopic\tn\tfirst_ts\tlast_ts\tcoverage\tpath"]
    status = 0

    for channel in channels:
        combined: list[dict] = []
        try:
            topics = list_topics(config, channel)
        except RuntimeError as exc:
            print(f"{channel}|ERROR|0||||error:{exc}|", file=sys.stderr)
            status = 1
            continue
        if only_topics is not None:
            wanted = set(only_topics)
            topics = [t for t in topics if (t.get("name") or "") in wanted]
        for topic in topics:
            name = topic.get("name") or ""
            inventory_lines.append(f"{channel}\t{name}\t{topic.get('max_id', '')}")
            messages, coverage = dump_topic(config, channel, name, start, end)
            combined.extend(messages)
            rel = f"{safe_name(channel)}__{safe_name(name)}.txt"
            path = outdir / rel
            write_transcript(path, channel, name, start, end, messages, coverage)
            first_ts = messages[0]["timestamp"] if messages else ""
            last_ts = messages[-1]["timestamp"] if messages else ""
            if coverage not in {"ok"}:
                status = 1
            manifest_lines.append(
                f"{channel}\t{name}\t{len(messages)}\t{first_ts}\t{last_ts}\t{coverage}\t{path}"
            )
            print(
                f"{channel}|{name}|{len(messages)}|{first_ts}|{last_ts}|{coverage}|{path}"
            )
        write_combined(outdir / "_combined" / f"{safe_name(channel)}.txt", channel, combined)

    (outdir / "_inventory.tsv").write_text("\n".join(inventory_lines) + "\n")
    (outdir / "_manifest.tsv").write_text("\n".join(manifest_lines) + "\n")
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("inventory")
    inv.add_argument("--channel", action="append", dest="channels")

    dump = sub.add_parser("dump")
    dump.add_argument("start", type=int)
    dump.add_argument("end", type=int)
    dump.add_argument("--outdir", type=Path, required=True)
    dump.add_argument("--channel", action="append", dest="channels")
    dump.add_argument("--topic", action="append", dest="topics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    channels = args.channels or all_channels(args.config)
    if args.cmd == "inventory":
        return cmd_inventory(args.config, channels)
    if args.start >= args.end:
        print("START_EPOCH_S must be < END_EPOCH_S", file=sys.stderr)
        return 2
    return cmd_dump(
        args.config,
        channels,
        args.start,
        args.end,
        args.outdir,
        args.topics,
    )


if __name__ == "__main__":
    raise SystemExit(main())
