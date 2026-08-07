---
name: recover-issuance
allowed-tools: Bash(ssh:*), Bash(ssh-keyscan:*), Bash(curl:*), Bash(python3:*), Bash(sqlite3:*), Bash(cast:*), Bash(systemctl:*), Bash(grep:*), Bash(awk:*), Bash(cut:*), Bash(sed:*), Bash(git:*), Bash(paste:*), Read, AskUserQuestion
description: Check issuance-bot production health and recover stuck transactions (mints and redemptions). Calls /admin/stuck, attempts /admin/recover on each, searches on-chain for unrecorded burns, and presents a findings table. When nothing is stuck — or after a deploy, or when asked "is it working?" — runs a full health check (deploy rev, crash-loop, signer, view rebuilds, backfill and vault coverage, Alpaca reachability). Destructive actions (force-complete, close) require explicit user confirmation.
argument-hint: "[host]"
disable-model-invocation: true
---

Check and recover stuck issuance-bot transactions on the production server.

## Resolve host

Read the SSH target from `~/Github/dotagents/.env`:

```bash
grep "ISSUANCE_HOST" ~/Github/dotagents/.env | cut -d= -f2
```

If an argument was passed to this command, use it instead. If neither the file
nor an argument provides a host, tell the user:
"No host configured. Either pass it as an argument or add `ISSUANCE_HOST=root@<ip>` to `~/Github/dotagents/.env`."
and stop.

Set `DB=/mnt/data/issuance.db` for all commands below, then set up a
**multiplexed SSH connection** (next section) before running anything remote.

## Deployment layout (NixOS — read before running remote commands)

Production runs on a **NixOS** box (`st0x-issuance-nixos`), deployed via
`deploy-rs` from the `~/Github/st0x.issuance` repo. This is NOT the old
Docker/Ubuntu droplet, so the classic paths and tooling do not apply:

- **No `docker`** — the bot is a systemd unit `st0x-issuance.service`
  (`systemctl status st0x-issuance`), listening on `:8000`.
- **No `python3` or `jq` on the box** — consume raw JSON from `curl`; do any
  pretty-printing or `python3` Decimal math **locally** on your laptop.
- **DB**: `/mnt/data/issuance.db` (`DB` above).
- **Secrets**: agenix-decrypted at `/run/agenix/st0x-issuance.env` — read them
  only inside the remote SSH command that needs them. NOT
  `/mnt/volume_nyc3_02/.env`. The exact names matter; do not guess them:
  `ISSUER_API_KEY`, `RPC_URL`, `ALPACA_API_BASE_URL` (note the `API_` infix —
  **not** `ALPACA_BASE_URL`), `ALPACA_API_KEY`, `ALPACA_API_SECRET`,
  `ALPACA_ACCOUNT_ID`, `ALPACA_IP_RANGES`. A misspelled var expands to empty and
  `curl` returns `HTTP 000`, which reads exactly like a credential/allowlist
  outage — a false alarm that has cost a round-trip before. Confirm names with
  `grep -oE '^[A-Z_]*ALPACA[A-Z_]*' /run/agenix/st0x-issuance.env` (prints names
  only, no values).
- **Deployed git rev**: `/run/st0x/st0x-issuance.git-rev`.
- **The unit runs from a _per-service_ nix profile**, not the system generation:
  `/nix/var/nix/profiles/per-service/st0x-issuance/`. The **system** generation
  timestamp is the host config and moves independently — a system generation
  hours older than the service start time is normal, not a failed activation.
  To prove a deploy is a real new build rather than a no-op restart, compare
  store paths across the last two generations:

  ```bash
  ssh $HOST 'nix-env -p /nix/var/nix/profiles/per-service/st0x-issuance --list-generations | tail -3'
  ssh $HOST 'readlink -f /nix/var/nix/profiles/per-service/st0x-issuance-{14,15}-link'
  ```

  Different store paths ⇒ genuinely new code.
- **New droplet ⇒ new host key / IP**: if the master fails with `Host key
  verification failed`, add the key once with
  `ssh-keyscan -t ed25519,rsa <ip> >> ~/.ssh/known_hosts`, then retry. If the IP
  itself changed, update `ISSUANCE_HOST` in `~/Github/dotagents/.env` first.

