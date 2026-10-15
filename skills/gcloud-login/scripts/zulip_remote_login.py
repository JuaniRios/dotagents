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


def code_only_replies(
    result: dict[str, Any], recipient: str, after_message_id: int
) -> list[tuple[int, str]]:
    """Return every code-only private reply from the recipient, oldest first."""
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
    candidates.sort()
    return candidates


def extract_authorization_code(
    result: dict[str, Any], recipient: str, after_message_id: int
) -> Optional[tuple[int, str]]:
    candidates = code_only_replies(result, recipient, after_message_id)
    if not candidates:
        return None
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

    def _recent_replies(self) -> dict[str, Any]:
        return run_json(
            [
                *self.base,
                "messages",
                "--sender",
                self.recipient,
                "--limit",
                "25",
            ]
        )

    def poll_code(self, after_message_id: int) -> Optional[tuple[int, str]]:
        return extract_authorization_code(
            self._recent_replies(), self.recipient, after_message_id
        )

    def code_reply_ids(self, after_message_id: int) -> list[int]:
        """IDs of every code-only reply after the request; codes are discarded."""
        replies = code_only_replies(
            self._recent_replies(), self.recipient, after_message_id
        )
        return [message_id for message_id, _ in replies]


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


def org_label(account: str) -> str:
    domain = account.rsplit("@", 1)[-1].casefold()
    if domain == "t0trade.com":
        return "T0"
    if domain == "s01issuer.com":
        return "S01"
    return "UNKNOWN ORG"


def login_message(target: str, account: str, request_id: str, url: str) -> str:
    org = org_label(account)
    return (
        f"**{org} login code needed** (`{account}`)\n\n"
        f"Google Cloud authentication is required on {target} for the "
        f"**{org}** account `{account}`.\n\n"
        f"[Open Google authentication]({url})\n\n"
        "After Google displays the authorization code, reply to this private "
        "bot DM with only the copied code—no label, quotes, or other text.\n\n"
        f"Request: `{request_id}`\n\n"
        "This request expires in 15 minutes. When the login ends, whether it "
        "succeeds or fails, the bot permanently deletes this request and your "
        "code reply."
    )


class Interrupted(BaseException):
    """A termination signal; a BaseException so cleanup still runs."""


def raise_interrupted(signum: int, frame: Any) -> None:
    raise Interrupted()


INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
SWEEP_ATTEMPTS = 3


class CleanupResult:
    def __init__(self) -> None:
        self.deleted = 0
        self.failed = 0
        self.sweep_failed = False
        self.request_unknown = False

    @property
    def ok(self) -> bool:
        return not (self.failed or self.sweep_failed or self.request_unknown)

    def summary(self) -> str:
        if not (self.deleted or self.failed or self.sweep_failed or self.request_unknown):
            return "No Zulip login message was sent."
        parts = [f"Permanently deleted {self.deleted} login message(s) from the Zulip DM."]
        if self.failed:
            parts.append(f"Could not delete {self.failed} login message(s).")
        if self.sweep_failed:
            parts.append("Could not list later code-only replies for deletion.")
        if self.request_unknown:
            parts.append(
                "The request DM may have been sent, but Zulip returned no message "
                "ID, so it could not be deleted."
            )
        return " ".join(parts)


class LoginAttempt:
    """Tracks every Zulip message one login request sent or consumed."""

    def __init__(self, bot: Any, deleter: Any) -> None:
        self.bot = bot
        self.deleter = deleter
        self.request_message_id = None  # type: Optional[int]
        self.reply_message_ids = []  # type: list[int]
        self.request_attempted = False

    def send_request(self, content: str) -> int:
        self.request_attempted = True
        self.request_message_id = self.bot.dm(content)
        return self.request_message_id

    def consumed_reply(self, message_id: int) -> None:
        self.reply_message_ids.append(message_id)

    def cleanup(self) -> CleanupResult:
        result = CleanupResult()
        if self.request_message_id is None:
            result.request_unknown = self.request_attempted
            return result
        targets = list(dict.fromkeys(self.reply_message_ids))
        for attempt in range(SWEEP_ATTEMPTS):
            try:
                later = self.bot.code_reply_ids(self.request_message_id)
            except Exception:  # noqa: BLE001 - report, never abort cleanup
                if attempt == SWEEP_ATTEMPTS - 1:
                    result.sweep_failed = True
                continue
            targets.extend(mid for mid in later if mid not in targets)
            break
        targets.append(self.request_message_id)
        for message_id in targets:
            try:
                self.deleter.delete(message_id)
            except Exception:  # noqa: BLE001 - report, never abort cleanup
                result.failed += 1
            else:
                result.deleted += 1
        return result


