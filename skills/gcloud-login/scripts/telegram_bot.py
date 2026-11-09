#!/usr/bin/env python3
"""Telegram transport for the login helpers: a drop-in for ZulipBot + deleter.

Uses the bot in ~/.config/telegram-bot.env (TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID). The chat must be a private chat with one person, so only
that person can reply. Telegram bot chats are not end-to-end encrypted; the
helpers rely on short-lived, single-use codes and delete every message of an
exchange (bots may delete incoming messages in private chats for 48 hours).

The token goes only in the HTTPS request path, never in argv, output, or logs.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Optional
import urllib.error
import urllib.request

DEFAULT_ENV_FILE = "~/.config/telegram-bot.env"
LONG_POLL_SECONDS = 20


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


class TelegramBot:
    """Sends to one private chat, reads that person's replies, deletes messages.

    Implements the interface the helpers use for Zulip: connectivity_gate, dm,
    poll_code, code_reply_ids, replies_after, and delete. Telegram message IDs
    grow within a chat for both sides, so "after message N" works as on Zulip.
    """

    def __init__(self, env_file: str = DEFAULT_ENV_FILE) -> None:
        self._token, self.chat_id = load_env(env_file)
        self._offset = None  # type: Optional[int]
        self._seen = {}  # type: dict[int, str]  message_id -> text, from the person only

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
        return message_id

    def send_html(self, text: str) -> int:
        result = self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML",
                            link_preview_options={"is_disabled": True})
        return int(result["message_id"])

    def _pull(self, wait: float = 0) -> None:
        """Reads new updates, keeps the person's text messages, confirms the rest."""
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



def self_test() -> int:
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
    print("self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