## SSH connection reuse (CRITICAL — set up first)

The server rate-limits new SSH connections. Opening a fresh `ssh` per command —
as the steps below appear to do — trips sshd throttling and you get
`ssh: connect to host ... port 22: Connection refused` partway through. Open
**one** master connection and route every later `ssh` through it.

Each tool call is a fresh shell, so env vars don't persist — but the master
socket file does. Hardcode a fixed `ControlPath` and let the **first real
command** open the master implicitly:

```bash
ssh -o ControlMaster=auto -o ControlPersist=15m \
    -o ControlPath=/tmp/issuance-cm.sock <resolved_host> '<first actual command>'
```

**Do NOT open the master as a standalone backgrounded daemon** — the
`ssh -fN ...` form is denied by the auto-approval classifier and the run stalls
before it starts. `ControlMaster=auto` creates the socket as a side effect of
the first useful command, which is all you need. Fold these three options into
Step 0's version check and the master is up from then on.

Then set `HOST` to **include the control option** so every existing `ssh $HOST`
call below transparently reuses the one connection:

```text
HOST="-o ControlPath=/tmp/issuance-cm.sock <resolved_host>"
```

So `ssh $HOST '...'` expands to
`ssh -o ControlPath=/tmp/issuance-cm.sock <resolved_host> '...'` — no new TCP
handshake. **Every** `ssh` (and `sqlite3`/`curl`-over-ssh) in the steps below
MUST go through `$HOST`.

**Also batch remote work:** when you need several queries/curls, combine them
into ONE `ssh` invocation (heredoc or `&&`-joined), and loop over aggregate IDs
*inside* the remote shell — never `ssh` once per iteration.

When finished, close the master:
`ssh -O exit -o ControlPath=/tmp/issuance-cm.sock <resolved_host>`.

## 0. Check deployed version

The deployed build is always the latest commit on `master` for the issuance
repo. Confirm the running revision and note it for the report (NixOS/systemd —
there is no Docker image tag; `deploy-rs` records the git rev):

```bash
ssh $HOST 'cat /run/st0x/st0x-issuance.git-rev 2>/dev/null; systemctl show st0x-issuance.service -p ActiveState -p ExecMainStartTimestamp --value'
```

`force-complete/redemption` and `close/redemption` have long been on `master`,
so they are available on the deployed build — no commit-ancestry check needed.
Only if the recorded git rev is conspicuously old (does not match the latest
`master` commit) should you verify the endpoint exists before relying on it.
Otherwise treat `FORCE_COMPLETE_DEPLOYED=true`.

## 1. Fetch stuck transactions

The box has no `python3`/`jq`, so consume the raw JSON directly (pretty-print
locally afterward if you need to):

```bash
ssh $HOST 'KEY=$(grep "ISSUER_API_KEY" /run/agenix/st0x-issuance.env | cut -d= -f2 | tr -d "\"") && curl -s -w "\nHTTP %{http_code}\n" -H "X-API-KEY: $KEY" http://localhost:8000/admin/stuck'
```

If the list is empty, **do not stop** — an empty `/admin/stuck` means there is
nothing to *recover*, not that the service is healthy. Go to the health check
(Step 1b), then report. Only skip 1b if the user explicitly asked just to
unstick transactions.

Build a working list from the response. Each item has:
`aggregate_type`, `aggregate_id`, `state`, `detail`, `underlying`, `quantity`,
`timestamp`, and optionally `tx_hash`.

## 1b. Health check (post-deploy, or whenever nothing is stuck)

Run this when `/admin/stuck` is empty, or whenever the user asks a health-shaped
question — "a new deploy just landed", "is everything working", "is the bot
OK?". `/admin/stuck` only reports aggregates already wedged in a known-bad
state; it is silent about a service that crash-loops, signs with a dead key,
cannot reach Alpaca, or never started watching a vault. Those are the failures
that have actually bitten in production, so check them directly.

Batch it into **one** `ssh` call:

