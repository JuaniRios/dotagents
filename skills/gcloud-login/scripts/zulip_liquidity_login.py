#!/usr/bin/env python3
"""Complete a st0x-liquidity-client loopback sign-in using a private Zulip DM handoff.

The client prints a Google sign-in URL and waits on a 127.0.0.1 port for the
OAuth redirect. The phone cannot reach that port, so the user copies the failed
redirect URL from the phone's address bar and replies with it. This helper
checks the reply against the port and state of the waiting client and replays
only its query string to that local port.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Optional, Sequence
import urllib.error
import urllib.parse
import urllib.request

from zulip_remote_login import (
    GOOGLE_URL_RE,
    INTERRUPT_SIGNALS,
    FakeBot,
    FakeDeleter,
    Interrupted,
    LoginAttempt,
    LoginError,
    ZulipBot,
    ZulipMessageDeleter,
    code_only_replies,
    host_label,
    raise_interrupted,
    read_pty,
    sanitize,
    spawn_gcloud as spawn_pty,
    terminate_child,
    wait_for_gcloud as wait_for_child,
)


DEFAULT_TIMEOUT_SECONDS = 15 * 60
# The wrapper fetches master and may rebuild the client before it prints a URL.
DEFAULT_BUILD_TIMEOUT_SECONDS = 20 * 60
POLL_SECONDS = 5.0
CLIENT_EXIT_GRACE_SECONDS = 180.0


class SignIn:
    """The port and CSRF state of the waiting client, read from its sign-in URL."""

    def __init__(self, url: str) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        redirect = urllib.parse.urlsplit(query.get("redirect_uri", [""])[0])
        state = query.get("state", [""])[0]
        if redirect.scheme != "http" or redirect.hostname != "127.0.0.1" or not redirect.port:
            raise LoginError("The client printed an unexpected redirect address")
        if not state:
            raise LoginError("The client sign-in URL carried no state")
        self.port = redirect.port
        self.state = state

    def redirect_query(self, reply: str) -> Optional[str]:
        """The reply's query string if it is this client's redirect with a code."""
        text = reply.strip()
        # Phone browsers often copy the address without its scheme, and the
        # query's scope value itself contains "https://".
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
            text = "http://" + text
        parts = urllib.parse.urlsplit(text)
        try:
            port = parts.port
        except ValueError:
            return None
        if parts.hostname not in {"127.0.0.1", "localhost"} or port != self.port:
            return None
        params = urllib.parse.parse_qs(parts.query)
        if params.get("state", [""])[0] != self.state:
            return None
        if not params.get("code", [""])[0]:
            return None
        return parts.query


def deliver_redirect(port: int, query: str) -> None:
    """Replays the redirect to the waiting client, bypassing any proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/?{query}", timeout=30) as response:
            response.read()
    except (OSError, urllib.error.URLError) as error:
        raise LoginError("Could not deliver the redirect to the waiting client") from error


def refresh_token_path(env: str) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "st0x-liquidity-client" / f"oauth-{env}.json"


def mtime(path: Path) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def login_message(target: str, env: str, request_id: str, url: str) -> str:
    return (
        f"**T0 liquidity client sign-in needed** (`{env}`)\n\n"
        f"`st0x-liquidity-client` is waiting on {target}. Sign in with your "
        "T0 account `@t0trade.com`.\n\n"
        f"[Open Google sign-in]({url})\n\n"
        "After you sign in, the browser tries to open a `127.0.0.1` address "
        "and fails. That is expected. Copy that full address from the address "
        "bar and reply to this private bot DM with only the address, with no "
        "other text.\n\n"
        f"Request: `{request_id}`\n\n"
        "This request expires in 15 minutes. When the sign-in ends, whether it "
        "succeeds or fails, the bot permanently deletes this request and your "
        "reply."
    )


