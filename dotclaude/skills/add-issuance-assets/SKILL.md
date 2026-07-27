---
name: add-issuance-assets
description: Add newly deployed tokenized assets to the production issuance bot. Use when given a registry PR, deployment output, or asset-address table and asked to register, restart, and verify issuance assets.
allowed-tools: Bash(ssh:*), Bash(ssh-keyscan:*), Bash(curl:*), Bash(sqlite3:*), Bash(cast:*), Bash(systemctl:*), Bash(journalctl:*), Bash(gh:*), Bash(awk:*), Bash(grep:*), Bash(sed:*), Bash(date:*), Read, AskUserQuestion
---

# Add issuance assets

Register newly deployed tokenized assets in production issuance, initialize
their receipt-backfill checkpoints at the current chain head, restart issuance,
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

2. Confirm the no-history prerequisite.
   - The standard checkpoint workflow intentionally skips historical scanning
     before the onboarding block.
   - Require explicit confirmation that the new vaults have had no mints,
     deposits, receipt transfers, or other receipt activity.
   - If historical receipts may exist, do not seed to the current head. Run a
     complete backfill instead.

3. Establish one multiplexed SSH connection.
   - Use `ControlMaster`, `ControlPersist`, and one fixed `ControlPath`.
   - Reuse it for every command and batch loops inside the remote shell.
   - Close it when finished.

4. Preflight production.
   - Record the deployed revision and service state.
   - Require the service to be active/running.
   - Query `GET /tokenized-assets/<UNDERLYING>`.
   - Require `404` for every genuinely new asset.
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

8. Determine the deployed checkpoint-key format.
   - Inspect existing `poll_checkpoints` rows and the deployed revision.
   - Older/Base deployments use:

     `receipt_backfill:<lowercase-vault>`

   - Network-keyed deployments use:

     `receipt_backfill:<network>:<lowercase-vault>`

   - Use the exact format expected by the running revision. Never invent or
     mix formats.

9. Stop issuance and seed the new checkpoints.
   - Stop `st0x-issuance.service` to avoid a periodic-backfill race.
   - In one SQLite transaction, insert one checkpoint per new vault at the
     exact captured chain head.
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
    - Service is active/running with no new errors.
    - Every internal detail endpoint returns the exact enabled listing.
    - One `TokenizedAssetEvent::Added` event exists per asset.
    - One live projection exists per asset.
    - Live asset count increased by the batch size.
    - Receipt mappings match the registry.
    - New checkpoints advanced normally.
    - Where possible, verify the Alpaca-facing list from an allowlisted source.

12. Report:
    - deployed revision;
    - assets added and enabled/frozen state;
    - vault and receipt mappings;
    - captured checkpoint block;
    - checkpoint key format and inserted rows;
    - API/event/view verification;
    - service and backfill status;
    - database backup path;
    - unresolved risks.

## Failure modes

- `401`: missing or invalid API key.
- `403`: source IP is not allowed for that route.
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
- Never edit domain events or projections directly.
- Never lower an existing checkpoint.
- Never leave issuance in a restart loop.
- Always back up before registration.
- Always verify persistence, receipt discovery, checkpoints, and service health.