```bash
ssh $HOST 'echo "=== rev / state / restarts ==="; cat /run/st0x/st0x-issuance.git-rev; systemctl show st0x-issuance.service -p ActiveState -p ExecMainStartTimestamp -p NRestarts -p MainPID --value; \
  echo "=== errors+warnings since start ==="; journalctl -u st0x-issuance --since "<service_start>" --no-pager -p warning | tail -40; \
  echo "=== startup sequence (polling noise stripped) ==="; journalctl -u st0x-issuance --since "<service_start>" --no-pager | grep -viE "Polling vault for transfer" | head -40; \
  echo "=== backfill coverage ==="; journalctl -u st0x-issuance --since "<service_start>" --no-pager | grep -c "Receipt backfill complete for vault"; \
  echo "=== vaults polled ==="; journalctl -u st0x-issuance --no-pager -n 400 | grep -oE "vault=0x[0-9a-fA-F]+" | sort -u | wc -l'
```

Verify each of these, and say which passed rather than a bare "looks fine":

| Signal | Healthy | Failure it catches |
|---|---|---|
| Deployed git rev | matches latest `master` | stale/failed deploy |
| `NRestarts` | `0` | crash-loop (missing view migrations, 2026-06-17) |
| ERROR/WARN count since start | `0` | anything degraded |
| `Turnkey wallet initialized` + `Signer backend resolved` | present | dead signing key (403, 2026-08-07) |
| View rebuilds (receipt inventory, redemption, receipt burns) | all "rebuild complete" | missing view→Lifecycle migrations |
| Receipt backfill | `complete` count == asset count | partial startup |
| Backfill `from_block` | near chain head | 6.9M-block replay crash-loop (2026-07-13) |
| Vaults polled | == asset count | asset registered but never watched (2026-07-13) |
| Poller block cursor | advances ~30 blocks/min on Base (2s blocks) | stalled monitor |

Then confirm no aggregate is quietly non-terminal. **Use these exact terminal
sets** — an incomplete list produces false "stuck!" alarms:

- **Redemption terminal**: `TokensBurned`, `RedemptionClosed`,
  `BurnForceCompleted`, `ExistingBurnRecovered`
  (`ExistingBurnRecovered` applies to `Completed` — `src/redemption/mod.rs`,
  and in the view `src/redemption/view.rs`)
- **Mint terminal**: `MintCompleted`, `MintClosed`

```bash
ssh $HOST bash -s <<'EOF'
sqlite3 /mnt/data/issuance.db "
WITH last AS (
  SELECT aggregate_type, aggregate_id, event_type,
         ROW_NUMBER() OVER (PARTITION BY aggregate_type, aggregate_id ORDER BY sequence DESC) rn
  FROM events WHERE aggregate_type IN ('Redemption','Mint')
)
SELECT aggregate_type, aggregate_id, event_type FROM last
WHERE rn = 1 AND event_type NOT IN (
  'RedemptionEvent::TokensBurned','RedemptionEvent::RedemptionClosed',
  'RedemptionEvent::BurnForceCompleted','RedemptionEvent::ExistingBurnRecovered',
  'MintEvent::MintCompleted','MintEvent::MintClosed'
);"
EOF
```

Finally, confirm outbound Alpaca still works — a 401 here is invisible to
`/admin/stuck` until requests pile up (2026-07-20). Use the **read-only**
account endpoint and print only the status code:

```bash
ssh $HOST 'set -a; . /run/agenix/st0x-issuance.env; set +a; \
  curl -s -o /dev/null -w "alpaca HTTP %{http_code}\n" \
    -u "$ALPACA_API_KEY:$ALPACA_API_SECRET" \
    "$ALPACA_API_BASE_URL/v1/accounts/$ALPACA_ACCOUNT_ID"; \
  curl -s https://api.ipify.org; echo'
```

`200` = credentials valid and egress IP allowlisted. `HTTP 000` is almost always
a **misspelled variable name**, not an outage — re-check against the names in
"Deployment layout" before reporting a problem.

**Ordering rule:** scan the logs *before* sending any unauthenticated probe. An
unauthenticated `curl` to `/tokenized-assets` correctly returns 401 and emits
`WARN auth: Missing X-API-KEY`, which then shows up in your own error scan and
looks like a real fault. If you probe first, attribute those WARNs to yourself
explicitly in the report.

Report the health check as a pass/fail table, and state plainly that no
recovery action was needed. If every signal is green, say so without hedging.

## 2. Attempt /admin/recover for each stuck redemption

