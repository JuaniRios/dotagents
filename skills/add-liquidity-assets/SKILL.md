---
name: add-liquidity-assets
description: >
  Add, enable, disable, or change tokenized assets in the live liquidity bot
  config, then roll staging or production and verify health. Use when asked to
  change an asset flag or st0x-hedge.toml on the GCP liquidity bots.
argument-hint: <prod|staging> <SYMBOL...>
allowed-tools: Bash(gcloud:*), Bash(gh:*), Bash(git:*), Bash(gt:*), Bash(curl:*), Read, Grep
---

# /add-liquidity-assets

**Required**: `prod` or `staging`, plus one or more symbols. Anything else:
say `Usage: /add-liquidity-assets <prod|staging> <SYMBOL...>` and stop.

This command mutates live hedge config. Show the exact TOML patch and release
path before opening a PR. Wait for explicit authorization. After the rollout,
use `check-liquidity-bot` for live verification.

Issuance registration is a separate prerequisite (`add-issuance-assets`).

## Deployment ownership

Runtime config lives in `ST0x-Technology/st0x.liquidity`:

| env | file | rollout |
|---|---|---|
| staging | `config/staging/st0x-hedge.toml` | `build-oci.yml` rolls image and config together after merge |
| prod | `config/prod/st0x-hedge.toml` | manually dispatch `production-release.yml` |

The old copies under `T0Trade/t0.devops/terraform/*-liquidity/` are not the
deployment source of truth. `t0.devops` still owns the VM, Secret Manager,
bucket, IAM, and Privileged Access Manager (PAM) infrastructure.

For a production config-only release, dispatch `production-release.yml` from
`master` with `version` empty. The reusable workflow:

1. Keeps the image digests currently live in production.
2. Validates the candidate config inside that exact bot image.
3. Publishes a numbered `liquidity-runtime-config` Secret Manager version.
4. Writes the image and config pins to `images.env` after PAM authorization.
5. Waits for the VM to publish the adopted pins in `deployed.env`.

The VM roll timer fetches the pinned config, restarts the stack, and runs its
migration and health gates. A config release briefly stops the bot and starts
all gated services, including Datasette.

Do not bump image pins for a TOML-only change. Do not replace the VM. Do not
edit `CONFIG_VERSION` by hand or restart the stack to pick up an unpublished
version.

Staging uses live Base and Alpaca accounts with a different wallet and
inventory. It is not a paper-trading sandbox.

## Active production PAM grants

The shared workflow reuses an open grant only when its justification matches the
same deployment run. When `master` finds a different `ACTIVE` grant, it revokes
that superseded grant and requests a fresh grant with the new deployment details.
It never replaces a grant that still awaits approval.

Do not bypass this behavior from another branch. Production Workload Identity
Federation permits the releaser only from `master`. Never impersonate the
releaser or write production GCS objects manually from a local user session.

## TOML shape

Every equity needs both tables. Missing either fails startup:

```toml
[assets.equities.SYM]
extended_hours_counter_trading = "enabled"

[chains.base.trading.assets.equities.SYM]
trading = "enabled"
rebalancing = "enabled"
wrapped_equity_recovery = "enabled"
vault_id = "0xfab"
tokenized_equity = "<unwrapped>"
tokenized_equity_derivative = "<wrapped>"
```

Resolve addresses from `ST0x-Technology/st0x.registry`
`token-lists/base.json`:

- `tokenized_equity` is `extensions.unwrappedAddress`.
- `tokenized_equity_derivative` is `address` (the `wt*` token).

Verify the wrapped token's `vault.symbol()` onchain when a public RPC is
available. Copy `vault_id` and flag conventions from a sibling in the same
environment. Do not invent values.

`extended_hours_counter_trading` is independent of `trading`. A manual Alpaca
buy does not create a Position aggregate. Enabling rebalancing can adopt an
existing unmanaged broker balance and try to tokenize it, so state that risk
before applying.

Enabling rebalancing also adds the asset's underlying-to-wrapper and
wrapped-to-orderbook allowances to startup. Before production rollout, verify
that existing allowances are sufficient or that the live Turnkey signer policy
permits every required approval transaction. A zero allowance plus no matching
policy will fail startup.

## Workflow

1. Use `check-liquidity-bot` to confirm the target is healthy before editing.
2. Read the environment file from the remote default branch. Stop if it already
   has the requested state.
3. Resolve and verify registry addresses for new assets.
4. List open PRs that touch the same config and linearize overlapping changes.
5. Show the exact patch and rollout side effects. Get authorization.
6. Follow the `graphite` skill for branch, commit, and PR operations.
7. Before submission, run the config compatibility review lane and relevant
   config checks.
8. Merge the authorized PR.
9. Staging: monitor `build-oci.yml`. Production: dispatch
   `production-release.yml` from `master` with `version` empty, then complete
   the PAM flow. The workflow will replace a superseded active grant when needed.
10. Wait for adoption. Confirm the config version advanced, the requested flags
    are loaded, the bot is `Up`, `/health` is 200 with fresh uptime, and
    Datasette is available.
11. Run `check-liquidity-bot` and report the PR, workflow run, config version,
    live commit, uptime, and residual risks.

## Hard rules

1. Never edit the old t0.devops TOML copies to change a live bot.
2. Never deploy an unmerged or unauthorized config.
3. Never skip exact-image validation, adoption, or post-roll health checks.
4. Never change image digests as part of a config-only rollout.
5. Never print Secret Manager payloads or secret TOML.
6. Never invent token addresses, vault IDs, or flag defaults.
7. Never skip either per-equity table.
8. Never treat staging as a sandbox for mainnet funds.

## Failure modes

- **Active grant, different justification**: the workflow revokes it before it
  requests a fresh grant. If revocation fails, the release fails closed.
- **Bot unhealthy after roll**: the VM should restore the previous image/config
  pair. Confirm the rollback in the roll-timer journal and `deployed.env`.
- **Workflow green but bot unhealthy**: treat as critical. The adoption marker
  raced the health gate or the rollback contract failed.
- **CONFIG_VERSION unchanged**: the release did not publish, PAM did not grant
  access, or the roll timer has not adopted the new pin.
- **PAM approval timeout**: rerun the failed job. The same run can reuse its
  matching open grant.
- **Overlapping config PR**: rebase or wait. Do not allow one PR to erase the
  other change.
