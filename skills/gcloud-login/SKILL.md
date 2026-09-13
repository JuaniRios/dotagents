---
name: gcloud-login
description: >
  Restore expired Google Cloud CLI and ADC user credentials through a
  phone-assisted, no-browser login coordinated over a private Juan-Bot Zulip
  DM. Use after gcloud reports expired credentials, reauthentication failure,
  or inability to prompt, and when asked to authenticate gcloud remotely.
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

- Google account: `juan@t0trade.com`
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

## Procedure

1. Disable shell tracing with `set +x` and never re-enable it.
2. If this follows another command, confirm its failure is authentication or
   reauthentication—not IAM, IAP, API enablement, networking, or quota.
3. Confirm the helper and `~/.zuliprc-bot` are readable. Do not print either
   credential file or any environment values.
4. Run the helper and allow it to wait for up to 15 minutes:

   ```bash
   set +x
   python3 "$HOME/Github/dotagents/skills/gcloud-login/scripts/zulip_remote_login.py" \
     --account juan@t0trade.com \
     --recipient juan@rainlang.xyz \
     --zulip-config "$HOME/.zuliprc-bot" \
     --zulip-delete-config "$HOME/.zuliprc-personal" \
     --update-adc
   ```

   The helper uses `--force --no-launch-browser` deliberately. `--force`
   prevents an unattended local password prompt and guarantees the phone-link
   flow; `--no-launch-browser` prevents GUI use on the target host.
5. Tell the user only that a private Juan-Bot DM was sent and that the helper
   is waiting. Do not repeat the authorization URL in agent chat.
6. Wait for the helper to finish. It polls Zulip every 5 seconds, performs the
   connectivity gate, generates a unique request ID, accepts only a newer
   code-only private DM from Juan, and never writes the authorization code to
   stdout/stderr. After gcloud succeeds, it permanently deletes the exact
   request and reply by ID.
7. On success, independently verify without printing tokens:

   ```bash
   gcloud auth print-access-token --account=juan@t0trade.com >/dev/null
   gcloud auth application-default print-access-token >/dev/null
   ```

8. Report the active account from `gcloud auth list`; do not report tokens,
   authorization codes, OAuth URLs, credential paths, or credential contents.
9. If invoked because a read-only operation failed, retry it exactly once. If
   it still fails, report the exact non-secret error and stop.

## Zulip exchange

The bot DM contains the target hostname, Google account, unique request ID,
authorization link, 15-minute deadline, and the reply format:

```text
AUTHORIZATION_CODE
```

The reply must be a private DM from `juan@rainlang.xyz` to Juan-Bot and must
contain only the copied Google authorization code. The helper only considers
messages newer than its bot request, extracts the code and reply message ID
inside its own process, disables PTY echo, and submits the code once. Only
after gcloud succeeds, it permanently deletes the reply and bot request by
their exact IDs, then discards the code from memory. The agent must never
fetch, quote, summarize, or display that Zulip message. Run at most one gcloud
login request at a time across the two hosts so a code-only reply is
unambiguous. Never use a public or private channel topic for this exchange.

## Failure handling

- Missing helper, `gcloud`, Python, `zulipctl`, or bot credentials: report the
  missing prerequisite without inspecting credential material.
- Zulip connectivity or recipient mismatch: stop before starting Google login.
- No Google URL, gcloud exits early, or Google rejects the code: send a
  non-secret failure DM, report the sanitized error, and stop.
- Timeout: terminate only the helper-owned gcloud child, send a timeout DM, and
  start a new request on the next invocation. Never reuse a request ID or code.
- Cleanup failure after successful Google authentication: report that login
  succeeded but the exact Zulip messages could not be permanently deleted; do
  not claim cleanup succeeded or retry deletion against broader targets.
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
   helper may delete the exact request and reply message IDs after success.
5. Never use this skill to bypass 2FA, organization session controls, or other
   access policies. The user completes Google authentication themselves.
6. Authentication recovery does not authorize a previously failed mutation to
   be retried.
