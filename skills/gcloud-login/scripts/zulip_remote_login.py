#!/usr/bin/env python3
"""Complete a gcloud browser-only login using a private Zulip DM handoff."""

from __future__ import annotations

import argparse
import fcntl
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
from typing import Any, Optional, Sequence


GOOGLE_URL_RE = re.compile(r"https://accounts\.google\.com/[^\s]+")
ANY_URL_RE = re.compile(r"https://[^\s]+")
DEFAULT_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 3.0


class LoginError(RuntimeError):
    """A safe-to-display login orchestration failure."""


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts = []  # type: list[str]

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def message_text(content: str) -> str:
    parser = TextExtractor()
    parser.feed(content)
    return html.unescape(" ".join(parser.parts)).strip()


def extract_authorization_code(
    result: dict[str, Any], request_id: str, recipient: str, after_message_id: int
) -> Optional[str]:
    pattern = re.compile(
        r"(?:^|\s)gcloud-auth\s+"
        + re.escape(request_id)
        + r"\s+(\S+)\s*$",
        re.IGNORECASE,
    )
    candidates = []  # type: list[tuple[int, str]]
    for message in result.get("messages", []):
        message_id = int(message.get("id", 0))
        message_type = str(message.get("type", "")).lower()
        sender = str(message.get("sender_email", ""))
        if message_id <= after_message_id:
            continue
        if message_type not in {"private", "direct"}:
            continue
        if sender.casefold() != recipient.casefold():
            continue
        match = pattern.search(message_text(str(message.get("content", ""))))
        if not match:
            continue
        code = match.group(1)
        if 16 <= len(code) <= 2048 and not any(ch.isspace() for ch in code):
            candidates.append((message_id, code))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def sanitize(text: str, code: Optional[str] = None) -> str:
    sanitized = GOOGLE_URL_RE.sub("[REDACTED_GOOGLE_AUTH_URL]", text)
    sanitized = ANY_URL_RE.sub("[REDACTED_URL]", sanitized)
    if code:
        sanitized = sanitized.replace(code, "[REDACTED_AUTHORIZATION_CODE]")
    return sanitized


def run_json(command: Sequence[str], *, input_text: Optional[str] = None) -> dict[str, Any]:
    try:
        process = subprocess.run(
            list(command),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=70,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise LoginError("Zulip command failed") from error
    if process.returncode != 0:
        raise LoginError("Zulip command failed")
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise LoginError("Zulip command returned invalid data") from error
    if result.get("result") != "success":
        raise LoginError("Zulip command did not succeed")
    return result


class ZulipBot:
    def __init__(self, executable: str, config: Path, recipient: str) -> None:
        self.base = [executable, "--config", str(config), "--compact"]
        self.recipient = recipient

    def connectivity_gate(self) -> None:
        result = run_json([*self.base, "me"])
        user = result.get("user", {})
        if not user.get("is_bot"):
            raise LoginError("Configured Zulip identity is not a bot")
        users = run_json([*self.base, "users", "--active-only"])
        exact = [
            user
            for user in users.get("members", [])
            if str(user.get("email", "")).casefold() == self.recipient.casefold()
            and user.get("is_active")
            and not user.get("is_bot")
        ]
        if len(exact) != 1:
            raise LoginError("Zulip recipient did not resolve uniquely")

    def dm(self, content: str) -> int:
        result = run_json(
            [*self.base, "dm", self.recipient],
            input_text=content,
        )
        message_id = result.get("verified", {}).get("message_id")
        if not isinstance(message_id, int):
            raise LoginError("Zulip did not return a message ID")
        return message_id

    def poll_code(self, request_id: str, after_message_id: int) -> Optional[str]:
        result = run_json(
            [
                *self.base,
                "messages",
                "--sender",
                self.recipient,
                "--search",
                request_id,
                "--limit",
                "25",
            ]
        )
        return extract_authorization_code(
            result, request_id, self.recipient, after_message_id
        )


def spawn_gcloud(command: Sequence[str]) -> tuple[subprocess.Popen[bytes], int]:
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 4096, 0, 0))
    attributes = termios.tcgetattr(slave_fd)
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
    try:
        process = subprocess.Popen(
            list(command),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)
    return process, master_fd


def terminate_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def login_message(hostname: str, account: str, request_id: str, url: str) -> str:
    return (
        f"Google Cloud authentication is required on **{hostname}** for "
        f"`{account}`.\n\n"
        f"[Open Google authentication]({url})\n\n"
        "After Google displays the authorization code, reply to this private "
        "bot DM with exactly:\n\n"
        f"`gcloud-auth {request_id} AUTHORIZATION_CODE`\n\n"
        "This request expires in 15 minutes. The code is short-lived and "
        "single-use, but your reply remains in Zulip history."
    )


