#!/usr/bin/env python3
"""Refresh every login Juan's agents need, on juan-dev-server and the Mac.

Runs on juan-dev-server. It first asks Juan on Telegram and waits for "go";
it signs nothing in without that reply. Each Google sign-in then goes through
the gcloud-login skill's helpers over the same Telegram bot, one at a time. Tokens are then shared where one sign-in
can serve several places: the liquidity client's token also signs in to the
Alpaca gateway (it admits that OAuth client), the issuance client's production
token serves staging too (one OAuth client), and every cache file plus the
gcloud credentials go to the Mac over SSH.

This script never prints, logs, or puts on a command line a token, code, or
credential file. Files move file to file (or through an SSH stdin pipe) with
mode 600.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
HELPERS = HOME / "Github/dotagents/skills/gcloud-login/scripts"
LOG_DIR = HOME / "Github/dotagents/data/daily-logins"
TELEGRAM_ENV = "~/.config/telegram-bot.env"  # same path on the Mac
sys.path.insert(0, str(HELPERS))
from telegram_bot import TelegramBot, TelegramError  # noqa: E402

CONFIRM_HOURS = 12
LOGIN_NAMES = {
    "server-gcloud-t0": "gcloud T0",
    "server-gcloud-s01": "gcloud S01",
    "liquidity-production": "liquidity production",
    "liquidity-staging": "liquidity staging",
    "issuance": "issuance",
}
MAC = "mac-logins"  # ssh alias in nix-darwin-config home/server.nix
T0 = "juan@t0trade.com"
S01 = "juan@s01issuer.com"
LOOPYLOUPE = "https://loopyloupe.t0trade.com/?gcp-iap-mode=CLEAR_LOGIN_COOKIE"
ALPACA_URL = {
    "production": "https://alpaca-ops.t0trade.com",
    "staging": "https://alpaca-ops-staging.t0trade.com",
}
ALPACA_ENV = {"production": "T0_ALPACA_PROD_URL", "staging": "T0_ALPACA_STAGING_URL"}

# Cache files to copy on the server: (source, destination), under CONFIG.
LOCAL_COPIES = [
    ("st0x-liquidity-client/oauth-production.json", "st0x-liquidity-client/oauth-alpaca-production.json"),
    ("st0x-liquidity-client/oauth-staging.json", "st0x-liquidity-client/oauth-alpaca-staging.json"),
    ("st0x-issuance-client/oauth-production.json", "st0x-issuance-client/oauth-staging.json"),
]
# Every cache file the Mac gets, under CONFIG on both hosts.
MAC_FILES = [
    "st0x-liquidity-client/oauth-production.json",
    "st0x-liquidity-client/oauth-staging.json",
    "st0x-liquidity-client/oauth-alpaca-production.json",
    "st0x-liquidity-client/oauth-alpaca-staging.json",
    "st0x-issuance-client/oauth-production.json",
    "st0x-issuance-client/oauth-staging.json",
    "gcloud/application_default_credentials.json",
]
# The Mac's non-interactive SSH shell has a bare PATH.
MAC_PATH = (
    'export PATH="/etc/profiles/per-user/$USER/bin:/run/current-system/sw/bin:'
    '$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/opt/homebrew/bin:'
    '/usr/local/bin:$PATH"'
)

STEPS = [
    "server-gcloud-t0",
    "server-gcloud-s01",
    "liquidity-production",
    "liquidity-staging",
    "issuance",
    "server-copies",
    "verify-server",
    "mac-copies",
    "mac-gcloud",
    "verify-mac",
    "loopyloupe",
]
MAC_STEPS = {"mac-copies", "mac-gcloud", "verify-mac", "loopyloupe"}


class Run:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.results: list[tuple[str, str, str]] = []  # (credential, host, result)
        self.failed: set[str] = set()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOG_DIR / f"{dt.date.today().isoformat()}.log"
        self.log_file = self.log_path.open("a", encoding="utf-8")
        self.log(f"=== run started {dt.datetime.now().isoformat(timespec='seconds')}")

    def log(self, line: str) -> None:
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def record(self, credential: str, host: str, result: str) -> None:
        self.results.append((credential, host, result))
        self.log(f"[{host}] {credential}: {result}")

    def command(self, argv: list[str], *, stdin: Optional[str] = None,
                env: Optional[dict[str, str]] = None, quiet: bool = False,
                timeout: Optional[float] = None) -> int:
        """Runs a command, logging its output unless quiet. Never pass a secret in argv."""
        if self.dry_run:
            self.log(f"dry-run: {' '.join(argv[:6])}{' ...' if len(argv) > 6 else ''}")
            return 0
        try:
            proc = subprocess.run(
                argv,
                input=stdin,
                text=True,
                env={**os.environ, **(env or {})},
                stdin=None if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
                stderr=subprocess.DEVNULL if quiet else subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124
        if not quiet and proc.stdout:
            for line in proc.stdout.splitlines()[-15:]:
                self.log(f"    {line}")
        return proc.returncode

    def mac(self, script: str, *, quiet: bool = False, timeout: Optional[float] = None) -> int:
        """Runs a bash script on the Mac, sent on stdin so no shell quoting is needed."""
        return self.command(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", MAC, "/bin/bash", "-s"],
            stdin=f"set -u\n{MAC_PATH}\n{script}\n",
            quiet=quiet,
            timeout=timeout,
        )


def gcloud_login(run: Run, account: str, update_adc: bool, host: str, remote: bool) -> bool:
    args = [
        "--account", account,
        "--transport", "telegram",
        "--telegram-env", TELEGRAM_ENV,
    ] + (["--update-adc"] if update_adc else [])
    if remote:
        helper = '"$HOME/Github/dotagents/skills/gcloud-login/scripts/zulip_remote_login.py"'
        code = run.mac(f"set +x\npython3 {helper} {' '.join(args)}")
    else:
        code = run.command(["python3", str(HELPERS / "zulip_remote_login.py"), *args])
    ok = code == 0
    run.record(f"gcloud {account}{' + ADC' if update_adc else ''}", host,
               "ok" if ok else f"failed (helper exit {code})")
    return ok


# The wrappers read each OAuth client secret from these files. An empty one
# fails only at the token exchange, after Juan has signed in on his phone.
SECRET_KEYS = {
    ("liquidity", "production"): ("st0x/liquidity-client.nuon", "prod_client_secret"),
    ("liquidity", "staging"): ("st0x/liquidity-client.nuon", "staging_client_secret"),
    ("issuance", "production"): ("st0x/issuance-client.nuon", "client_secret"),
}


def missing_secret(client: str, env: str) -> Optional[str]:
    """Names the empty or missing secret for a client, reading only its length."""
    rel, key = SECRET_KEYS[(client, env)]
    proc = subprocess.run(
        ["nu", "-c", f"open '{CONFIG / rel}' | get -i {key} | default '' | str length"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or proc.stdout.strip() in ("", "0"):
        return f"{key} in ~/.config/{rel}"
    return None


def ops_login(run: Run, client: str, env: str) -> bool:
    missing = missing_secret(client, env)
    if missing:
        run.record(f"{client} {env} sign-in", "server", f"failed (empty {missing}; no prompt sent)")
        return False
    token = CONFIG / f"st0x-{client}-client/oauth-{env}.json"
    before = token.stat().st_mtime_ns if token.exists() else None
    code = run.command([
        "python3", str(HELPERS / "zulip_ops_client_login.py"),
        "--client", client, "--env", env, "--force",
        "--transport", "telegram",
        "--telegram-env", TELEGRAM_ENV,
    ])
    if code == 0:
        run.record(f"{client} {env} sign-in", "server", "ok")
        return True
    # The helper also runs a read-only check after the sign-in. If the new
    # refresh token was saved, the sign-in worked and only that check failed
    # (for example a 503 from the bot); the verify rows report the bot.
    if not run.dry_run and token.exists() and token.stat().st_mtime_ns != before:
        run.record(f"{client} {env} sign-in", "server", "ok")
        run.log(f"    note: signed in, but the client's own check failed (helper exit {code})")
        return True
    run.record(f"{client} {env} sign-in", "server", f"failed (helper exit {code})")
    return False


def copy_private(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
        shutil.copyfileobj(inp, out)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)


def server_copies(run: Run) -> None:
    for src_rel, dst_rel in LOCAL_COPIES:
        src, dst = CONFIG / src_rel, CONFIG / dst_rel
        if not src.is_file():
            run.record(f"copy {dst_rel}", "server", "skipped (source missing)")
            continue
        if not run.dry_run:
            copy_private(src, dst)
        run.record(f"copy {dst_rel}", "server", "ok")


# The ops checks run the nushell wrappers, which fetch the client's default
# branch and build it, so the first run of a day can take minutes. A client
# with no cached sign-in would open a browser sign-in and wait forever, so a
# check runs only when its cache file exists, and under a time limit.
CHECK_TIMEOUT_SECONDS = 20 * 60


def ops_checks() -> list[tuple[str, str, dict[str, str], str]]:
    """(name, nushell command, extra env, cache file under CONFIG)."""
    checks = []
    for env in ("production", "staging"):
        checks.append((f"liquidity {env}", f"st0x-liquidity-client --env {env} read resource health", {},
                       f"st0x-liquidity-client/oauth-{env}.json"))
        checks.append((f"alpaca gateway {env}", f"st0x-liquidity-client --env {env} alpaca market-status",
                       {ALPACA_ENV[env]: ALPACA_URL[env]}, f"st0x-liquidity-client/oauth-alpaca-{env}.json"))
        checks.append((f"issuance {env}", f"st0x-issuance-client --env {env} read orchestrator-health", {},
                       f"st0x-issuance-client/oauth-{env}.json"))
    return checks


def check_result(code: int) -> str:
    if code == 0:
        return "ok"
    if code == 124:
        return f"failed (no answer in {CHECK_TIMEOUT_SECONDS // 60} min)"
    if code == 77:
        return "failed (IAP refused the account, exit 77)"
    return f"failed (exit {code})"


def verify_server(run: Run) -> None:
    for account in (T0, S01):
        code = run.command(["gcloud", "auth", "print-access-token", f"--account={account}"], quiet=True)
        run.record(f"check gcloud {account}", "server", "ok" if code == 0 else "failed")
    code = run.command(["gcloud", "auth", "application-default", "print-access-token"], quiet=True)
    run.record("check ADC", "server", "ok" if code == 0 else "failed")
    for name, nu_command, env, cache in ops_checks():
        if not (CONFIG / cache).is_file():
            run.record(f"check {name}", "server", "failed (not signed in: no cached token)")
            continue
        code = run.command(["nu", "-l", "-c", f"{nu_command} | ignore"], env=env, quiet=True,
                           timeout=CHECK_TIMEOUT_SECONDS)
        run.record(f"check {name}", "server", check_result(code))


def mac_copies(run: Run) -> bool:
    """Sends each cache file through the SSH stdin pipe, base64 inside a heredoc."""
    parts = ["umask 077"]
    sent = []
    for rel in MAC_FILES:
        src = CONFIG / rel
        if not src.is_file():
            run.record(f"copy {rel}", "mac", "skipped (missing on server)")
            continue
        data = "" if run.dry_run else base64.b64encode(src.read_bytes()).decode()
        dst = f'"$HOME/.config/{rel}"'
        parts += [
            f'mkdir -p "$(dirname {dst})"',
            f"base64 -D > {dst}.tmp <<'B64'\n{data}\nB64",
            f"chmod 600 {dst}.tmp && mv {dst}.tmp {dst}",
        ]
        sent.append(rel)
    code = run.mac("\n".join(parts), quiet=True)
    for rel in sent:
        run.record(f"copy {rel}", "mac", "ok" if code == 0 else f"failed (ssh exit {code})")
    return code == 0


MAC_GCLOUD_IMPORT = r'''
import base64, json, os, sqlite3, sys
rows = json.loads(base64.b64decode(sys.stdin.read()))
home = os.path.expanduser("~/.config/gcloud")
os.makedirs(home, exist_ok=True)
creds = sqlite3.connect(os.path.join(home, "credentials.db"))
creds.execute("CREATE TABLE IF NOT EXISTS credentials (account_id TEXT PRIMARY KEY, value BLOB)")
for account, value in rows:
    creds.execute("INSERT OR REPLACE INTO credentials VALUES (?, ?)", (account, value))
creds.commit()
tokens_path = os.path.join(home, "access_tokens.db")
if os.path.exists(tokens_path):
    tokens = sqlite3.connect(tokens_path)
    try:
        for account, _ in rows:
            tokens.execute("DELETE FROM access_tokens WHERE account_id = ?", (account,))
        tokens.commit()
    except sqlite3.Error:
        pass
os.chmod(os.path.join(home, "credentials.db"), 0o600)
'''


def mac_gcloud(run: Run) -> None:
    """Copies the two accounts' gcloud credentials to the Mac; falls back to Telegram logins there."""
    accounts = (T0, S01)
    copied = False
    if not run.dry_run:
        db = sqlite3.connect(CONFIG / "gcloud/credentials.db")
        rows = db.execute(
            "SELECT account_id, value FROM credentials WHERE account_id IN (?, ?)", accounts
        ).fetchall()
        db.close()
        if len(rows) == 2:
            payload = base64.b64encode(json.dumps(rows).encode()).decode()
            importer = base64.b64encode(MAC_GCLOUD_IMPORT.encode()).decode()
            script = (
                f"echo {payload} | python3 -c \"$(echo {importer} | base64 -D)\" && "
                f"gcloud config set account {T0} >/dev/null 2>&1"
            )
            copied = run.mac(script, quiet=True) == 0
    run.record("gcloud credentials copy", "mac", "ok" if copied else "failed")

    for account in accounts:
        ok = copied and run.mac(f"gcloud auth print-access-token --account={account} >/dev/null 2>&1", quiet=True) == 0
        if ok:
            run.record(f"check gcloud {account}", "mac", "ok")
            continue
        run.log(f"[mac] gcloud {account} did not work from the copy; logging in on the Mac over Telegram")
        gcloud_login(run, account, update_adc=False, host="mac", remote=True)
    run.mac(f"gcloud config set account {T0} >/dev/null 2>&1", quiet=True)