def run_login(
    args: argparse.Namespace,
    attempt: LoginAttempt,
    process: subprocess.Popen[bytes],
    master_fd: int,
    token_before: Optional[int],
) -> None:
    request_id = secrets.token_hex(5)
    url_deadline = time.monotonic() + args.build_timeout
    deadline = None  # type: Optional[float]
    output = ""
    sign_in = None  # type: Optional[SignIn]
    reply_query = None  # type: Optional[str]
    next_poll = float("inf")
    poll_failures = 0
    target = host_label()

    try:
        while time.monotonic() < (deadline if deadline is not None else url_deadline):
            ready, _, _ = select.select([master_fd], [], [], 0.5)
            if ready:
                output = read_pty(master_fd, output)
                if sign_in is None:
                    match = GOOGLE_URL_RE.search(output)
                    if match:
                        url = match.group(0).rstrip(".,)")
                        sign_in = SignIn(url)
                        attempt.send_request(login_message(target, args.env, request_id, url))
                        deadline = time.monotonic() + args.timeout
                        next_poll = time.monotonic()
                        print(
                            "Sent a private sign-in request from Juan-Bot and waiting "
                            "for the correlated reply.",
                            flush=True,
                        )

            if sign_in is not None and time.monotonic() >= next_poll:
                try:
                    replies = attempt.bot.replies_after(attempt.request_message_id)
                except LoginError:
                    replies = []
                    poll_failures += 1
                    if poll_failures >= 3:
                        raise LoginError("Repeated Zulip polling failure")
                else:
                    poll_failures = 0
                next_poll = time.monotonic() + POLL_SECONDS
                for message_id, text in reversed(replies):
                    query = sign_in.redirect_query(text)
                    if query is not None:
                        attempt.consumed_reply(message_id)
                        reply_query = query
                        break
                if reply_query is not None:
                    deliver_redirect(sign_in.port, reply_query)
                    print(
                        "Received the private redirect reply and delivered it to the "
                        "waiting client.",
                        flush=True,
                    )
                    break

            return_code = process.poll()
            if return_code is not None:
                if sign_in is None and return_code == 0:
                    print("The client was already signed in; no sign-in was needed.", flush=True)
                    return
                safe_tail = sanitize(output[-4000:])
                raise LoginError(f"The client exited before the handoff: {safe_tail.strip()}")

        if sign_in is None:
            raise LoginError("Timed out waiting for the client to print a sign-in URL")
        if reply_query is None:
            raise LoginError("Timed out waiting for the private Zulip redirect reply")

        return_code, output = wait_for_child(
            process, master_fd, CLIENT_EXIT_GRACE_SECONDS, output
        )
        signed_in = mtime(refresh_token_path(args.env)) != token_before
        if return_code == 0:
            return
        safe_tail = sanitize(output[-4000:], reply_query)
        if signed_in:
            raise LoginError(
                "Sign-in succeeded and the refresh token was saved, but the check "
                f"command failed: {safe_tail.strip()}"
            )
        raise LoginError(f"The client did not complete the sign-in: {safe_tail.strip()}")
    except LoginError as error:
        raise LoginError(sanitize(str(error), reply_query)) from None
    finally:
        reply_query = None


class LiquidityZulipBot(ZulipBot):
    def replies_after(self, after_message_id: Optional[int]) -> list[tuple[int, str]]:
        if after_message_id is None:
            return []
        return code_only_replies(self._recent_replies(), self.recipient, after_message_id)


def run_attempt(
    args: argparse.Namespace,
    attempt: LoginAttempt,
    command: Sequence[str],
    token_before: Optional[int],
) -> int:
    previous = {sig: signal.getsignal(sig) for sig in INTERRUPT_SIGNALS}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, raise_interrupted)
    failure = None  # type: Optional[str]
    process = None  # type: Optional[subprocess.Popen[bytes]]
    master_fd = None  # type: Optional[int]
    try:
        process, master_fd = spawn_pty(command)
        run_login(args, attempt, process, master_fd, token_before)
    except LoginError as error:
        failure = str(error)
    except (KeyboardInterrupt, Interrupted):
        failure = "Sign-in interrupted before it completed"
    except Exception as error:  # noqa: BLE001 - never leak a traceback
        failure = f"Unexpected helper error ({type(error).__name__})"
    finally:
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
        print("Liquidity client sign-in completed successfully.", flush=True)
    else:
        print(f"error: {sanitize(failure)}", file=sys.stderr, flush=True)
    if cleanup.ok:
        print(cleanup.summary(), flush=True)
    else:
        print(f"error: Zulip cleanup incomplete. {cleanup.summary()}", file=sys.stderr, flush=True)
    return 0 if failure is None and cleanup.ok else 1


def orchestrate(args: argparse.Namespace) -> int:
    nu = shutil.which("nu")
    zulipctl = shutil.which("zulipctl")
    if not nu:
        raise LoginError("nu is not installed")
    if not zulipctl:
        raise LoginError("zulipctl is not installed")
    for path in (args.zulip_config, args.zulip_delete_config):
        config = Path(path).expanduser()
        if not config.is_file():
            raise LoginError("Zulip credentials are missing")
        if config.stat().st_mode & 0o077:
            raise LoginError("Zulip credential permissions are too broad")

    bot = LiquidityZulipBot(zulipctl, Path(args.zulip_config).expanduser(), args.recipient)
    bot.connectivity_gate()
    deleter = ZulipMessageDeleter(Path(args.zulip_delete_config).expanduser(), args.recipient)

    token_path = refresh_token_path(args.env)
    if token_path.exists() and not args.force:
        raise LoginError(
            "A cached refresh token already exists; run the client directly, or pass "
            "--force to sign in again"
        )
    if args.force and token_path.exists():
        token_path.unlink()

    # The wrapper is a nushell login-shell command, so run it through `nu -l`.
    command = [nu, "-l", "-c", f"st0x-liquidity-client --env {args.env} read resource health"]
    return run_attempt(args, LoginAttempt(bot, deleter), command, mtime(token_path))