def run_login(
    args: argparse.Namespace,
    attempt: LoginAttempt,
    process: subprocess.Popen[bytes],
    master_fd: int,
    gcloud: str,
    credentials_before: dict[Path, Optional[int]],
) -> None:
    request_id = secrets.token_hex(5)
    deadline = time.monotonic() + args.timeout
    output = ""
    url = None  # type: Optional[str]
    code = None  # type: Optional[str]
    next_poll = float("inf")
    poll_failures = 0
    target = host_label()

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
                            attempt.send_request(
                                login_message(target, args.account, request_id, url)
                            )
                            next_poll = time.monotonic()
                            print(
                                "Sent a private Google authentication request "
                                "from Juan-Bot and waiting for the correlated reply.",
                                flush=True,
                            )

            if attempt.request_message_id is not None and time.monotonic() >= next_poll:
                try:
                    reply = attempt.bot.poll_code(attempt.request_message_id)
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
                    attempt.consumed_reply(code_message_id)
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
        return_code, output = wait_for_gcloud(process, master_fd, exit_grace, output)
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
    except LoginError as error:
        raise LoginError(sanitize(str(error), code)) from None
    finally:
        code = None
        url = None


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

    return run_attempt(
        args, LoginAttempt(bot, deleter), command, gcloud, credentials_before
    )


def run_attempt(
    args: argparse.Namespace,
    attempt: LoginAttempt,
    command: Sequence[str],
    gcloud: str,
    credentials_before: dict[Path, Optional[int]],
) -> int:
    previous = {sig: signal.getsignal(sig) for sig in INTERRUPT_SIGNALS}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, raise_interrupted)
    failure = None  # type: Optional[str]
    process = None  # type: Optional[subprocess.Popen[bytes]]
    master_fd = None  # type: Optional[int]
    try:
        process, master_fd = spawn_gcloud(command)
        run_login(args, attempt, process, master_fd, gcloud, credentials_before)
    except LoginError as error:
        failure = str(error)
    except (KeyboardInterrupt, Interrupted):
        failure = "Login interrupted before it completed"
    except Exception as error:  # noqa: BLE001 - never leak a traceback
        failure = f"Unexpected helper error ({type(error).__name__})"
    finally:
        # A second Ctrl-C or SIGTERM must not abort message cleanup.
        for sig in INTERRUPT_SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if process is not None:
                terminate_child(process)
            if master_fd is not None:
                os.close(master_fd)
            cleanup = attempt.cleanup()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    if failure is None:
        print("Google Cloud authentication completed successfully.", flush=True)
    else:
        print(f"error: {sanitize(failure)}", file=sys.stderr, flush=True)
    if cleanup.ok:
        print(cleanup.summary(), flush=True)
    else:
        print(f"error: Zulip cleanup incomplete. {cleanup.summary()}", file=sys.stderr, flush=True)
        if failure is None:
            print(
                "error: Google Cloud authentication succeeded, but Zulip message "
                "cleanup failed",
                file=sys.stderr,
                flush=True,
            )
    return 0 if failure is None and cleanup.ok else 1


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

    cleanup_self_test()
    print("self-test passed")
    return 0