def verify_mac(run: Run) -> None:
    code = run.mac("gcloud auth application-default print-access-token >/dev/null 2>&1", quiet=True)
    run.record("check ADC", "mac", "ok" if code == 0 else "failed")
    for name, nu_command, env, cache in ops_checks():
        exports = "".join(f"export {k}={v}; " for k, v in env.items())
        code = run.mac(
            f'test -s "$HOME/.config/{cache}" || exit 3\n'
            f"{exports}nu -l -c '{nu_command} | ignore' </dev/null >/dev/null 2>&1",
            quiet=True, timeout=CHECK_TIMEOUT_SECONDS,
        )
        run.record(f"check {name}", "mac",
                   "failed (not signed in: no cached token)" if code == 3 else check_result(code))


def loopyloupe(run: Run) -> None:
    code = run.mac(f"/usr/bin/open '{LOOPYLOUPE}'", quiet=True)
    run.record("Loopyloupe sign-in", "mac",
               "opened in the browser, sign in there" if code == 0 else f"failed to open (ssh exit {code})")


def ipv6_on() -> bool:
    out = subprocess.run(["ip", "-6", "addr", "show", "scope", "global"],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def is_ok(result: str) -> bool:
    return result == "ok" or result.startswith("opened")


def report(run: Run, bot: Optional[TelegramBot]) -> int:
    bad = [(c, h, r) for c, h, r in run.results if not is_ok(r)]
    summary = f"Daily logins {dt.date.today().isoformat()}: {len(run.results) - len(bad)} ok, {len(bad)} not ok."
    lines = [summary, "", "| Host | Credential | Result |", "|---|---|---|"]
    lines += [f"| {h} | {c} | {r} |" for c, h, r in run.results]
    lines += ["", f"Log: `{run.log_path}` on juan-dev-server."]
    run.log("\n".join(lines))
    if bot is not None and not run.dry_run:
        rows = "\n".join(f"{'✅' if is_ok(r) else '❌'} {h} · {c}: {r}" for c, h, r in run.results)
        text = (f"<b>{html.escape(summary)}</b>\n\n<pre>{html.escape(rows)}</pre>\n"
                f"Log: <code>{html.escape(str(run.log_path))}</code>")
        try:
            bot.send_html(text[:4096])
        except TelegramError as error:
            run.log(f"could not send the report to Telegram: {error}")
    return 0 if not bad else 1


def confirm(run: Run, bot: TelegramBot, logins: list[str], hours: float) -> bool:
    """Asks on Telegram and waits for "go". Returns False on "skip" or no answer."""
    deadline = (dt.datetime.now() + dt.timedelta(hours=hours)).strftime("%H:%M")
    prompt = bot.dm(
        f"**Daily logins ready.** {len(logins)} sign-ins: {', '.join(logins)}.\n\n"
        f"Reply `go` when you are at your phone, or `skip`. Nothing starts before you "
        f"reply. Waiting until {deadline}."
    )
    run.log(f"--- confirm: asked on Telegram, waiting until {deadline}")
    answer = bot.wait_for_word(prompt, {"go", "skip"}, timeout=hours * 3600)
    if answer is None:
        bot.dm(f"No reply by {deadline}. Skipped today's logins.")
        run.record("confirmation", "server", f"skipped (no reply in {hours:g} h)")
        return False
    if answer[1] == "skip":
        bot.dm("Skipped today's logins.")
        run.record("confirmation", "server", "skipped (you replied skip)")
        return False
    bot.dm(f"Starting. The sign-in requests come one at a time: {', '.join(logins)}.")
    run.log("--- confirm: go")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma list of steps: " + ",".join(STEPS) + ", or 'mac'")
    parser.add_argument("--skip-mac", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-confirm", action="store_true",
                        help="start at once; for runs Juan starts himself")
    parser.add_argument("--confirm-hours", type=float, default=CONFIRM_HOURS)
    args = parser.parse_args()

    steps = STEPS
    if args.only:
        wanted = set(args.only.split(","))
        if "mac" in wanted:
            wanted |= MAC_STEPS
        unknown = wanted - set(STEPS) - {"mac"}
        if unknown:
            parser.error(f"unknown steps: {', '.join(sorted(unknown))}")
        steps = [s for s in STEPS if s in wanted]
    if args.skip_mac:
        steps = [s for s in steps if s not in MAC_STEPS]

    os.umask(0o077)
    run = Run(args.dry_run)
    try:
        bot = TelegramBot(TELEGRAM_ENV)
        bot.connectivity_gate()
    except TelegramError as error:
        run.record("Telegram bot", "server", f"failed ({error})")
        return report(run, None)
    if ipv6_on():
        run.record("IPv6 check", "server", "failed (IPv6 is on; gcloud-login forbids it)")
        return report(run, bot)

    logins = [LOGIN_NAMES[s] for s in steps if s in LOGIN_NAMES]
    if logins and not args.no_confirm and not args.dry_run:
        try:
            if not confirm(run, bot, logins, args.confirm_hours):
                report(run, None)  # the skip message already went to Telegram
                return 0
        except TelegramError as error:
            run.record("confirmation", "server", f"failed ({error})")
            return report(run, None)

    active = subprocess.run(["gcloud", "config", "get-value", "account"],
                            capture_output=True, text=True).stdout.strip() or T0

    actions: dict[str, Callable[[], object]] = {
        "server-gcloud-t0": lambda: gcloud_login(run, T0, True, "server", False),
        "server-gcloud-s01": lambda: gcloud_login(run, S01, False, "server", False),
        "liquidity-production": lambda: ops_login(run, "liquidity", "production"),
        "liquidity-staging": lambda: ops_login(run, "liquidity", "staging"),
        "issuance": lambda: ops_login(run, "issuance", "production"),
        "server-copies": lambda: server_copies(run),
        "verify-server": lambda: verify_server(run),
        "mac-copies": lambda: mac_copies(run),
        "mac-gcloud": lambda: mac_gcloud(run),
        "verify-mac": lambda: verify_mac(run),
        "loopyloupe": lambda: loopyloupe(run),
    }
    mac_reachable = True
    for step in steps:
        if step in MAC_STEPS:
            if mac_reachable and run.mac("true", quiet=True) != 0:
                mac_reachable = False
            if not mac_reachable:
                run.record(step, "mac", "skipped (Mac not reachable over SSH; asleep or offline)")
                continue
        run.log(f"--- {step}")
        try:
            actions[step]()
        except Exception as error:  # report and continue with the next step
            run.record(step, "mac" if step in MAC_STEPS else "server", f"failed ({type(error).__name__})")
        if step == "server-gcloud-s01":
            subprocess.run(["gcloud", "config", "set", "account", active],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return report(run, bot)


if __name__ == "__main__":
    sys.exit(main())
