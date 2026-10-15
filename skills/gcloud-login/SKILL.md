---
name: gcloud-login
description: >
  Restore expired Google Cloud CLI and ADC user credentials through a
  phone-assisted, no-browser login coordinated over a private Juan-Bot Zulip
  DM. Use after gcloud reports expired credentials, reauthentication failure,
  or inability to prompt, and when asked to authenticate gcloud remotely.
  Handles both Google accounts: juan@t0trade.com (T0) and juan@s01issuer.com
  (S01).
allowed-tools: Bash(gcloud:*), Bash(zulipctl:*), Bash(python3:*), Bash(test:*), Bash(set:*)
---

# /gcloud-login

Restore `gcloud` authentication on either configured host without requiring a
browser on that host. A helper starts Google's browser-only-device flow, sends
the authorization link privately from Juan-Bot to Juan on Zulip, waits for the
correlated one-time authorization code, feeds it directly to the waiting
`gcloud` PTY, and verifies the result.

This is remote-assisted authentication, not unattended workload identity. The
user must complete Google authentication on their phone and reply to the bot.

After successful authentication, retry the original read-only command exactly
once. Never retry a mutation automatically.

## Fixed identities and prerequisites

- Google accounts, chosen by the project the failed command targeted:
  - `juan@t0trade.com` for T0 projects (`t0-*`). This is the default and
    the account gcloud should stay active on.
  - `juan@s01issuer.com` for S01 projects (`s01-*`, such as `s01-issuance`).
  If the target is ambiguous, ask which account before starting a login.
- Zulip actor: Juan-Bot via `~/.zuliprc-bot`
- Zulip recipient: `juan@rainlang.xyz`
- Zulip cleanup identity: Juan via `~/.zuliprc-personal`
- Helper: `~/Github/dotagents/skills/gcloud-login/scripts/zulip_remote_login.py`
- `gcloud`, `zulipctl`, and `python3` must be installed on the target host.
- Both Zulip credential files must exist with mode `0600`; Juan-Bot must be
  able to DM the recipient, and Juan must be allowed to delete his own and his
  owned bot's direct messages.

The shared nix-darwin/home-manager configuration installs `gcloud`,
`zulipctl`, and Python on both `juanrios-m2` and `juan-dev-server`. Zulip bot
credentials remain host-local and must never enter Nix, Git, or tool output.

## Never use IPv6

Never use IPv6. On this network IPv6 connections hang, and Python tools
(`gcloud`, `zulipctl`) try IPv6 first, so they stall until a timeout and
then report a vague error. Before any `gcloud` or Zulip call, turn IPv6
off on every network service:

```bash
networksetup -listallnetworkservices | tail -n +2 | sed 's/^\*//' |
  while IFS= read -r s; do networksetup -setv6off "$s"; done
```

This is macOS. On a Linux host, check `ip -6 addr show scope global`; if
it lists an address, report that IPv6 is on and stop. Do not turn IPv6
back on.

## Procedure

1. Disable shell tracing with `set +x` and never re-enable it.
   Then turn IPv6 off as described in "Never use IPv6".
2. If this follows another command, confirm its failure is authentication or
   reauthentication—not IAM, IAP, API enablement, networking, or quota.
3. Confirm the helper and `~/.zuliprc-bot` are readable. Do not print either
   credential file or any environment values.
4. Record the active account (`gcloud config get-value account`), then run
   the helper with the chosen `ACCOUNT` and allow it to wait for up to 15
   minutes:

   ```bash
   set +x
   python3 "$HOME/Github/dotagents/skills/gcloud-login/scripts/zulip_remote_login.py" \
     --account "$ACCOUNT" \
     --recipient juan@rainlang.xyz \
     --zulip-config "$HOME/.zuliprc-bot" \
     --zulip-delete-config "$HOME/.zuliprc-personal" \
     --update-adc
   ```

   The helper uses `--force --no-launch-browser` deliberately. `--force`
   prevents an unattended local password prompt and guarantees the phone-link
   flow; `--no-launch-browser` prevents GUI use on the target host.

   Application Default Credentials hold one account at a time. Pass
   `--update-adc` for `juan@t0trade.com`. For `juan@s01issuer.com`, pass it
   only when the task needs S01 ADC (for example, a client library rather
   than the `gcloud` CLI), and say that this replaces the T0 ADC until the next
   T0 login.
5. Tell the user only that a private Juan-Bot DM was sent and that the helper
   is waiting. Do not repeat the authorization URL in agent chat.