For each stuck **redemption**, capture the HTTP status code and response body.
Batch all redemptions into ONE `ssh` call (loop in the remote shell, read the
key once) rather than one `ssh` per aggregate:

```bash
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /run/agenix/st0x-issuance.env | cut -d= -f2 | tr -d '\"') && \
  for AGG in <agg_id_1> <agg_id_2> <agg_id_3>; do \
    echo \"== \$AGG ==\"; \
    curl -s -w '\n%{http_code}\n' -X POST -H \"X-API-KEY: \$KEY\" \
      http://localhost:8000/admin/recover/redemption/\$AGG; \
  done"
```

Interpret the HTTP status:

| Status | Body pattern | Classification |
|--------|-------------|----------------|
| 200 | any | ✅ Recovered — stop here for this item |
| 422 | "Alpaca journal still pending" | ⏳ Retry later — Alpaca hasn't confirmed yet |
| 422 | "Invalid state…expected Failed, found Burning" | 🔍 Needs on-chain check (Step 3) |
| 502 | "Tokenization request not found" | 🔍 Needs on-chain check (Step 3) — Alpaca request expired |
| 404 | any | ⚠️ Endpoint not deployed |
| 500 | any | ❌ Internal error — log body, skip |

For stuck **mints**, run instead:

```bash
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /run/agenix/st0x-issuance.env | cut -d= -f2 | tr -d '\"') && \
  curl -s -w '\n%{http_code}' -X POST -H 'X-API-KEY: '\$KEY \
  http://localhost:8000/admin/reprocess/mint/<aggregate_id>"
```

## 3. On-chain burn investigation

Run this for each redemption classified "🔍 Needs on-chain check" in Step 2.

### 3a. Get full event history

Run remote `sqlite3` via a **single-quoted heredoc** piped to `bash -s` so the
SQL single-quote string literals survive intact. Do NOT embed double-quoted SQL
inside `ssh "sqlite3 \"…\""` — the nested shell quoting mangles it and SQLite
then reads `'Redemption'` as a column name.

```bash
ssh $HOST bash -s <<'EOF'
sqlite3 /mnt/data/issuance.db "
SELECT event_type, json(payload)
FROM events
WHERE aggregate_type = 'Redemption'
  AND aggregate_id = '<aggregate_id>'
ORDER BY sequence;
"
EOF
```

Extract from the payload:
- `alpaca_quantity` and `dust_quantity` (from `AlpacaCalled` or `BurnResumed` event)
- `block_number` of the `Detected` event (used as the start block for on-chain search)
- Whether `BurnFireblocksSubmitted` exists (and if it was followed by `BurningFailed`)

### 3b. Get vault address

Same heredoc pattern (the quoted `<<'EOF'` also stops the local shell from
expanding the `$.Added...` JSON paths):

```bash
ssh $HOST bash -s <<'EOF'
sqlite3 /mnt/data/issuance.db "
SELECT json_extract(payload, '\$.Added.vault')
FROM events
WHERE aggregate_type = 'TokenizedAsset'
  AND event_type = 'TokenizedAssetEvent::Added'
  AND json_extract(payload, '\$.Added.underlying') = '<underlying>';
"
EOF
```

Also check for `VaultAddressUpdated` events on the same asset — use the most
recent vault address if any updates exist.

### 3c. Compute expected share amount in hex

Run this **locally** on your laptop (the NixOS box has no `python3`). Use exact
decimal arithmetic (never float) to avoid precision loss:

```bash
python3 -c "
from decimal import Decimal
alpaca = Decimal('<alpaca_quantity>')
dust = Decimal('<dust_quantity>')
total = int((alpaca + dust) * 10**18)
print(hex(total))
"
```

### 3d. Search for burn event on-chain

Get the RPC URL from the server:

```bash
HTTPS_RPC=$(ssh $HOST 'grep "RPC_URL" /run/agenix/st0x-issuance.env | cut -d= -f2 | tr -d "\"" | sed "s|wss://|https://|"')
```

Search for `Transfer(any → 0x0)` matching the exact share amount:

