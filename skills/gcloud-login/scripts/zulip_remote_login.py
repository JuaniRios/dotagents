#!/usr/bin/env python3
"""Complete a gcloud browser-only login using a private Zulip DM handoff."""

from __future__ import annotations

import argparse
import base64
import configparser
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
import struct
import subprocess
import sys
import termios
import time
from typing import Any, Optional, Sequence
import urllib.error
import urllib.request


GOOGLE_URL_RE = re.compile(r"https://accounts\.google\.com/[^\s]+")
ANY_URL_RE = re.compile(r"https://[^\s]+")
DEFAULT_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 5.0
GCLOUD_EXIT_GRACE_SECONDS = 30.0


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
    result: dict[str, Any], recipient: str, after_message_id: int
) -> Optional[tuple[int, str]]:
    pattern = re.compile(r"^\s*(\S{16,2048})\s*$")
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
    return candidates[-1]


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

    def poll_code(self, after_message_id: int) -> Optional[tuple[int, str]]:
        result = run_json(
            [
                *self.base,
                "messages",
                "--sender",
                self.recipient,
                "--limit",
                "25",
            ]
        )
        return extract_authorization_code(result, self.recipient, after_message_id)


class ZulipMessageDeleter:
    def __init__(self, config: Path, expected_email: str) -> None:
        parser = configparser.ConfigParser()
        try:
            loaded = parser.read(config)
            api = parser["api"]
            self.site = api["site"].rstrip("/")
            email = api["email"]
            key = api["key"]
        except (OSError, KeyError, configparser.Error) as error:
            raise LoginError("Zulip deletion credentials are invalid") from error
        if not loaded or not self.site.startswith("https://"):
            raise LoginError("Zulip deletion credentials are invalid")
        if email.casefold() != expected_email.casefold():
            raise LoginError("Zulip deletion identity does not match the recipient")
        token = base64.b64encode(f"{email}:{key}".encode("utf-8")).decode("ascii")
        self.authorization = f"Basic {token}"

    def delete(self, message_id: int) -> None:
        request = urllib.request.Request(
            f"{self.site}/api/v1/messages/{message_id}",
            method="DELETE",
            headers={"Authorization": self.authorization},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read())
        except (OSError, ValueError) as error:
            raise LoginError("Zulip message deletion failed") from error
        if result.get("result") != "success":
            raise LoginError("Zulip message deletion did not succeed")


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


def read_pty(master_fd: int, output: str) -> str:
    try:
        chunk = os.read(master_fd, 65536)
    except OSError:
        chunk = b""
    if not chunk:
        return output
    return (output + chunk.decode("utf-8", errors="replace"))[-200000:]


def wait_for_gcloud(
    process: subprocess.Popen[bytes], master_fd: int, timeout: float, output: str
) -> tuple[Optional[int], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master_fd], [], [], 0.5)
        if ready:
            output = read_pty(master_fd, output)
        return_code = process.poll()
        if return_code is not None:
            return return_code, output
    return None, output


