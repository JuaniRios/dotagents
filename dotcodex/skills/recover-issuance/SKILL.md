---
name: recover-issuance
description: "Use when the user asks to diagnose or recover stuck issuance-bot transactions in production, or to check whether the issuance bot is healthy after a deploy. Uses the managed Nushell `prod-remote` accessor for safe production access. Covers stuck requests, recovery endpoints, exact on-chain burn matching, carefully confirmed force-completion, and a post-deploy health check (deploy revision, crash-loop, signer, view rebuilds, backfill and vault coverage, Alpaca reachability)."
---

# recover-issuance

Codex-native port of the former Claude slash command `recover-issuance`.

Diagnose and recover stuck issuance-bot transactions on production. This
workflow handles financial operations and production state, so it is
intentionally strict.

## Deployment Layout (NixOS)

Production runs on a **NixOS** box (`st0x-issuance-nixos`), deployed via
`deploy-rs` from the `~/Github/st0x.issuance` repo — NOT the old Docker/Ubuntu
droplet. Do not assume Docker paths or on-box scripting tools:

- No `docker`: the bot is a systemd unit `st0x-issuance.service`, listening on
  `:8000`. There is no container image tag; the deployed git revision is
  recorded at `/run/st0x/st0x-issuance.git-rev`.
- No `python3` or `jq` on the box: consume raw `curl` JSON, and run any Decimal
  arithmetic or pretty-printing locally on your workstation.
- Database: `/mnt/data/issuance.db`.
- The unit runs from a **per-service** nix profile,
  `/nix/var/nix/profiles/per-service/st0x-issuance/`, which is versioned
  separately from the system generation. A system generation timestamp older
  than the service start time is normal and does not mean the deploy failed. To
  prove a deploy is a real new build rather than a no-op restart, list that
  profile's generations and compare the resolved store paths of the last two —
  different paths mean genuinely new code.
- Secrets: agenix-decrypted at `/run/agenix/st0x-issuance.env`. Read them only
  inside the remote SSH command that needs them; never echo them. Use the exact
  variable names and do not guess: `ISSUER_API_KEY`, `RPC_URL`,
  `ALPACA_API_BASE_URL` (note the `API_` infix — it is **not**
  `ALPACA_BASE_URL`), `ALPACA_API_KEY`, `ALPACA_API_SECRET`,
  `ALPACA_ACCOUNT_ID`, `ALPACA_IP_RANGES`. A misspelled name expands to empty
  and `curl` reports `HTTP 000`, which looks identical to a credential or
  IP-allowlist outage. List the names (never the values) off the box before
  relying on them.
- New droplet after a rebuild ⇒ new host key/IP: if the managed accessor reports
  `Host key verification failed`, stop and tell the user the recorded host key
  must be updated. Do not bypass the accessor or retry with `ssh-keyscan`.
- Run remote `sqlite3` queries through a single-quoted heredoc piped to
  `bash -s` so SQL string literals survive shell quoting, rather than nesting
  double-quoted SQL inside another quoted remote-command argument.

## Managed Production Access (mandatory — do this first)

Use the `prod-remote` function from the user's managed Nushell config. It calls
`st0x-remote-identity`, which retrieves the approved 1Password identity into a
0600 cache and passes it as `SSH_IDENTITY` to the issuance flake's remote
helper. The helper decrypts the production host and uses that same identity for
SSH. This avoids offering every key in the SSH agent and triggering fail2ban.

Agent tool shells are non-interactive and do not automatically expose Nushell
custom commands. From the issuance repo, load the generated config explicitly
inside its dev shell:

```bash
nu_config=$(nu -c '$nu.config-path')
REMOTE_COMMAND='<one batched remote command>' \
  nix develop --command nu -c \
  "source '$nu_config'; prod-remote \$env.REMOTE_COMMAND"
```

Treat `prod-remote` as the only production transport for this workflow:

- Never read `ISSUANCE_HOST`, decrypt `.remote-prod.age` yourself, call raw
  `ssh`, call `nix run .#prodRemote`, or inspect/try SSH-agent identities.
- Build the first useful diagnostic command before connecting. Do not run a
  separate connectivity probe and then reconnect for the real work.
- Batch the entire uninterrupted diagnostic phase into one accessor call. Loop
  over aggregate IDs inside the remote shell; never call the accessor once per
  item and never parallelize accessor calls.
- If that first accessor call fails, hangs, times out, or is refused, stop
  immediately and report the exact error. Do not retry or try alternate access
  until the user explicitly says access is restored.
- A later accessor call is allowed when the workflow genuinely pauses for the
  user's required confirmation before a mutating recovery action.

Remote API keys, RPC URLs, and database URLs must be read only inside the
remote command that needs them and must never be echoed.

## Workflow

1. Identify deployed version.
   - SSH to the host (through the multiplexed master).
   - Read the deployed git revision from `/run/st0x/st0x-issuance.git-rev` and
     the unit state via `systemctl show st0x-issuance.service` (systemd, not
     Docker).
   - The deployed build is the latest commit on `master` for the issuance repo,
     so `force-complete`/`close` are available unless the recorded revision is
     visibly behind `master`. Reference the deployed revision in findings, not
     an unrelated local branch.

2. Fetch stuck issuance records.
   - Query the admin stuck endpoint using the remote `ISSUER_API_KEY`.
   - Capture transaction IDs, user/account identifiers, amounts, token symbols,
     chain IDs, timestamps, and current status.
   - Present a concise table before attempting recovery.