```bash
cast logs \
  --rpc-url "$HTTPS_RPC" \
  --from-block <detection_block_from_3a> \
  --to-block latest \
  --address <vault_address> \
  "Transfer(address indexed from, address indexed to, uint256 value)" \
  "" \
  "0x0000000000000000000000000000000000000000" 2>/dev/null \
  | grep -E "transactionHash|data:" | awk '{print $2}' | paste - - \
  | grep -i "<hex_amount_without_leading_0x>"
```

The grep pattern is the hex amount without `0x` prefix, case-insensitive.

Interpret:
- **Line returned** (`<padded_data> <tx_hash>`): burn happened on-chain but
  was not recorded. Record the tx hash. → ✅ Burn verified
- **No output**: burn has NOT happened on-chain. → ❌ No burn found

**If no exact match**: run without the grep to list all burn txs from that
vault since the detection block. If there are nearby batch burns (multiple
Transfer events in the same tx), the redemption's shares may have been
included at a per-receipt level that doesn't individually match. Note those
tx hashes as "possible batch burn — needs manual verification".

### 3e. Classify result

| Scenario | Status | Suggested next step |
|----------|--------|---------------------|
| Exact burn tx found | ✅ Burn verified | `force-complete` with that tx (Step 4) |
| No burn, Fireblocks tx failed, Alpaca confirmed | 🔄 Re-burn needed | Deploy latest + re-run `/admin/recover` |
| No burn, no prior Fireblocks attempt, Alpaca confirmed | 🔄 Burn pending | Deploy latest + re-run `/admin/recover` |
| No burn, balance ≈ 0 at last recovery attempt | ⚠️ Shares missing | Escalate — shares may have been swept by another batch redemption |

## 4. Execute force-complete for verified burns

**Always ask for user confirmation before executing.** Present what would run:

- Aggregate: `<aggregate_id>` (`<underlying>`, `<quantity>`)
- Burn tx: `<tx_hash>` (verified on-chain)
- Endpoint: `POST /admin/force-complete/redemption/<aggregate_id>`

If `FORCE_COMPLETE_DEPLOYED=false` (deployed tag is older than `master` and
lacks the endpoint): do NOT attempt. Tell the user the deploy needs to catch up
to the latest `master` commit, and stop.

If confirmed and the endpoint is deployed:

```bash
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /run/agenix/st0x-issuance.env | cut -d= -f2 | tr -d '\"') && \
  curl -s -X POST \
  -H 'X-API-KEY: '\$KEY \
  -H 'Content-Type: application/json' \
  -d '{\"burn_tx_hash\":\"<tx_hash>\",\"reason\":\"Burn confirmed on-chain by exact Transfer(to=0x0) amount match — was not recorded\"}' \
  http://localhost:8000/admin/force-complete/redemption/<aggregate_id>"
```

Interpret response:
- **200**: ✅ Force-completed
- **422**: On-chain verification failed — the tx hash didn't prove a burn for
  this redemption. Do NOT retry. Report to user.
- **404**: Endpoint not present in deployed build — the deploy is behind
  `master`; report that a redeploy of the latest `master` is needed, and stop.

## 5. Findings table

Output a Markdown table:

| Aggregate | Asset | Qty | Stuck Since | Recover Result | On-chain | Action Taken | Next Step |
|-----------|-------|-----|-------------|----------------|----------|--------------|-----------|

Column values:
- **Recover Result**: ✅ Recovered / ⏳ Alpaca pending / 🔍 Burning-state / 🔍 Alpaca-expired / ❌ Error
- **On-chain**: ✅ Burn verified `<short_tx_hash>` / ❌ No burn / ⚠️ Shares missing / — (not investigated)
- **Action Taken**: ✅ Recovered / ✅ Force-completed / Pending confirmation / Needs deploy / None
- **Next Step**: specific, copy-pasteable instruction

After the table, list any items needing follow-up as a numbered action list.

## Hard rules

1. **Never run `force-complete` or `close` without explicit user confirmation.**
2. Only suggest `force-complete` when an exact-amount `Transfer(to=0x0)` match
   was found on-chain — approximate matches are not sufficient.
3. Always use `from decimal import Decimal` for share amount computation —
   never `float` (precision loss corrupts 18-decimal amounts).
4. Never read secret files locally — evaluate `$ISSUER_API_KEY` and `$RPC_URL`
   only on the remote server (from `/run/agenix/st0x-issuance.env`) within a
   single SSH command.
