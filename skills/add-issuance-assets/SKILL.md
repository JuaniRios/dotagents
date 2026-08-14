---
name: add-issuance-assets
description: Add newly deployed tokenized assets to the production issuance bot. Use when given a registry PR, deployment output, or asset-address table and asked to register, restart, and verify issuance assets.
allowed-tools: Bash(ssh:*), Bash(ssh-keyscan:*), Bash(curl:*), Bash(sqlite3:*), Bash(cast:*), Bash(systemctl:*), Bash(journalctl:*), Bash(gh:*), Bash(awk:*), Bash(grep:*), Bash(sed:*), Bash(date:*), Read, AskUserQuestion
---

# Add issuance assets

Register newly deployed tokenized assets in production issuance, initialize
their per-vault poller checkpoints at the current chain head, restart issuance,
and verify persistence and monitoring.

## Production layout

- NixOS service: `st0x-issuance.service`
- Local API: `http://127.0.0.1:8000`
- Database: `/mnt/data/issuance.db`
- Deployed revision: `/run/st0x/st0x-issuance.git-rev`
- Secrets: `/run/agenix/st0x-issuance.env`
- Host: explicit argument, otherwise `ISSUANCE_HOST` in
  `~/Github/dotagents/.env`
- No Docker, Python, or jq on the host

Never print secrets. Read them only inside the remote command that uses them.

## Address meanings

Registry entries normally contain:

- `address`: wrapped `wt*` trading token
- `extensions.unwrappedAddress`: issuance `OffchainAssetReceiptVault`
- `extensions.receiptAddress`: ERC-1155 receipt contract

The issuance API's `vault` field must be `unwrappedAddress`.

The receipt address is not an API field. Issuance discovers it by calling
`vault.receipt()`.

## Workflow

1. Resolve the approved asset set.
   - Accept a registry PR, deployment output, or explicit table.
   - Respect assets explicitly excluded from launch.
   - Build a table with underlying, expected `t*` symbol, network, wrapper,
     unwrapped vault, and receipt address.
   - Verify on-chain:
     - `vault.symbol()` equals the expected `t*` symbol;
     - `vault.decimals()` equals 18;
     - `vault.receipt()` equals the registry receipt address.
   - Present the exact table before mutation.
   - Require explicit authorization to add the batch.

2. Prove the no-history prerequisite on-chain.
   - Seeding at the current head intentionally skips every earlier block, so
     any pre-existing activity would be silently and permanently dropped.
   - Do not rely on assertion alone. Prove it for each vault and receipt:
     - `cast code <address> --block <B>` returns `0x` for some block `B`
       chosen before deployment;
     - `cast logs --from-block <B> --to-block latest --address <address>`
       returns zero logs.
   - Zero logs across a window that begins before the contract existed proves
     zero activity over its entire lifetime. That is the standard of evidence.
   - `vault.totalSupply() == 0` is corroborating but not sufficient on its own:
     shares could have been minted and later burned.
   - If any history exists, do not seed to the current head. Run a complete
     backfill instead.

3. Establish one multiplexed SSH connection.
   - Use `ControlMaster`, `ControlPersist`, and one fixed `ControlPath`.
   - Keep the `ControlPath` short, e.g. `/tmp/.ssh-<tag>.sock`. A long path
     (such as one under a session scratchpad) exceeds the ~104-character Unix
     domain socket limit and the connection fails outright.
   - Reuse it for every command and batch loops inside the remote shell.
   - Close it when finished.

4. Preflight production.
   - Record the deployed revision and service state.
   - Require the service to be active/running.
   - Query `GET /tokenized-assets/<UNDERLYING>?network=<network>`.
   - The `network` query parameter is **required**. Without it the route
     returns `422`, which is not evidence that the asset is absent.
   - Require `404` for every genuinely new asset.
   - Also query one known-existing asset and require `200`, so a uniform `404`
     caused by a malformed request cannot be mistaken for a clean preflight.
   - Stop if an existing listing differs; never overwrite it implicitly.
   - Adding an asset enables it immediately. Never freeze unless requested.

5. Create a consistent SQLite backup.
   - Use SQLite `.backup` while the service is running.
   - Write `/mnt/data/issuance.db.pre-assets-<UTC timestamp>`.
   - Verify it exists and is non-empty.
   - Never overwrite an existing backup.

6. Register every asset.

   ```http
   POST http://127.0.0.1:8000/tokenized-assets
   X-API-KEY: $ISSUER_API_KEY
   Content-Type: application/json
   ```

   ```json
   {
     "underlying": "<UNDERLYING>",
     "token": "<tSYMBOL>",
     "network": "<network>",
     "vault": "<unwrappedAddress>"
   }
   ```

   - Require HTTP `201` and the exact expected response.
   - Stop on the first unexpected result.
   - Do not send wrapper, receipt, decimals, ISIN, or logo fields.

