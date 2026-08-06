---
name: add-issuance-assets
description: "Use when the user asks to add, register, onboard, or verify newly deployed tokenized assets in the production issuance bot, especially from a registry PR or deployment address list."
---

# add-issuance-assets

Register newly deployed tokenized assets in production issuance, initialize
their per-vault poller checkpoints at the current chain head, restart issuance,
and verify persistence and monitoring.

This changes production financial infrastructure. Keep the batch exact, create
a database backup, and stop on unexpected responses.

## Production Layout

- NixOS service: `st0x-issuance.service`
- Local API: `http://127.0.0.1:8000`
- Database: `/mnt/data/issuance.db`
- Deployed revision: `/run/st0x/st0x-issuance.git-rev`
- Secrets: `/run/agenix/st0x-issuance.env`
- Host: explicit argument, otherwise `ISSUANCE_HOST` from
  `~/Github/dotagents/.env`
- No Docker, Python, or jq on the host

Never print secrets. Read them only inside the remote SSH command that needs
them.

## Address Meanings

Registry entries normally contain:

- top-level `address`: wrapped `wt*` trading token
- `extensions.unwrappedAddress`: issuance `OffchainAssetReceiptVault`
- `extensions.receiptAddress`: ERC-1155 receipt contract

The API's `vault` field must be `unwrappedAddress`. The receipt address is not
submitted; issuance discovers it through `vault.receipt()`.

## Workflow

1. Resolve and validate the approved assets.
   - Accept a registry PR, deployment output, or explicit table.
   - Use the connected GitHub app for private PRs; use `gh` only as fallback.
   - Respect explicit launch exclusions.
   - Build a table with underlying, expected `t*` symbol, network, wrapper,
     unwrapped vault, and receipt address.
   - Verify `symbol()`, `decimals() == 18`, and `receipt()` on-chain.
   - Present the table and require explicit authorization before mutation.

2. Prove on-chain that there is no history to backfill.
   - Seeding to the current head intentionally skips all earlier blocks, so any
     pre-existing activity is silently and permanently dropped.
   - Do not rely on assertion. For each vault and receipt address, prove it:
     - `cast code <address> --block <B>` returns `0x` for a block `B` chosen
       before deployment;
     - `cast logs --from-block <B> --to-block latest --address <address>`
       returns zero logs.
   - Zero logs over a window starting before the contract existed proves zero
     activity across its whole lifetime. That is the required standard.
   - `vault.totalSupply() == 0` corroborates but does not suffice alone; shares
     could have been minted and later burned.
   - If history may exist, do not use current-head checkpointing; perform a
     complete backfill.

3. Open one multiplexed SSH connection.
   - Use one fixed `ControlPath`.
   - Keep it short, e.g. `/tmp/.ssh-<tag>.sock`. Long paths exceed the
     ~104-character Unix domain socket limit and the connection fails.
   - Reuse it for all commands and batch per-asset work remotely.
   - Close it when finished.

4. Preflight.
   - Record the deployed revision and service state.
   - Require `active/running`.
   - Query `GET /tokenized-assets/<UNDERLYING>?network=<network>`. The
     `network` query parameter is required; without it the route returns `422`,
     which is not evidence that the asset is absent.
   - Require `404` for new assets.
   - Also query a known-existing asset and require `200`, so a uniform `404`
     from a malformed request cannot pass as a clean preflight.
   - Stop if an existing listing differs.
   - Adding enables assets immediately. Never freeze unless requested.

5. Back up SQLite.
   - Use `.backup` to create
     `/mnt/data/issuance.db.pre-assets-<UTC timestamp>`.
   - Verify the backup is non-empty and do not overwrite an existing file.