class FakeBot:
    """Mock Zulip bot: records DMs and serves a scripted reply list."""

    def __init__(self, replies: Sequence[tuple[int, str]], fail_sweep: bool = False) -> None:
        self.sent = []  # type: list[int]
        self.replies = list(replies)
        self.fail_sweep = fail_sweep

    def dm(self, content: str) -> int:
        assert "login code needed" in content, "only the request DM may be sent"
        self.sent.append(100 + len(self.sent))
        return self.sent[-1]

    def poll_code(self, after_message_id: int) -> Optional[tuple[int, str]]:
        later = [reply for reply in self.replies if reply[0] > after_message_id]
        return later[-1] if later else None

    def code_reply_ids(self, after_message_id: int) -> list[int]:
        if self.fail_sweep:
            raise LoginError("Zulip command failed")
        return [mid for mid, _ in self.replies if mid > after_message_id]


class FakeDeleter:
    def __init__(self, fail: Sequence[int] = ()) -> None:
        self.deleted = []  # type: list[int]
        self.fail = set(fail)

    def delete(self, message_id: int) -> None:
        if message_id in self.fail:
            raise LoginError("Zulip message deletion failed")
        self.deleted.append(message_id)


def fake_gcloud(exit_code: int, before_url: str = "") -> list[str]:
    script = (
        f"{before_url}"
        'printf "Go to https://accounts.google.com/o/oauth2/auth?fake=1\\n"; '
        'printf "Enter code: "; IFS= read -r value; '
        f"exit {exit_code}"
    )
    return ["/bin/sh", "-c", script]


def run_fake(
    command: Sequence[str], bot: FakeBot, deleter: FakeDeleter, timeout: int = 20
) -> int:
    args = argparse.Namespace(account="juan@t0trade.com", update_adc=False, timeout=timeout)
    return run_attempt(args, LoginAttempt(bot, deleter), command, "/bin/false", {})


def cleanup_self_test() -> None:
    code = "4/fake-code_1234567890"
    late = "4/late-code_1234567890"

    # Success: request, consumed reply, and a second code-only reply are deleted.
    bot, deleter = FakeBot([(101, code), (102, late)]), FakeDeleter()
    assert run_fake(fake_gcloud(0), bot, deleter) == 0
    assert sorted(deleter.deleted) == [100, 101, 102], deleter.deleted
    assert bot.sent == [100]

    # Rejection: gcloud exits non-zero after the code; no failure DM, all deleted.
    bot, deleter = FakeBot([(101, code)]), FakeDeleter()
    assert run_fake(fake_gcloud(1), bot, deleter) == 1
    assert sorted(deleter.deleted) == [100, 101]
    assert bot.sent == [100]

    # Timeout with no reply: only the request exists and it is deleted.
    bot, deleter = FakeBot([]), FakeDeleter()
    assert run_fake(fake_gcloud(0), bot, deleter, timeout=2) == 1
    assert deleter.deleted == [100]
    assert bot.sent == [100]

    # SIGTERM or Ctrl-C while waiting: the request and a reply that arrived
    # after polling stopped are both deleted.
    for sig in (signal.SIGTERM, signal.SIGINT):
        bot, deleter = FakeBot([]), FakeDeleter()

        def late_reply(signum: int, frame: Any, bot: FakeBot = bot, sig: int = sig) -> None:
            bot.replies.append((105, late))
            os.kill(os.getpid(), sig)

        signal.signal(signal.SIGALRM, late_reply)
        signal.setitimer(signal.ITIMER_REAL, 1.5)
        try:
            assert run_fake(fake_gcloud(0), bot, deleter) == 1
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
        assert sorted(deleter.deleted) == [100, 105], deleter.deleted

    # gcloud exits before printing a URL: nothing was sent, nothing to delete.
    bot, deleter = FakeBot([]), FakeDeleter()
    assert run_fake(["/bin/sh", "-c", "exit 3"], bot, deleter) == 1
    assert bot.sent == [] and deleter.deleted == []

    # Cleanup failures are reported: success still returns non-zero.
    bot, deleter = FakeBot([(101, code)]), FakeDeleter(fail=[100])
    assert run_fake(fake_gcloud(0), bot, deleter) == 1
    assert deleter.deleted == [101]
    bot, deleter = FakeBot([(101, code)], fail_sweep=True), FakeDeleter()
    assert run_fake(fake_gcloud(0), bot, deleter) == 1
    assert sorted(deleter.deleted) == [100, 101]


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
    except KeyboardInterrupt:
        print("error: Login interrupted before any Zulip request was sent", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
