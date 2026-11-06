---
name: daily-logins
description: >
  Refresh every login Juan's agents need, once a day: gcloud CLI and ADC for
  T0 (juan@t0trade.com) and S01 (juan@s01issuer.com), and the IAP sign-ins of
  st0x-liquidity-client, the T0 Alpaca gateway (t0-humans), and
  st0x-issuance-client, on both juan-dev-server and the Mac
  (juans-macbook-pro), plus a fresh Loopyloupe sign-in in the Mac browser.
  Runs from a systemd timer on juan-dev-server at 08:30 America/Montevideo.
  Use when asked to run the daily logins, refresh all logins or tokens, sign
  both machines in again, or when the timer's run failed.
---

# /daily-logins

One run signs everything in again with as few phone prompts as Google allows.
Each Google sign-in goes through the `gcloud-login` skill's Zulip helpers:
Juan-Bot sends a private DM, Juan completes the sign-in on his phone and
replies, and the helper deletes the exchange. This skill never handles a
code, URL, or token itself; its script moves token files without reading them
into output.

## How few prompts, and why not one per org

A refresh token belongs to one OAuth client. A gcloud token cannot sign in to
an IAP client, and each IAP Desktop client is a separate OAuth client that
needs its own consent. What can be shared is shared:

| Sign-in on the server | Also covers, by file copy |
|---|---|
| gcloud T0 with `--update-adc` | T0 ADC; Mac gcloud T0 and ADC |
| gcloud S01 | Mac gcloud S01 |
| liquidity production | Alpaca gateway production (the gateway admits the liquidity client; checked 2026-11-06); the Mac |
| liquidity staging | Alpaca gateway staging; the Mac |
| issuance production | issuance staging (one OAuth client for both; checked 2026-11-06); the Mac |

That is **5 phone prompts a day**, plus one browser sign-in on the Mac for
Loopyloupe. Every login is forced daily, also when the old one still works.
A copied refresh token stays bound to the account and client it was issued
for, and Google still enforces Workspace session controls on it.

Mac gcloud: gcloud has no supported import of a user login, so the script
copies the two accounts' rows of `~/.config/gcloud/credentials.db` into the
Mac's database and drops their cached access tokens there. If an account then
fails its check on the Mac, the script falls back to a Zulip login on the Mac
(the helper runs there, so the Mac needs the helpers and both Zulip configs);
that makes up to 7 prompts.

## Prerequisites

- Server: `gcloud`, `python3`, `zulipctl`, `nu`, the nushell `st0x-*-client`
  wrappers (`nix-darwin-config` `home/shell.nix`) with
  `~/.config/st0x/{liquidity,issuance}-client.nuon`, `~/.zuliprc-bot` and
  `~/.zuliprc-personal` (mode 600).
- Mac: the same client wrappers and `.nuon` files for the Mac checks.
- SSH from the server to the Mac: alias `mac-logins` (server
  `home/server.nix`), key `~/.ssh/id_daily_logins`, which the Mac authorizes
  with a full shell (`modules/darwin/clipboard-ssh.nix`). The other server
  key, `id_main`, may only run `pbcopy` on the Mac; never use it for this.
- Timer: `systemd.user.timers.daily-logins` in the server's `home/server.nix`
  (change it with the `nix-darwin` skill).

## Run it

The timer runs the script with no agent. To run it by hand on the server:

```bash
set +x
python3 ~/Github/dotagents/skills/daily-logins/scripts/daily_logins.py
```

- `--only <step,...>`: run some steps; `mac` means every Mac step. Steps:
  `server-gcloud-t0`, `server-gcloud-s01`, `liquidity-production`,
  `liquidity-staging`, `issuance`, `server-copies`, `verify-server`,
  `mac-copies`, `mac-gcloud`, `verify-mac`, `loopyloupe`.
- `--skip-mac`: server only.
- `--dry-run`: list the commands; send nothing, copy nothing.

From an agent session, start it in the background and wait: each login can
wait 15 to 20 minutes for Juan's reply. Tell the user that Juan-Bot DMs are
coming, one at a time, and which ones (gcloud T0, gcloud S01, liquidity
production, liquidity staging, issuance).

## What a run does

1. Stops at once if the server has a global IPv6 address (`gcloud-login`
   forbids IPv6).
2. Logs in, one Zulip exchange at a time: gcloud T0 with ADC, gcloud S01
   (then sets the active account back), then `--force` sign-ins of liquidity
   production, liquidity staging, and issuance production.
3. Copies on the server, mode 600: liquidity `oauth-production.json` and
   `oauth-staging.json` to `oauth-alpaca-production.json` and
   `oauth-alpaca-staging.json`; issuance `oauth-production.json` to
   `oauth-staging.json`.
4. Checks on the server, read-only, printing nothing: `gcloud auth
   print-access-token` per account, ADC, and per environment
   `read resource health`, `alpaca market-status` (with `T0_ALPACA_<ENV>_URL`),
   and issuance `read orchestrator-health`. A check whose cache file is missing
   reports "not signed in" instead of starting a browser sign-in; each has a
   20-minute limit because the wrappers build the client first.
5. Mac, over `mac-logins`, only if it answers: copies the six client cache
   files and the ADC file through the SSH stdin pipe, imports the gcloud
   credentials, runs the same checks, and opens
   `https://loopyloupe.t0trade.com/?gcp-iap-mode=CLEAR_LOGIN_COOKIE`, which
   drops the IAP session and starts a fresh sign-in in the browser. The script
   cannot see that sign-in, so it reports "opened", never "done". If the Mac is
   asleep, every Mac step reports "skipped"; run `--only mac` later.
6. Reports: one Juan-Bot DM to Juan with a table of host, credential, and
   result, and the same table on stdout and in
   `~/Github/dotagents/data/daily-logins/<date>.log`. A failed step does not
   stop the run. The exit code is 0 only when every row is ok.

## Reading the results

- `failed (IAP refused the account, exit 77)` after a good sign-in is an
  access problem (group membership, PAM), not a login problem. Report it.
- `not signed in` on a check: the sign-in or copy for that client failed
  earlier in the run; read its row.
- A helper failure: read the log lines under that step. The `gcloud-login`
  skill's "Failure handling" applies.

## Hard rules

1. Every rule in the `gcloud-login` skill's "Hard rules" applies.
2. Never print, log, read into chat, or pass on a command line a token,
   code, OAuth URL, or credential file. Copies go file to file or through an
   SSH stdin pipe, with mode 600.
3. One Zulip login exchange at a time, across both hosts.
4. Never retry a failed login in a loop. Report it; the next run tries again.
5. This skill refreshes sign-ins only. It grants no access and never runs a
   write or capital command.