class FakeLiquidityBot(FakeBot):
    def dm(self, content: str) -> int:
        assert "sign-in needed" in content, "only the request DM may be sent"
        self.sent.append(100 + len(self.sent))
        return self.sent[-1]

    def replies_after(self, after_message_id: Optional[int]) -> list[tuple[int, str]]:
        return [reply for reply in self.replies if reply[0] > (after_message_id or 0)]


FAKE_CLIENT = r"""
import http.server, socketserver, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        H.path_seen = self.path
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", int(sys.argv[1])), H)
port = srv.server_address[1]
print(f"Open https://accounts.google.com/o/oauth2/v2/auth?client_id=x"
      f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}&state=goodstate&response_type=code",
      flush=True)
srv.handle_request()
sys.exit(0 if "code=4%2Fcode" in H.path_seen and "state=goodstate" in H.path_seen else 7)
"""


def self_test() -> int:
    sign_in = SignIn(
        "https://accounts.google.com/o/oauth2/v2/auth?redirect_uri=http%3A%2F%2F127.0.0.1"
        "%3A41234&state=abc123"
    )
    assert sign_in.port == 41234 and sign_in.state == "abc123"
    good = "http://127.0.0.1:41234/?state=abc123&code=4%2Fcode&scope=email+openid"
    assert sign_in.redirect_query(good) == "state=abc123&code=4%2Fcode&scope=email+openid"
    assert sign_in.redirect_query(good.replace("http://", "")) is not None
    scoped = "127.0.0.1:41234/?state=abc123&code=4%2Fc&scope=email+https://www.googleapis.com/x"
    assert sign_in.redirect_query(scoped) is not None
    assert sign_in.redirect_query(good.replace("41234", "41235")) is None
    assert sign_in.redirect_query(good.replace("abc123", "evil")) is None
    assert sign_in.redirect_query(good.replace("127.0.0.1", "evil.example")) is None
    assert sign_in.redirect_query("http://127.0.0.1:41234/?state=abc123") is None
    try:
        SignIn("https://accounts.google.com/o?redirect_uri=https%3A%2F%2Fevil&state=x")
    except LoginError:
        pass
    else:
        raise AssertionError("a non-loopback redirect must be rejected")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [sys.executable, "-c", FAKE_CLIENT, str(port)]

    def run(replies: list[tuple[int, str]], timeout: int = 20) -> tuple[int, FakeDeleter]:
        bot, deleter = FakeLiquidityBot(replies), FakeDeleter()
        args = argparse.Namespace(env="production", timeout=timeout, build_timeout=20)
        code = run_attempt(args, LoginAttempt(bot, deleter), command, None)
        assert bot.sent == [100], "only the request DM may be sent"
        return code, deleter

    # Success: the latest matching reply is delivered; a wrong-state reply is
    # ignored but still deleted, along with the request.
    code, deleter = run(
        [
            (101, f"http://127.0.0.1:{port}/?state=wrong&code=4%2Fcode"),
            (102, f"http://127.0.0.1:{port}/?state=goodstate&code=4%2Fcode"),
        ]
    )
    assert code == 0 and sorted(deleter.deleted) == [100, 101, 102], deleter.deleted

    # Timeout with only a non-matching reply: nothing delivered, all deleted.
    code, deleter = run([(101, "http://127.0.0.1:1/?state=x&code=y_123456789")], timeout=2)
    assert code == 1 and sorted(deleter.deleted) == [100, 101], deleter.deleted

    # The client exits before printing a URL: nothing sent or deleted.
    bot, deleter = FakeLiquidityBot([]), FakeDeleter()
    args = argparse.Namespace(env="production", timeout=5, build_timeout=5)
    assert run_attempt(args, LoginAttempt(bot, deleter), ["/bin/sh", "-c", "exit 3"], None) == 1
    assert bot.sent == [] and deleter.deleted == []

    print("self-test passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=["production", "staging"], default="production")
    parser.add_argument("--recipient", default="juan@rainlang.xyz")
    parser.add_argument("--zulip-config", default="~/.zuliprc-bot")
    parser.add_argument("--zulip-delete-config", default="~/.zuliprc-personal")
    parser.add_argument("--force", action="store_true", help="discard a cached refresh token")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--build-timeout", type=int, default=DEFAULT_BUILD_TIMEOUT_SECONDS, help=argparse.SUPPRESS
    )
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
        print("error: Sign-in interrupted before any Zulip request was sent", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