def orchestrate(args: argparse.Namespace) -> int:
    gcloud = shutil.which("gcloud")
    zulipctl = shutil.which("zulipctl")
    if not gcloud:
        raise LoginError("gcloud is not installed")
    if not zulipctl:
        raise LoginError("zulipctl is not installed")

    config = Path(args.zulip_config).expanduser()
    if not config.is_file():
        raise LoginError("Zulip bot credentials are missing")
    if config.stat().st_mode & 0o077:
        raise LoginError("Zulip bot credential permissions are too broad")

    bot = ZulipBot(zulipctl, config, args.recipient)
    bot.connectivity_gate()

    command = [
        gcloud,
        "auth",
        "login",
        args.account,
        "--force",
        "--no-launch-browser",
    ]
    if args.update_adc:
        command.append("--update-adc")

    process, master_fd = spawn_gcloud(command)
    request_id = secrets.token_hex(5)
    deadline = time.monotonic() + args.timeout
    output = ""
    url = None  # type: Optional[str]
    code = None  # type: Optional[str]
    request_message_id = 0
    next_poll = float("inf")
    poll_failures = 0

    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    output = (output + chunk.decode("utf-8", errors="replace"))[-200000:]
                    if url is None:
                        match = GOOGLE_URL_RE.search(output)
                        if match:
                            url = match.group(0).rstrip(".,)")
                            request_message_id = bot.dm(
                                login_message(
                                    socket.gethostname(), args.account, request_id, url
                                )
                            )
                            next_poll = time.monotonic()
                            print(
                                "Sent a private Google authentication request "
                                "from Juan-Bot and waiting for the correlated reply.",
                                flush=True,
                            )

            if url is not None and time.monotonic() >= next_poll:
                try:
                    code = bot.poll_code(request_id, request_message_id)
                except LoginError:
                    code = None
                    poll_failures += 1
                    if poll_failures >= 3:
                        raise LoginError("Repeated Zulip polling failure")
                else:
                    poll_failures = 0
                next_poll = time.monotonic() + POLL_SECONDS
                if code is not None:
                    os.write(master_fd, code.encode("utf-8") + b"\n")
                    break

            return_code = process.poll()
            if return_code is not None:
                if return_code == 0:
                    raise LoginError("gcloud exited before requesting an authorization code")
                safe_tail = sanitize(output[-4000:])
                raise LoginError(f"gcloud login failed before handoff: {safe_tail.strip()}")

        if code is None:
            raise LoginError("Timed out waiting for the private Zulip authorization reply")

        remaining = max(1.0, deadline - time.monotonic())
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise LoginError("Timed out while Google completed authentication") from error
        if return_code != 0:
            safe_tail = sanitize(output[-4000:], code)
            raise LoginError(f"Google rejected the authorization response: {safe_tail.strip()}")

        bot.dm(
            f"Google Cloud authentication completed on **{socket.gethostname()}** "
            f"for `{args.account}` (request `{request_id}`)."
        )
        print("Google Cloud authentication completed successfully.", flush=True)
        return 0
    except LoginError as error:
        try:
            bot.dm(
                f"Google Cloud authentication failed on **{socket.gethostname()}** "
                f"for `{args.account}` (request `{request_id}`): {sanitize(str(error), code)}"
            )
        except LoginError:
            pass
        raise
    finally:
        terminate_child(process)
        os.close(master_fd)
        code = None


def self_test() -> int:
    request_id = "a1b2c3d4e5"
    result = {
        "messages": [
            {
                "id": 12,
                "type": "private",
                "sender_email": "juan@rainlang.xyz",
                "content": f"<p>gcloud-auth {request_id} 4/test-code_123456789</p>",
            }
        ]
    }
    code = extract_authorization_code(
        result, request_id, "juan@rainlang.xyz", after_message_id=11
    )
    assert code == "4/test-code_123456789"
    assert extract_authorization_code(
        result, "wrong-request", "juan@rainlang.xyz", after_message_id=11
    ) is None
    result["messages"][0]["sender_email"] = "someone@example.com"
    assert extract_authorization_code(
        result, request_id, "juan@rainlang.xyz", after_message_id=11
    ) is None
    result["messages"][0]["sender_email"] = "juan@rainlang.xyz"
    result["messages"][0]["type"] = "stream"
    assert extract_authorization_code(
        result, request_id, "juan@rainlang.xyz", after_message_id=11
    ) is None
    redacted = sanitize("open https://accounts.google.com/o/oauth2/auth?secret=yes", code)
    assert "accounts.google.com" not in redacted
    assert code not in redacted

    dummy_code = "4/dummy-secret-code_123456789"
    process, master_fd = spawn_gcloud(
        [
            "/bin/sh",
            "-c",
            f'IFS= read -r value; test "$value" = "{dummy_code}"; printf "accepted\\n"',
        ]
    )
    try:
        os.write(master_fd, dummy_code.encode("utf-8") + b"\n")
        received = b""
        read_deadline = time.monotonic() + 5
        while time.monotonic() < read_deadline and b"accepted" not in received:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            received += chunk
        assert process.wait(timeout=5) == 0
        assert dummy_code.encode("utf-8") not in received
        assert b"accepted" in received
    finally:
        terminate_child(process)
        os.close(master_fd)

    print("self-test passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="juan@t0trade.com")
    parser.add_argument("--recipient", default="juan@rainlang.xyz")
    parser.add_argument("--zulip-config", default="~/.zuliprc-bot")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help=argparse.SUPPRESS
    )
    parser.add_argument("--update-adc", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    try:
        return orchestrate(args)
    except LoginError as error:
        print(f"error: {sanitize(str(error))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