5. Never run destructive DB operations (DROP, DELETE, UPDATE) on the remote
   SQLite database.
6. The deployed image is the latest `master` commit, which already includes
   `force-complete` and `close`. Only if the running tag is visibly behind
   `master` should you flag that a redeploy is needed before using them.
7. **An empty `/admin/stuck` is not a clean bill of health.** Never report the
   service healthy on that basis alone — run Step 1b and report what you
   actually verified.
8. Never report a production fault (bad credentials, stuck aggregate, failed
   deploy) without first ruling out the self-inflicted causes in "Failure
   modes": a misspelled env var, an incomplete terminal-event list, the
   per-service vs system nix profile, and your own unauthenticated probes.

## Failure modes

- **SSH permission denied**: check SSH key access to the server.
- **`Host key verification failed`** (new droplet after a migration/rebuild):
  add the key once with `ssh-keyscan -t ed25519,rsa <ip> >> ~/.ssh/known_hosts`,
  then re-open the master. If the IP changed too, update `ISSUANCE_HOST` in
  `~/Github/dotagents/.env` first.
- **`docker: command not found` / `/mnt/volume_nyc3_02/...: No such file`**:
  you're on the NixOS box — use the paths in "Deployment layout" above
  (`st0x-issuance.service`, `/mnt/data/issuance.db`,
  `/run/agenix/st0x-issuance.env`), not the old Docker droplet paths.
- **`python3: command not found` on the box**: the box has no `python3`/`jq` —
  consume raw JSON, and run any `python3` Decimal math locally (Step 3c).
- **`sqlite3` error `no such column: "Redemption"`**: the SQL string literals
  got mangled by nested shell quoting — run the query through the single-quoted
  `<<'EOF'` heredoc to `bash -s` shown in Step 3a.
- **`ssh: connect to host ... port 22: Connection refused`**: you opened too
  many separate SSH connections and tripped the server's rate limit. Ensure the
  multiplexed master from "SSH connection reuse" is up and that every `ssh` goes
  through `$HOST` (the `ControlPath` option). Wait ~30s for the throttle to
  clear, re-open the master, and batch remaining commands into fewer `ssh`
  calls.
- **`cast` not found**: `cast` is from the Foundry toolchain — run `nix develop`
  in the issuance repo first.
- **RPC rate limit or timeout**: retry `cast logs` once. If it fails again,
  note that on-chain investigation was inconclusive for that item.
- **Archive node needed**: for redemptions > 4 weeks old, the standard RPC
  may not serve logs that far back. Note this and skip the on-chain check.
- **`/admin/stuck` returns 401**: API key may have changed — ask the user to
  verify `ISSUER_API_KEY` on the server.
- **The SSH master command is denied / the run stalls immediately**: you used
  the backgrounded `ssh -fN ...` daemon form, which the auto-approval classifier
  blocks. Fold `-o ControlMaster=auto -o ControlPersist=15m -o ControlPath=...`
  into the first real command instead (see "SSH connection reuse").
- **Alpaca probe returns `HTTP 000`**: near-certainly a misspelled env var
  expanding to empty, not an outage. The base URL is `ALPACA_API_BASE_URL`, not
  `ALPACA_BASE_URL`. Re-check the names before reporting a credential problem.
- **Aggregates look "non-terminal" but `/admin/stuck` is empty**: your terminal
  event list is incomplete. `ExistingBurnRecovered` (redemption) and
  `MintClosed` (mint) are terminal — see the exact sets in Step 1b. Trust
  `/admin/stuck` over a hand-written query and verify against the aggregate
  source before raising an alarm.
- **System nix generation looks older than the service start time**: not a
  failed deploy. The unit runs from the *per-service* profile
  (`/nix/var/nix/profiles/per-service/st0x-issuance/`), which is versioned
  separately from the system generation.
- **`WARN auth: Missing X-API-KEY` in the logs**: probably your own
  unauthenticated probe. Check timestamps against your commands before treating
  it as a real fault, and scan logs before probing.
- **No output from cast logs grep**: the burn may be a multi-receipt batch
  where no single Transfer event matches the total. List nearby burn txs for
  manual inspection.
