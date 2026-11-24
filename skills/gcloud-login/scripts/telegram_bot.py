#!/usr/bin/env python3
"""Telegram transport for the login helpers: a drop-in for ZulipBot + deleter.

Uses the bot in ~/.config/telegram-bot.env (TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID). The chat must be a private chat with one person, so only
that person can reply. Telegram bot chats are not end-to-end encrypted; the
helpers rely on short-lived, single-use codes and delete every message of an
exchange (bots may delete incoming messages in private chats for 48 hours).

The token goes only in the HTTPS request path, never in argv, output, or logs.

Reading: Juan-Bot (the juan-bot service on juan-dev-server) is the only
program that reads this bot with getUpdates, because two readers of one bot
cut each other off and lose each other's messages. These helpers get Juan's
replies from Juan-Bot's inbox socket instead (see nix-darwin-config
modules/nixos/juan-bot/jb_inbox.py): replies to the helper's own messages,
and the code or word it waits for. They still send and delete their own
messages directly. The socket is found at $JB_INBOX_SOCKET (daily-logins
forwards it to the Mac over its SSH session), else at INBOX_SOCKET on the
server, else (on the Mac) through an `ssh -L` forward to $JB_INBOX_SSH
(default juan-dev-server). If none answers, the helper says so on stderr and
reads the bot itself, as before; on the server it touches DIRECT_MARKER so
Juan-Bot treats that time as blind.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re
import atexit
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional
import urllib.error
import urllib.request

DEFAULT_ENV_FILE = "~/.config/telegram-bot.env"
LONG_POLL_SECONDS = 20
INBOX_SOCKET = "/var/lib/juan-bot/run/inbox.sock"
DIRECT_MARKER = "~/.cache/telegram-direct-read"
INBOX_RETRY_SECONDS = 60  # an inbox that fails this long (Juan-Bot restarting) makes the helper read directly
INBOX_TTL = 13 * 3600
LABELS = {"daily_logins.py": "daily logins", "zulip_remote_login.py": "gcloud login",
          "zulip_ops_client_login.py": "ops client sign-in", "telegram_bot.py": "inbox test"}


class TelegramError(RuntimeError):
    """A safe-to-display Telegram failure. Never carries the token."""


def load_env(path: str = DEFAULT_ENV_FILE) -> tuple[str, int]:
    file = Path(path).expanduser()
    if not file.is_file():
        raise TelegramError("Telegram bot credentials are missing")
    if file.stat().st_mode & 0o077:
        raise TelegramError("Telegram bot credential permissions are too broad")
    values = {}
    for line in file.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(?:export\s+)?(\w+)=[\"']?([^\"'\s]*)", line)
        if match:
            values[match.group(1)] = match.group(2)
    try:
        return values["TELEGRAM_BOT_TOKEN"], int(values["TELEGRAM_CHAT_ID"])
    except (KeyError, ValueError) as error:
        raise TelegramError("Telegram bot credentials are invalid") from error


def to_html(markdown: str) -> str:
    """Converts the helpers' small Markdown subset (**b**, `code`, [t](url)) to Telegram HTML."""
    text = html.escape(markdown, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


class InboxError(TelegramError):
    """Juan-Bot's inbox did not answer or refused the call."""


class Inbox:
    """A session on Juan-Bot's inbox: only the replies Juan-Bot routed to this session come back."""

    def __init__(self, path: str, label: str) -> None:
        self.path = path
        self.label = label
        self.watched = set()  # type: set[int]
        self.words = set()  # type: set[str]
        self.code = False
        self.session = ""
        self.open()

    def _raw(self, op: str, timeout: float = 10, **args: Any) -> Any:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(self.path)
            sock.sendall((json.dumps({"op": op, "args": args}) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
            res = json.loads(buf)
        except (OSError, ValueError) as error:
            raise InboxError(f"Juan-Bot inbox {op} failed ({type(error).__name__})") from None
        finally:
            sock.close()
        if not res.get("ok"):
            raise InboxError(f"Juan-Bot inbox {op}: {res.get('error')}")
        return res["result"]

    def open(self) -> None:
        self.session = self._raw("open", label=self.label, ttl=INBOX_TTL)["session"]
        if self.watched:
            self._raw("watch", session=self.session, message_ids=sorted(self.watched))
        if self.words or self.code:
            self._raw("want", session=self.session, words=sorted(self.words), code=self.code)

    def call(self, op: str, timeout: float = 10, **args: Any) -> Any:
        try:
            return self._raw(op, timeout, session=self.session, **args)
        except InboxError as error:
            if "unknown session" not in str(error):
                raise
            self.open()  # expired (idle while another helper ran) or Juan-Bot lost it: open again
            return self._raw(op, timeout, session=self.session, **args)

    def watch(self, message_id: int) -> None:
        self.watched.add(message_id)
        self.call("watch", message_ids=[message_id])

    def want(self, words: set, code: bool) -> None:
        if (set(words), code) != (self.words, self.code):
            self.words, self.code = set(words), code
            self.call("want", words=sorted(words), code=code)

    def pull(self, after: int, wait: float) -> list:
        wait = max(0.0, min(wait, 50.0))
        return self.call("pull", timeout=wait + 15, after=after, wait=wait)["messages"]

    def close(self) -> None:
        try:
            self.call("close")
        except InboxError:
            pass


def _ssh_forward() -> Optional[str]:
    """On the Mac: forward Juan-Bot's inbox socket from the server over SSH. None if that fails."""
    host = os.environ.get("JB_INBOX_SSH", "juan-dev-server")
    local = os.path.join(tempfile.mkdtemp(prefix="jb-inbox-"), "inbox.sock")
    try:
        proc = subprocess.Popen(
            ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ExitOnForwardFailure=yes",
             "-L", f"{local}:{INBOX_SOCKET}", host],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    atexit.register(proc.terminate)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and proc.poll() is None:
        if os.path.exists(local):
            return local
        time.sleep(0.2)
    proc.terminate()
    return None


def connect_inbox(label: str) -> tuple:
    """(Inbox, "") when Juan-Bot's inbox answers, else (None, why)."""
    path = os.environ.get("JB_INBOX_SOCKET") or (INBOX_SOCKET if os.path.exists(INBOX_SOCKET) else "")
    if not path and sys.platform == "darwin":
        path = _ssh_forward() or ""
        if not path:
            return None, "no SSH forward to Juan-Bot"
    if not path:
        return None, "no inbox socket on this host"
    try:
        return Inbox(path, label), ""
    except InboxError as error:
        return None, str(error)


def touch_direct_marker() -> None:
    marker = Path(DIRECT_MARKER).expanduser()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass


class TelegramBot:
    """Sends to one private chat, reads that person's replies, deletes messages.

    Implements the interface the helpers use for Zulip: connectivity_gate, dm,
    poll_code, code_reply_ids, replies_after, and delete. Telegram message IDs
    grow within a chat for both sides, so "after message N" works as on Zulip.
    """

    _inbox = None  # type: Optional[Inbox]
    _inbox_failing = None  # type: Optional[float]

    def __init__(self, env_file: str = DEFAULT_ENV_FILE, inbox: bool = True, label: str = "") -> None:
        self._token, self.chat_id = load_env(env_file)
        self._offset = None  # type: Optional[int]
        self._seen = {}  # type: dict[int, str]  message_id -> text, from the person only
        self._inbox = None  # type: Optional[Inbox]
        self._inbox_failing = None  # type: Optional[float]
        if inbox:
            name = os.path.basename(sys.argv[0] or "")
            self._inbox, why = connect_inbox(label or LABELS.get(name, name or "script"))
            if self._inbox:
                atexit.register(self._inbox.close)
                print("Reading Juan's Telegram replies through Juan-Bot's inbox.", file=sys.stderr, flush=True)
            else:
                self._go_direct(why)

    def _go_direct(self, why: str) -> None:
        self._inbox = None
        print(f"Juan-Bot's inbox is not reachable ({why}); reading Telegram directly. Juan-Bot treats this "
              "time as blind, and a reply may reach only one of us.", file=sys.stderr, flush=True)

    @property
    def via_inbox(self) -> bool:
        return self._inbox is not None

    def _watch(self, message_id: int) -> None:
        if self._inbox:
            try:
                self._inbox.watch(message_id)
            except InboxError as error:
                self._go_direct(str(error))

    def _want(self, words: set, code: bool) -> None:
        if self._inbox:
            try:
                self._inbox.want(words, code)
            except InboxError as error:
                self._go_direct(str(error))

    def _call(self, method: str, http_timeout: float = 30, **params: Any) -> Any:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=http_timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                description = json.loads(error.read()).get("description", "")
            except (OSError, ValueError):
                description = ""
            raise TelegramError(f"Telegram {method} failed: {error.code} {description}".strip()) from None
        except (OSError, ValueError):
            raise TelegramError(f"Telegram {method} failed") from None
        if not result.get("ok"):
            raise TelegramError(f"Telegram {method} did not succeed")
        return result["result"]

    def connectivity_gate(self) -> None:
        chat = self._call("getChat", chat_id=self.chat_id)
        if chat.get("type") != "private" or chat.get("id") != self.chat_id:
            raise TelegramError("The Telegram chat is not a private chat with one person")

    def dm(self, content: str, *, markdown: bool = True) -> int:
        result = self._call(
            "sendMessage",
            chat_id=self.chat_id,
            text=to_html(content) if markdown else html.escape(content, quote=False),
            parse_mode="HTML",
            # A preview would make Telegram fetch the sign-in URL.
            link_preview_options={"is_disabled": True},
        )
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramError("Telegram did not return a message ID")
        self._watch(message_id)
        return message_id

    def send_html(self, text: str) -> int:
        result = self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML",
                            link_preview_options={"is_disabled": True})
        self._watch(int(result["message_id"]))
        return int(result["message_id"])

    def _pull(self, wait: float = 0) -> None:
        """Reads the person's new messages: from Juan-Bot's inbox, else from Telegram directly."""
        while self._inbox:
            try:
                after = max(self._seen, default=0)
                for message_id, text in self._inbox.pull(after, wait):
                    self._seen[int(message_id)] = str(text)
                self._inbox_failing = None
                return
            except InboxError as error:
                if self._inbox_failing is None:
                    self._inbox_failing = time.monotonic()
                if time.monotonic() - self._inbox_failing >= INBOX_RETRY_SECONDS:
                    self._go_direct(str(error))
                    break
                time.sleep(3)  # Juan-Bot may be restarting
        self._pull_direct(wait)

    def _pull_direct(self, wait: float = 0) -> None:
        """Reads new updates, keeps the person's text messages, confirms the rest."""
        touch_direct_marker()
        params = {"timeout": int(wait), "allowed_updates": ["message"]}
        if self._offset is not None:
            params["offset"] = self._offset
        updates = self._call("getUpdates", http_timeout=wait + 30, **params)
        for update in updates:
            self._offset = int(update["update_id"]) + 1
            message = update.get("message") or {}
            sender = (message.get("from") or {}).get("id")
            chat = (message.get("chat") or {}).get("id")
            if chat == self.chat_id and sender == self.chat_id and "text" in message:
                self._seen[int(message["message_id"])] = str(message["text"])
        # The next call's offset confirms these updates. A later process may see
        # unconfirmed ones again, but every caller only takes messages newer
        # than its own request, so old replies are never used.

    def replies_after(self, after_message_id: Optional[int]) -> list[tuple[int, str]]:
        if after_message_id is None:
            return []
        self._want(set(), True)  # every caller looks for a pasted code or redirect URL
        self._pull()
        return sorted((mid, text) for mid, text in self._seen.items() if mid > after_message_id)

    def _code_only(self, after_message_id: int) -> list[tuple[int, str]]:
        out = []
        for mid, text in self.replies_after(after_message_id):
            match = re.fullmatch(r"\s*(\S{16,2048})\s*", text)
            if match:
                out.append((mid, match.group(1)))
        return out

    def poll_code(self, after_message_id: int) -> Optional[tuple[int, str]]:
        candidates = self._code_only(after_message_id)
        return candidates[-1] if candidates else None

    def code_reply_ids(self, after_message_id: int) -> list[int]:
        return [mid for mid, _ in self._code_only(after_message_id)]

    def delete(self, message_id: int) -> None:
        self._call("deleteMessage", chat_id=self.chat_id, message_id=message_id)
        self._seen.pop(message_id, None)

    def wait_for_word(self, after_message_id: int, words: set[str], timeout: float) -> Optional[tuple[int, str]]:
        """Blocks until the person sends one of `words` (any case) or the time runs out."""
        self._want(words, False)
        try:
            return self._wait_for_word(after_message_id, words, timeout)
        finally:
            self._want(set(), False)

    def _wait_for_word(self, after_message_id: int, words: set[str], timeout: float) -> Optional[tuple[int, str]]:
        deadline = time.monotonic() + timeout
        failures = 0
        while time.monotonic() < deadline:
            try:
                self._pull(wait=min(LONG_POLL_SECONDS, max(1, deadline - time.monotonic())))
                failures = 0
            except TelegramError:
                failures += 1
                if failures >= 30:
                    raise
                time.sleep(min(60, 5 * failures))
                continue
            for mid, text in sorted(self._seen.items()):
                if mid > after_message_id and text.strip().casefold() in words:
                    return mid, text.strip().casefold()
        return None



class FakeInbox:
    """Juan-Bot's inbox protocol, for the self-test: one routed reply per session after a word is wanted."""

    def __init__(self) -> None:
        import socketserver
        import threading
        self.path = os.path.join(tempfile.mkdtemp(), "inbox.sock")
        self.sessions = {}  # type: dict[str, dict]
        self.ops = []  # type: list[str]
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                req = json.loads(self.rfile.readline())
                op, a = req["op"], req.get("args") or {}
                fake.ops.append(op)
                out = {"ok": True, "result": {}}  # type: dict
                if op == "open":
                    sid = f"s{len(fake.sessions)}"
                    fake.sessions[sid] = {"watched": [], "words": [], "msgs": []}
                    out["result"] = {"session": sid}
                elif a.get("session") not in fake.sessions:
                    out = {"ok": False, "error": "KeyError: 'unknown session'"}
                elif op == "watch":
                    fake.sessions[a["session"]]["watched"] += a["message_ids"]
                elif op == "want":
                    fake.sessions[a["session"]]["words"] = a["words"]
                    if "go" in a["words"]:
                        fake.sessions[a["session"]]["msgs"] = [[51, "go"]]
                elif op == "pull":
                    out["result"] = {"messages": [m for m in fake.sessions[a["session"]]["msgs"]
                                                  if m[0] > a["after"]]}
                self.wfile.write((json.dumps(out) + "\n").encode())

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        self.server = Server(self.path, Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def self_test() -> int:
    global INBOX_RETRY_SECONDS
    rendered = to_html("**T0 login** (`a@b`)\n\n[Open](https://x.test/?a=1&b=<2>)")
    assert rendered == ('<b>T0 login</b> (<code>a@b</code>)\n\n'
                        '<a href="https://x.test/?a=1&amp;b=&lt;2&gt;">Open</a>'), rendered
    bot = TelegramBot.__new__(TelegramBot)
    bot._seen = {10: "go", 11: "4/code_abcdefghijklmnop", 12: "hello there"}
    bot._pull = lambda wait=0: None  # type: ignore[method-assign]
    assert bot.poll_code(10) == (11, "4/code_abcdefghijklmnop")
    assert bot.code_reply_ids(11) == []
    assert bot.replies_after(10) == [(11, "4/code_abcdefghijklmnop"), (12, "hello there")]
    assert bot.wait_for_word(9, {"go"}, timeout=1) == (10, "go")

    # Through Juan-Bot's inbox: the helper's message is watched, the word is wanted only while waiting.
    fake = FakeInbox()
    bot = TelegramBot.__new__(TelegramBot)
    bot._seen, bot._offset, bot.chat_id = {}, None, 1
    bot._inbox = Inbox(fake.path, "test")
    bot._call = lambda method, http_timeout=30, **params: {"message_id": 50}  # type: ignore[method-assign]
    assert bot.dm("Daily logins ready? reply `go`") == 50
    assert fake.sessions["s0"]["watched"] == [50]
    assert bot.wait_for_word(50, {"go", "skip"}, timeout=5) == (51, "go")
    assert fake.sessions["s0"]["words"] == []  # no longer waits for "go"
    fake.sessions.clear()  # Juan-Bot forgot the session: the client opens a new one
    bot.replies_after(50)
    assert "s0" in fake.sessions and fake.sessions["s0"]["watched"] == [50], fake.sessions

    # Juan-Bot down: the helper says so and reads Telegram itself.
    fake.stop()
    direct = []
    bot._pull_direct = lambda wait=0: direct.append(wait)  # type: ignore[method-assign]
    INBOX_RETRY_SECONDS = 0
    bot._pull()
    assert bot._inbox is None and direct == [0]
    INBOX_RETRY_SECONDS = 60
    saved = os.environ.pop("JB_INBOX_SOCKET", None)
    os.environ["JB_INBOX_SOCKET"] = os.path.join(tempfile.mkdtemp(), "missing.sock")
    inbox, why = connect_inbox("test")
    assert inbox is None and "failed" in why, why
    os.environ.pop("JB_INBOX_SOCKET")
    if saved is not None:
        os.environ["JB_INBOX_SOCKET"] = saved
    print("self-test passed")
    return 0


def inbox_test(timeout: float) -> int:
    """Live check: ask Juan for `ok` and wait for Juan-Bot to route his reply here."""
    bot = TelegramBot()
    if not bot.via_inbox:
        print("FAIL: Juan-Bot's inbox is not reachable", file=sys.stderr)
        return 2
    prompt = bot.dm("🧪 Juan-Bot inbox test: reply `ok`")
    answer = bot.wait_for_word(prompt, {"ok"}, timeout=timeout)
    if answer is None:
        print(f"no reply within {int(timeout)} s (the request was sent and watched)")
        return 1
    bot.dm("✅ Inbox test passed: Juan-Bot routed your reply to the script.")
    print(f"ok: Juan-Bot routed reply {answer[0]} to this script")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["inbox-test"]:
        raise SystemExit(inbox_test(float(sys.argv[2]) if len(sys.argv) > 2 else 900))
    raise SystemExit(self_test())
