---
allowed-tools: Bash(ssh:*), Bash(curl:*), Bash(python3:*), Bash(sqlite3:*), Bash(cast:*), Bash(docker:*), Bash(grep:*), Bash(awk:*), Bash(cut:*), Bash(sed:*), Bash(git:*), Bash(paste:*), Read, AskUserQuestion
description: Check, diagnose, and recover stuck issuance-bot transactions (mints and redemptions). Calls /admin/stuck, attempts /admin/recover on each, searches on-chain for unrecorded burns, and presents a findings table. Destructive actions (force-complete, close) require explicit user confirmation.
argument-hint: "[host]"
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

Set `DB=/mnt/volume_nyc3_02/issuance.db` for all commands below, then set up a
**multiplexed SSH connection** (next section) before running anything remote.

## SSH connection reuse (CRITICAL — set up first)

The server rate-limits new SSH connections. Opening a fresh `ssh` per command —
as the steps below appear to do — trips sshd throttling and you get
`ssh: connect to host ... port 22: Connection refused` partway through. Open
**one** master connection and route every later `ssh` through it.

Each tool call is a fresh shell, so env vars don't persist — but the master
socket file does. Hardcode a fixed `ControlPath` and open the master once:

```bash
ssh -fN -o ControlMaster=auto -o ControlPersist=15m \
    -o ControlPath=/tmp/issuance-cm.sock <resolved_host>
```

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

The deployed image is always the latest commit on `master` for the issuance
repo. Confirm the running tag and note it for the report:

```bash
ssh $HOST 'docker inspect issuance-bot --format "{{.Config.Image}}"'
```

`force-complete/redemption` and `close/redemption` have long been on `master`,
so they are available on the deployed build — no commit-ancestry check needed.
Only if the deployed tag is conspicuously old (image tag does not match the
latest `master` commit) should you verify the endpoint exists before relying on
it. Otherwise treat `FORCE_COMPLETE_DEPLOYED=true`.

## 1. Fetch stuck transactions

```bash
ssh $HOST 'KEY=$(grep "ISSUER_API_KEY" /mnt/volume_nyc3_02/.env | cut -d= -f2) && curl -s -H "X-API-KEY: $KEY" http://localhost:8000/admin/stuck | python3 -m json.tool'
```

If the list is empty, report "✅ No stuck transactions" and stop.

Build a working list from the response. Each item has:
`aggregate_type`, `aggregate_id`, `state`, `detail`, `underlying`, `quantity`,
`timestamp`, and optionally `tx_hash`.

## 2. Attempt /admin/recover for each stuck redemption

For each stuck **redemption**, capture the HTTP status code and response body.
Batch all redemptions into ONE `ssh` call (loop in the remote shell, read the
key once) rather than one `ssh` per aggregate:

```bash
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /mnt/volume_nyc3_02/.env | cut -d= -f2) && \
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
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /mnt/volume_nyc3_02/.env | cut -d= -f2) && \
  curl -s -w '\n%{http_code}' -X POST -H 'X-API-KEY: '\$KEY \
  http://localhost:8000/admin/reprocess/mint/<aggregate_id>"
```

## 3. On-chain burn investigation

Run this for each redemption classified "🔍 Needs on-chain check" in Step 2.

### 3a. Get full event history

```bash
ssh $HOST "sqlite3 $DB \"
SELECT event_type, json(payload)
FROM events
WHERE aggregate_type = 'Redemption'
  AND aggregate_id = '<aggregate_id>'
ORDER BY sequence;
\""
```

Extract from the payload:
- `alpaca_quantity` and `dust_quantity` (from `AlpacaCalled` or `BurnResumed` event)
- `block_number` of the `Detected` event (used as the start block for on-chain search)
- Whether `BurnFireblocksSubmitted` exists (and if it was followed by `BurningFailed`)

### 3b. Get vault address

```bash
ssh $HOST "sqlite3 $DB \"
SELECT json_extract(payload, '$.Added.vault')
FROM events
WHERE aggregate_type = 'TokenizedAsset'
  AND event_type = 'TokenizedAssetEvent::Added'
  AND json_extract(payload, '$.Added.underlying') = '<underlying>';
\""
```

Also check for `VaultAddressUpdated` events on the same asset — use the most
recent vault address if any updates exist.

### 3c. Compute expected share amount in hex

Use exact decimal arithmetic (never float) to avoid precision loss:

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
HTTPS_RPC=$(ssh $HOST 'grep "RPC_URL" /mnt/volume_nyc3_02/.env | cut -d= -f2 | sed "s|wss://|https://|"')
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
ssh $HOST "KEY=\$(grep ISSUER_API_KEY /mnt/volume_nyc3_02/.env | cut -d= -f2) && \
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
4. Never read `.env` files locally — evaluate `$ISSUER_API_KEY` and `$RPC_URL`
   only on the remote server within a single SSH command.
5. Never run destructive DB operations (DROP, DELETE, UPDATE) on the remote
   SQLite database.
6. The deployed image is the latest `master` commit, which already includes
   `force-complete` and `close`. Only if the running tag is visibly behind
   `master` should you flag that a redeploy is needed before using them.

## Failure modes

- **SSH permission denied**: check SSH key access to the server.
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
- **No output from cast logs grep**: the burn may be a multi-receipt batch
  where no single Transfer event matches the total. List nearby burn txs for
  manual inspection.