def credential_paths(gcloud: str, update_adc: bool) -> list[Path]:
    try:
        result = subprocess.run(
            [gcloud, "info", "--format=value(config.paths.global_config_dir)"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise LoginError("Could not resolve the gcloud configuration directory") from error
    root = Path(result.stdout.strip())
    if result.returncode != 0 or not root.is_absolute():
        raise LoginError("Could not resolve the gcloud configuration directory")
    paths = [root / "credentials.db"]
    if update_adc:
        paths.append(root / "application_default_credentials.json")
    return paths


def mtimes(paths: Sequence[Path]) -> dict[Path, Optional[int]]:
    result = {}  # type: dict[Path, Optional[int]]
    for path in paths:
        try:
            result[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            result[path] = None
    return result


def verify_hung_gcloud_completion(
    gcloud: str,
    account: str,
    update_adc: bool,
    before: dict[Path, Optional[int]],
) -> bool:
    after = mtimes(list(before))
    if not all(after[path] != before[path] for path in before):
        return False
    commands = [[gcloud, "auth", "print-access-token", f"--account={account}"]]
    if update_adc:
        commands.append([gcloud, "auth", "application-default", "print-access-token"])
    for command in commands:
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
    return True


def terminate_child(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass


def host_label() -> str:
    if sys.platform == "darwin":
        return "the **MacBook** (`juanrios-m2`)"
    if sys.platform.startswith("linux"):
        return "the **Dev server** (`juan-dev-server`)"
    return "an **unknown host**"


def login_message(target: str, account: str, request_id: str, url: str) -> str:
    return (
        f"Google Cloud authentication is required on {target} for "
        f"`{account}`.\n\n"
        f"[Open Google authentication]({url})\n\n"
        "After Google displays the authorization code, reply to this private "
        "bot DM with only the copied code—no label, quotes, or other text.\n\n"
        f"Request: `{request_id}`\n\n"
        "This request expires in 15 minutes. After successful login, the bot "
        "will permanently delete this request and your code reply."
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

    delete_config = Path(args.zulip_delete_config).expanduser()
    if not delete_config.is_file():
        raise LoginError("Zulip deletion credentials are missing")
    if delete_config.stat().st_mode & 0o077:
        raise LoginError("Zulip deletion credential permissions are too broad")

    bot = ZulipBot(zulipctl, config, args.recipient)
    bot.connectivity_gate()
    deleter = ZulipMessageDeleter(delete_config, args.recipient)
    tracked_credentials = credential_paths(gcloud, args.update_adc)
    credentials_before = mtimes(tracked_credentials)

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
    code_message_id = 0
    request_message_id = 0
    next_poll = float("inf")
    poll_failures = 0
    target = host_label()
    authenticated = False

    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if ready:
                updated_output = read_pty(master_fd, output)
                if updated_output != output:
                    output = updated_output
                    if url is None:
                        match = GOOGLE_URL_RE.search(output)
                        if match:
                            url = match.group(0).rstrip(".,)")
                            request_message_id = bot.dm(
                                login_message(target, args.account, request_id, url)
                            )
                            next_poll = time.monotonic()
                            print(
                                "Sent a private Google authentication request "
                                "from Juan-Bot and waiting for the correlated reply.",
                                flush=True,
                            )

            if url is not None and time.monotonic() >= next_poll:
                try:
                    reply = bot.poll_code(request_message_id)
                except LoginError:
                    reply = None
                    poll_failures += 1
                    if poll_failures >= 3:
                        raise LoginError("Repeated Zulip polling failure")
                else:
                    poll_failures = 0
                next_poll = time.monotonic() + POLL_SECONDS
                if reply is not None:
                    code_message_id, code = reply
                    os.write(master_fd, code.encode("utf-8") + b"\n")
                    print(
                        "Received the private authorization reply and submitted it "
                        "to gcloud.",
                        flush=True,
                    )
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
        exit_grace = min(GCLOUD_EXIT_GRACE_SECONDS, remaining)
        return_code, output = wait_for_gcloud(
            process, master_fd, exit_grace, output
        )
        if return_code is None:
            if not verify_hung_gcloud_completion(
                gcloud, args.account, args.update_adc, credentials_before
            ):
                raise LoginError("Timed out while Google completed authentication")
            terminate_child(process)
            return_code = 0
        if return_code != 0:
            safe_tail = sanitize(output[-4000:], code)
            raise LoginError(f"Google rejected the authorization response: {safe_tail.strip()}")

        authenticated = True
        deleter.delete(code_message_id)
        deleter.delete(request_message_id)
        code = None

        bot.dm(
            f"Google Cloud authentication completed on {target} "
            f"for `{args.account}` (request `{request_id}`). The authentication "
            "request and code reply were permanently deleted."
        )
        print("Google Cloud authentication completed successfully.", flush=True)
        return 0
    except LoginError as error:
        try:
            if authenticated:
                bot.dm(
                    f"Google Cloud authentication completed on {target} for "
                    f"`{args.account}`, but Zulip message cleanup failed "
                    f"(request `{request_id}`)."
                )
            else:
                bot.dm(
                    f"Google Cloud authentication failed on {target} "
                    f"for `{args.account}` (request `{request_id}`): "
                    f"{sanitize(str(error), code)}"
                )
        except LoginError:
            pass
        if authenticated:
            raise LoginError(
                "Google Cloud authentication succeeded, but Zulip message cleanup failed"
            ) from error
        raise
    finally:
        terminate_child(process)
        os.close(master_fd)
        code = None


def self_test() -> int:
    result = {
        "messages": [
            {
                "id": 12,
                "type": "private",
                "sender_email": "juan@rainlang.xyz",
                "content": "<p>4/test-code_123456789</p>",
            }
        ]
    }
    reply = extract_authorization_code(result, "juan@rainlang.xyz", after_message_id=11)
    assert reply == (12, "4/test-code_123456789")
    code = reply[1]
    result["messages"][0]["content"] = "<p>extra 4/test-code_123456789</p>"
    assert extract_authorization_code(
        result, "juan@rainlang.xyz", after_message_id=11
    ) is None
    result["messages"][0]["content"] = "<p>4/test-code_123456789</p>"
    result["messages"][0]["sender_email"] = "someone@example.com"
    assert extract_authorization_code(
        result, "juan@rainlang.xyz", after_message_id=11
    ) is None
    result["messages"][0]["sender_email"] = "juan@rainlang.xyz"
    result["messages"][0]["type"] = "stream"
    assert extract_authorization_code(
        result, "juan@rainlang.xyz", after_message_id=11
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
    parser.add_argument("--zulip-delete-config", default="~/.zuliprc-personal")
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