6. Register the assets through:

   ```http
   POST /tokenized-assets
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

   - Require `201` and the exact expected response.
   - Stop on the first unexpected response.
   - Do not send receipt, wrapper, decimals, ISIN, or logo fields.

7. Capture the current chain head.
   - Query `eth_blockNumber` through the configured remote RPC after all POSTs.
   - Keep the RPC URL secret.
   - Convert the result exactly to an unsigned integer.
   - Record the exact head.

8. Determine the deployed checkpoint families and key format.
   - `poll_checkpoints` is `(name, block_number, updated_at)`, keyed by `name`.
   - Production maintains two independent per-vault families. Seeding only one
     leaves the other scanning from the global start block:

     `receipt_backfill:<network>:<lowercase-vault>` — receipt backfiller
     `transfer_poll:<network>:<lowercase-vault>` — redemption transfer poller

   - Older Base-only deployments also carry legacy vault-only names
     (`receipt_backfill:<lowercase-vault>`), which the code may consult as a
     fallback for Base. A genuinely new vault has no legacy row, so seed the
     network-keyed name.
   - Census existing rows by prefix and confirm against the deployed revision
     which names it actually loads. Use exactly that format.
   - Record `BACKFILL_START_BLOCK`; it is what an unseeded vault scans from and
     determines the restart cost.

9. Stop issuance and seed checkpoints.
   - Stop the service before writing to avoid a periodic-backfill race.
   - In one SQLite transaction, insert each new vault at the captured head, for
     each family.
   - Seed `transfer_poll` only when step 2 proved the vault has never emitted a
     share `Transfer`. Unseeded, the poller scans from `BACKFILL_START_BLOCK`
     by deliberate design, so a runtime-added vault never inherits a cursor
     already past its history and silently drops redemptions beneath it.
     Without that proof, leave `transfer_poll` unseeded and accept the scan.
   - Use monotonic upsert semantics; never lower an existing checkpoint.
   - Verify all rows.
   - Modify only `poll_checkpoints`, never events or projections.

10. Start and monitor issuance.
    - Start the service and wait for API readiness.
    - Verify every new vault begins from `captured_head + 1`, not the global
      configured start block.
    - Require logs with the expected vault and receipt address followed by
      `Receipt backfill complete for vault`.
    - Require all new checkpoints to advance normally.
    - If logs show the global start block, stop and diagnose the checkpoint key.
    - If an RPC `408` occurs, do not leave the unit in a restart loop.

11. Verify:
    - service active/running with no new errors and no added restarts;
    - exact internal detail response for every asset;
    - one immutable `TokenizedAssetEvent::Added` event per asset;
    - one live projection per asset;
    - expected increase in live asset count;
    - exact receipt mappings;
    - every seeded checkpoint in both families advanced past the seeded head; a
      family still sitting exactly at the seed is not progressing;
    - Alpaca-facing list from an allowlisted source when available. The
      internal list route is IP-restricted and returns `403` from
      `127.0.0.1` — use the per-asset detail route rather than treating that
      `403` as a failure.

12. Report:
    - deployed revision;
    - assets and enabled/frozen state;
    - vault/receipt mappings;
    - captured head, checkpoint families, and key format;
    - inserted and advanced checkpoints;
    - API/event/view verification;
    - service/backfill health;
    - backup path;
    - unresolved risk.

## Failure Modes

- `401`: invalid API key.
- `403`: source IP not allowed. Expected from `127.0.0.1` on the Alpaca-facing
  list route; not a fault.
- `422` on a detail query: the required `network` query parameter is missing or
  unsupported. Re-query correctly — never read it as "asset absent".
- Non-`201` POST: stop the batch.
- Contract or receipt mismatch: do not register.
- RPC `408`: timeout; verify the intended checkpoint was loaded.
- Global-range backfill after seeding: wrong checkpoint key or failed write.
- Repeated restart: stop the loop and diagnose.
- Wrong token/network: re-add may not fix it; use the backup and an explicit
  recovery plan.

## Hard Rules

- Never use wrapper or receipt addresses as `vault`.
- Never invent addresses, symbols, networks, blocks, or checkpoint keys.
- Never print secrets.
- Never add unapproved assets.
- Never freeze unless requested.
- Never seed current-head checkpoints if historical receipt activity may exist.
- Never seed `transfer_poll` at the head without on-chain proof that the vault
  has never emitted a share `Transfer`; an unproven seed can silently skip
  redemptions forever.
- Never treat a `422` detail response as proof that an asset is absent.
- Never edit domain events or projections.
- Never lower checkpoints.
- Never leave issuance in a restart loop.
- Always back up before registration.
- Always verify persistence, receipt discovery, checkpoint advancement, and
  service health.