6. Wait for the helper to finish. It polls Zulip every 5 seconds, performs the
   connectivity gate, generates a unique request ID, accepts only a newer
   code-only private DM from Juan, and never writes the authorization code to
   stdout/stderr. When it finishes, on every outcome, it permanently deletes
   the exact request and every code-only reply by ID, and reports how many
   login messages it deleted.
7. On success, independently verify without printing tokens:

   ```bash
   gcloud auth print-access-token --account="$ACCOUNT" >/dev/null
   gcloud auth application-default print-access-token >/dev/null  # only with --update-adc
   ```

   `gcloud auth login` makes the new account active. After an S01 login,
   restore the account recorded in step 4 with
   `gcloud config set account <recorded account>`, so T0 commands keep
   working. Pass `--account=juan@s01issuer.com` on every S01 `gcloud` command.
8. Report the active account from `gcloud auth list`; do not report tokens,
   authorization codes, OAuth URLs, credential paths, or credential contents.
9. If invoked because a read-only operation failed, retry it exactly once. If
   it still fails, report the exact non-secret error and stop.

## Zulip exchange

The bot DM starts with which login code it needs, `T0 login code needed`
or `S01 login code needed`, so the user signs in with the right account.
It also contains the target hostname, Google account, unique request ID,
authorization link, 15-minute deadline, and the reply format:

```text
AUTHORIZATION_CODE
```

The reply must be a private DM from `juan@rainlang.xyz` to Juan-Bot and must
contain only the copied Google authorization code. The helper only considers
messages newer than its bot request, extracts the code and reply message ID
inside its own process, disables PTY echo, and submits the code once. The bot
DM is the only message the helper sends: it sends no success, failure, or
timeout DM and reports the result on its own output instead.

When the helper finishes, on every outcome (success, rejected code, timeout,
error, Ctrl-C, or `SIGTERM`/`SIGHUP`), it permanently deletes these messages
by their exact IDs with the Juan identity:

- the bot request;
- the reply it submitted;
- every other code-only reply from Juan after the request, including a late
  or rejected code.

It ignores further interrupts until cleanup is done, then discards the code
from memory. It never deletes by search or by a broader target. The agent
must never fetch, quote, summarize, or display that Zulip message. Run at most
one gcloud login request at a time across the two hosts so a code-only reply is
unambiguous. Never use a public or private channel topic for this exchange.

## Failure handling

- Missing helper, `gcloud`, Python, `zulipctl`, or bot credentials: report the
  missing prerequisite without inspecting credential material.
- `Zulip command failed` or a hang: check IPv6 first (see "Never use
  IPv6"), turn it off, and run the helper again.
- Zulip connectivity or recipient mismatch: stop before starting Google login.
- No Google URL, gcloud exits early, or Google rejects the code: delete the
  login messages, report the sanitized error, and stop. Send no failure DM.
- Timeout or interrupt: terminate only the helper-owned gcloud child, delete
  the login messages, and report the sanitized error. Send no timeout DM.
  Start a new request on the next invocation. Never reuse a request ID or code.
- A code-only reply that arrives after cleanup ends is not deleted; a manual
  sweep of the DM by exact ID must remove it.
- Cleanup failure: the helper exits non-zero and reports how many messages it
  could not delete, and whether it could not list later replies or got no
  request message ID. After successful Google authentication, report that
  login succeeded but cleanup failed. Do not claim cleanup succeeded or retry
  deletion against broader targets.
- If gcloud refreshes both requested credential stores but its macOS process
  does not finish exiting within 30 seconds, verify both token commands,
  terminate only that helper-owned process, and continue cleanup. Require both
  credential mtimes to have changed so an older valid token cannot be mistaken
  for this login succeeding.
- Wrong sender, public/channel message, non-code content, or reply predating
  the bot request: ignore it.
- IAM, permission, IAP, API enablement, network, or quota failure after login:
  authentication succeeded; report the separate authorization/runtime error.
- Never fall back to asking for a Google password or authorization code in
  agent chat.

## Hard rules

1. Never enable shell tracing.
2. Never print or expose OAuth URLs, access tokens, refresh tokens, passwords,
   authorization codes, Zulip API keys, or credential-file contents in agent
   chat or tool output.
3. Never pass secrets directly on a command line or store them in a file,
   environment variable, Nix store path, Git repository, or shell history.
4. Only the helper process may read the newer code-only authorization DM, and
   it may only feed that value to the helper-owned gcloud PTY once. Only the
   helper may delete the exact request and reply message IDs, and it must do
   so on every outcome.
7. The helper sends only the bot request DM. It never sends a status,
   failure, or timeout DM.
5. Never use this skill to bypass 2FA, organization session controls, or other
   access policies. The user completes Google authentication themselves.
6. Authentication recovery does not authorize a previously failed mutation to
   be retried.