2b. Run the health check when nothing is stuck, or when the question is about
   health rather than recovery.

   Trigger this whenever the stuck list comes back empty, or the user asks
   something health-shaped ("a new deploy just landed", "is everything
   working", "is the bot OK?"). An empty stuck list means there is nothing to
   *recover*; it does not mean the service is well. The stuck endpoint only
   reports aggregates already wedged in a known-bad state, and is silent about a
   service that crash-loops, signs with a dead key, cannot reach Alpaca, or
   never started watching a vault — which are the failures that have actually
   occurred in production. Do not report the bot healthy on an empty stuck list
   alone.

   Batch the whole check into one `ssh` call and verify each signal:

   - Deployed git revision matches the latest `master`.
   - `NRestarts` is `0` (a non-zero value means a crash-loop, historically from
     missing view migrations).
   - Zero ERROR/WARN entries in the journal since the service start timestamp.
   - Startup logged the signer coming up (Turnkey wallet initialized, signer
     backend resolved) — this catches a dead or unauthorized signing key.
   - Every view rebuild completed (receipt inventory, redemption, receipt
     burns).
   - Receipt backfill completed for every enabled asset, and its start block is
     near the chain head. A backfill starting millions of blocks back has caused
     a crash-loop before.
   - The number of distinct vaults being polled equals the asset count, so an
     asset cannot be registered but unwatched.
   - The poller's block cursor advances (~30 blocks/minute on Base, 2s blocks).

   Then confirm no aggregate is quietly non-terminal, querying the event store
   for each aggregate's latest event. Use these exact terminal sets, because an
   incomplete list produces false "stuck" alarms:

   - Redemption terminal: `TokensBurned`, `RedemptionClosed`,
     `BurnForceCompleted`, `ExistingBurnRecovered`. `ExistingBurnRecovered`
     applies to `Completed` in both the aggregate and the view — verify against
     the redemption source before treating it as unfinished.
   - Mint terminal: `MintCompleted`, `MintClosed`.

   Finally, confirm outbound Alpaca connectivity with a read-only account
   request, printing only the HTTP status code and the egress IP. A `401` here
   is invisible to the stuck endpoint until requests pile up. `200` means the
   credentials are valid and the egress IP is allowlisted; `HTTP 000` is almost
   always a misspelled variable name rather than an outage.

   Scan the journal *before* sending any unauthenticated probe. An
   unauthenticated request correctly returns 401 and emits a missing-API-key
   warning, which then appears in your own error scan and reads as a real fault.
   If you probe first, attribute those warnings to yourself in the report.

   Report the result as a pass/fail list, state which signals you actually
   verified, and say plainly that no recovery action was needed. If everything
   is green, say so without hedging.

3. Try normal recovery first.
   - Use the documented recover endpoint for each stuck transaction.
   - Record response status and body.
   - Re-fetch the stuck endpoint after each recovery attempt.
   - Do not jump to force-complete while a normal retry path is still plausible.

4. Investigate on-chain burn state when normal recovery does not clear a
   transaction.
   - Query the remote database for the issuance row and relevant chain metadata.
   - Use remote RPC/cast commands only with remote secrets scoped to the SSH
     session.
   - Use exact Decimal arithmetic for token amounts. Never use floating-point
     arithmetic for comparisons.
   - Match burns exactly by token, amount, address, chain, and transaction
     context. Near matches are evidence, not proof.

5. Force-complete only with explicit confirmation.
   Present:
   - transaction ID,
   - current stuck status,
   - exact burn evidence,
   - why normal recovery cannot complete it,
   - the exact force-complete command or endpoint call.
   Ask for explicit confirmation before running it.

6. Verify after any recovery or force-completion.
   - Re-query the stuck endpoint.
   - Check the specific transaction status.
   - Summarize whether the transaction cleared, remains stuck, or changed state.

7. Final report.
   Include:
   - deployed version,
   - stuck transaction table,
   - actions taken,
   - exact on-chain evidence used,
   - final status,
   - unresolved risks or next manual steps.

## Hard Rules

- Use only the managed Nushell `prod-remote` accessor for production access.
  Raw `ssh`, direct flake remote apps, host-file decryption, and SSH-agent key
  discovery are forbidden.
- Make one batched accessor call per uninterrupted phase. After any failed
  accessor call, stop without retries until the user explicitly confirms
  access is restored.
- Never force-complete, close, or otherwise finalize a transaction without
  explicit user confirmation in the current session.
- Never treat approximate amount/address/token matches as sufficient burn
  evidence.
- Never use floating-point arithmetic for financial amounts.
- Never print API keys, RPC URLs, database URLs, private keys, or bearer tokens.
- Never mutate production state while inspecting a different deployed version
  than the one you described.
- Never assume the old Docker/Ubuntu layout; the box is NixOS/systemd with no
  `docker`, `python3`, or `jq`, DB at `/mnt/data/issuance.db`, and secrets at
  `/run/agenix/st0x-issuance.env`.
- Never call the remote accessor once per command or item; batch remote work in
  the accessor's single SSH session to avoid the server's connection limits.
- Never treat an empty stuck list as proof the service is healthy. Run the
  health check and report what you actually verified.
- Never report a production fault — bad credentials, a stuck aggregate, a failed
  deploy — without first ruling out the self-inflicted causes: a misspelled
  environment variable name, an incomplete terminal-event list, the per-service
  versus system nix profile, and warnings emitted by your own unauthenticated
  probes.
