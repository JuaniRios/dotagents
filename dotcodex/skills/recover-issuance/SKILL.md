---
name: recover-issuance
description: "Use when the user asks to diagnose or recover stuck issuance-bot transactions in production, including stuck requests, recovery endpoints, exact on-chain burn matching, and carefully confirmed force-completion."
---

# recover-issuance

Codex-native port of the former Claude slash command `recover-issuance`.

Diagnose and recover stuck issuance-bot transactions on production. This
workflow handles financial operations and production state, so it is
intentionally strict.

## Host Resolution

Resolve the production host from, in order:
1. An explicit host argument from the user.
2. The `ISSUANCE_HOST` entry in `~/Github/dotagents/.env`.

Only read the host key needed for this workflow. Do not print secrets. Remote
API keys, RPC URLs, and database URLs must be read only inside the remote SSH
command that needs them, and must not be echoed.

## SSH Connection Reuse (do this first)

The server rate-limits new SSH connections. Opening a fresh `ssh` per command
trips sshd throttling and produces `Connection refused` partway through. Before
running any remote command, open ONE multiplexed master connection and route
every later `ssh` through it:

- Open the master once with `ControlMaster=auto`, `ControlPersist`, and a fixed
  `ControlPath` (e.g. `/tmp/issuance-cm.sock`).
- Pass that same `-o ControlPath=...` on every subsequent `ssh` so they reuse
  the single TCP connection instead of opening a new one.
- Batch remote work: combine multiple queries/curls into ONE `ssh` invocation
  and loop over aggregate IDs inside the remote shell — never one `ssh` per
  item.
- Close the master with `ssh -O exit -o ControlPath=...` when done.

If you still hit `Connection refused`, wait for the throttle to clear, re-open
the master, and reduce the number of separate `ssh` calls.

## Workflow

1. Identify deployed version.
   - SSH to the host (through the multiplexed master).
   - Inspect the running Docker image tag or service metadata.
   - The deployed image is the latest commit on `master` for the issuance repo,
     so `force-complete`/`close` are available unless the running tag is visibly
     behind `master`. Reference the deployed tag in findings, not an unrelated
     local branch.

2. Fetch stuck issuance records.
   - Query the admin stuck endpoint using the remote `ISSUER_API_KEY`.
   - Capture transaction IDs, user/account identifiers, amounts, token symbols,
     chain IDs, timestamps, and current status.
   - Present a concise table before attempting recovery.

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

- Never force-complete, close, or otherwise finalize a transaction without
  explicit user confirmation in the current session.
- Never treat approximate amount/address/token matches as sufficient burn
  evidence.
- Never use floating-point arithmetic for financial amounts.
- Never print API keys, RPC URLs, database URLs, private keys, or bearer tokens.
- Never mutate production state while inspecting a different deployed version
  than the one you described.
- Never open a fresh SSH connection per command; reuse one multiplexed master
  connection and batch remote work to avoid the server's connection rate limit.