7. Capture the exact current chain head.
   - Read the configured RPC secret only inside the remote command.
   - Query `eth_blockNumber` after all registrations succeed.
   - Convert it exactly to an unsigned integer; never use floating point.
   - Record the head in the report.

8. Determine the deployed checkpoint families and key format.
   - `poll_checkpoints` is `(name, block_number, updated_at)`, keyed by `name`.
   - Production maintains **two independent per-vault families**. Seeding only
     one leaves the other to scan from the global start block:

     `receipt_backfill:<network>:<lowercase-vault>` — receipt backfiller
     `transfer_poll:<network>:<lowercase-vault>` — redemption transfer poller

   - Older Base-only deployments also carry legacy vault-only names
     (`receipt_backfill:<lowercase-vault>`), which the code may consult as a
     fallback for Base. A genuinely new vault has no legacy row, so seed the
     network-keyed name.
   - Census the existing rows by prefix and confirm against the deployed
     revision which names it actually loads. Never invent or mix formats.
   - Record `BACKFILL_START_BLOCK` — it is what an unseeded vault will scan
     from, and the size of that window drives the restart cost.

9. Stop issuance and seed the new checkpoints.
   - Stop `st0x-issuance.service` to avoid a periodic-backfill race.
   - In one SQLite transaction, insert one row per new vault **per family** at
     the exact captured chain head.
   - Seed `transfer_poll` only when step 2 proved the vault has never emitted a
     share `Transfer`. Unseeded, the poller scans from `BACKFILL_START_BLOCK`
     by deliberate design, so a runtime-added vault never inherits a cursor
     already past its history and silently drops redemptions beneath it.
     Seeding at head defeats that safety unless zero history is proven; when it
     is not proven, leave `transfer_poll` unseeded and accept the longer scan.
   - Use monotonic upsert semantics: never lower an existing checkpoint.
   - Verify all inserted rows before starting the service.
   - Modify only `poll_checkpoints`. Never edit events or projections.

10. Start issuance and monitor readiness.
    - Start `st0x-issuance.service`.
    - Wait for the internal API to become ready.
    - Each new vault must start at `captured_head + 1`, not the configured
      global backfill start block.
    - For every asset, require logs showing:
      - expected underlying and vault;
      - expected receipt contract;
      - `from_block = captured_head + 1`;
      - `Receipt backfill complete for vault`.
    - Require each checkpoint to advance normally beyond the seeded head.

11. Final verification.
    - Service is active/running with no new errors and no added restarts.
    - Every internal detail endpoint returns the exact enabled listing.
    - One `TokenizedAssetEvent::Added` event exists per asset.
    - One live projection exists per asset.
    - Live asset count increased by the batch size.
    - Receipt mappings match the registry.
    - Every seeded checkpoint, in **both** families, advanced past the seeded
      head. A family that is still sitting exactly at the seed is not
      progressing — diagnose before declaring success.
    - Where possible, verify the Alpaca-facing list from an allowlisted source.
      The internal `GET /tokenized-assets` list route is IP-restricted and
      returns `403` from `127.0.0.1`; use the per-asset detail route instead of
      treating that `403` as a failure.

12. Report:
    - deployed revision;
    - assets added and enabled/frozen state;
    - vault and receipt mappings;
    - captured checkpoint block;
    - checkpoint families, key format, and inserted rows;
    - API/event/view verification;
    - service and backfill status;
    - database backup path;
    - unresolved risks.

## Failure modes

- `401`: missing or invalid API key.
- `403`: source IP is not allowed for that route. Expected from `127.0.0.1` on
  the Alpaca-facing list route; not a fault.
- `422` on a detail query: the required `network` query parameter is missing or
  unsupported. Re-query correctly — never read it as "asset absent".
- Non-`201` POST: stop the batch.
- Vault call failure: do not register.
- Receipt mismatch: stop; registry and deployment disagree.
- RPC `408`: the request timed out. Confirm the checkpoint was loaded using the
  correct key; do not leave issuance in a restart loop.
- Startup scans the global block: checkpoint key is absent or incompatible with
  the deployed revision. Stop and diagnose before retrying.
- Wrong token/network registration: re-add may not repair it; use the backup
  and an explicit recovery plan.

## Hard rules

- Never use wrapper or receipt addresses as the issuance `vault`.
- Never invent an address, symbol, network, head block, or checkpoint key.
- Never print credentials or RPC URLs.
- Never add assets outside the approved source set.
- Never freeze unless explicitly requested.
- Never seed a current-head checkpoint if historical receipt activity may exist.
- Never seed `transfer_poll` at the head without on-chain proof that the vault
  has never emitted a share `Transfer`; an unproven seed can silently skip
  redemptions forever.
- Never treat a `422` detail response as proof that an asset is absent.
- Never edit domain events or projections directly.
- Never lower an existing checkpoint.
- Never leave issuance in a restart loop.
- Always back up before registration.
- Always verify persistence, receipt discovery, checkpoints, and service health.
