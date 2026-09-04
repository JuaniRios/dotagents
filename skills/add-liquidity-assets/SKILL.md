---
name: add-liquidity-assets
description: >
  Add or enable tokenized assets in the live liquidity bot config (staging
  or production) via t0.devops config-as-data, merge/PAM apply, and the VM
  roll timer. Use when asked to add a symbol, turn trading on, or change
  st0x-hedge.toml on the GCP bots.
argument-hint: <prod|staging> <SYMBOL...>
allowed-tools: Bash(gcloud:*), Bash(gh:*), Bash(git:*), Bash(gt:*), Bash(curl:*), Bash(jq:*), Read, Grep
---

# /add-liquidity-assets

**Required**: `prod` or `staging`, plus one or more symbols. Anything else:
say `Usage: /add-liquidity-assets <prod|staging> <SYMBOL...>` and stop.

This command **mutates** live hedge config. Present the exact toml patch
and wait for explicit authorization before opening the PR. After apply,
verify with the `check-liquidity-bot` skill (access, `remote`/`api` helpers,
and the health report live there — do not copy them).

Issuance registration is a separate prerequisite (`add-issuance-assets`).
Do not treat this skill as a substitute.

## What actually runs

The GCP bots do **not** read `st0x.liquidity` `config/{prod,staging,prod-gcp,staging-gcp}/st0x-hedge.toml`. Those copies are dead on GCP.

Live config is `T0Trade/t0.devops`:

| env | file | apply |
|---|---|---|
| staging | `terraform/staging-liquidity/st0x-hedge.toml` | merge to `main` auto-applies |
| prod | `terraform/production-liquidity/st0x-hedge.toml` | merge only plans; human dispatches `production-liquidity.yml`; 2-of-N PAM |

`modules/runtime-config` publishes the file as Secret Manager secret
`liquidity-runtime-config`. Terraform writes that version into the VM's
`images.env` as `CONFIG_VERSION` (currently a number, never `latest`).
The 2-minute `t0-liquidity[-staging]-roll.timer` sees the new `images.env`,
fetches that pin to `/etc/t0-liquidity/secrets/st0x-hedge.toml`, and
`systemctl restart t0-liquidity-stack`.

The stack unit is:

- `ExecStartPre` = fetch secrets at the pinned versions
- `ExecStart` = `docker compose up -d --remove-orphans --scale bot|dashboard|datasette=${GATED_SERVICE_REPLICAS}`
- `ExecStop` = `docker compose down`

A config release therefore **stops the bot briefly** and **starts every
gated service whose replica count is 1**, including Datasette even if
someone had `docker stop`ped it. Confirm that side effect before apply.
Do not hand-restart the stack to "pick up" a Secret Manager version you
added out of band: a bare restart re-fetches the **old** `CONFIG_VERSION`.

Do **not** bump `images.yaml` for a toml-only change. Do **not** replace
the GCE instance (that is only for cloud-init/compose-file changes).
Do **not** edit `CONFIG_VERSION` by hand.

There is no liquidity equivalent of `oracle-config.yml`: a bad toml
crash-loops the bot after the roll (`compose up` still succeeds). Watch
the bot.

Staging is live Base + Alpaca with a **different** EOA/inventory, not a
paper book. Do not treat a staging apply as a dry run of prod.

## Toml shape

Every equity needs **both** tables. Missing either fails startup.

Copy the flags from a sibling already in **that same file**, not from
`st0x.liquidity` `config/prod`. Typical enabled sibling (TQQQ):

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

Addresses come from `ST0x-Technology/st0x.registry` `token-lists/base.json`:

- `tokenized_equity` = `extensions.unwrappedAddress`
- `tokenized_equity_derivative` = `address` (the `wt*` token)

Checksum to match siblings. `vault_id = "0xfab"` is the auto-discover
sentinel used by every current entry; do not invent a vault.

Default for a brand-new listing: copy the enabled sibling flags above
(`trading`, `rebalancing`, `wrapped_equity_recovery`,
`extended_hours_counter_trading` all `"enabled"`). One release, not a
disabled-then-enable pair. If the user named flags, use those.

`extended_hours_counter_trading` is independent of `trading`. Off-hours
hedges only happen when it is `"enabled"`.

A `cli buy` on Alpaca does **not** create a Position aggregate and does
**not** require the symbol in this file. Enabling `rebalancing` on a
symbol that already has unmanaged broker shares can make the inventory
poller adopt that balance and then try to tokenize it on-chain. Say so
before applying.

## Workflow

1. Bind env as in `check-liquidity-bot`. Confirm `/health` is 200.
2. Read the live file:
   `gh api -H 'Accept: application/vnd.github.raw' repos/T0Trade/t0.devops/contents/${CONFIG_PATH}`
   Stop if the symbol is already present with the requested flags.
3. Resolve addresses from the registry. Verify `vault.symbol()` on-chain
   matches `tSYM` when a public RPC is available. Do not copy addresses
   from `st0x.liquidity` config files.
4. `gh pr list --repo T0Trade/t0.devops --state open --search st0x-hedge.toml`
   Name any open PR that already edits the same file (rebase or wait).
5. Show the exact hunks and the apply path (staging merge vs prod
   dispatch + PAM). Wait for authorization.
6. Clone or update `~/Github/t0.devops`. Version control: follow the
   `graphite` skill (`gt sync`, `gt create`, `gt submit`). Touch only
   the one env's `st0x-hedge.toml` unless the user asked for both.
7. Staging: merge. The apply is automatic. Prod: merge, then
   Actions → `production-liquidity` → Run workflow. The apply job
   requests PAM entitlement `tf-apply-owner` on project `t0-liquidity`
   and waits up to 60 minutes. Approvers follow the `review-pam-grants`
   skill (2 of 4). Missed window: `gh run rerun <id> --failed`.
8. Wait for the roll (timer ticks every 2 minutes). Confirm on the VM:
   - `CONFIG_VERSION` in `/etc/t0-liquidity/images.env` advanced
   - `/etc/t0-liquidity/secrets/st0x-hedge.toml` contains the new tables
   - `docker ps` shows the bot Up, not Restarting
   - `api /health` is 200 with a fresh `uptimeSeconds`
9. Run `check-liquidity-bot` on that env. For a `trading = "enabled"`
   add, say explicitly that no hedge is expected until the first onchain
   fill.
10. Report: PR URL, apply run, new `CONFIG_VERSION`, bot uptime, whether
    Datasette came back, residual risks (unmanaged broker qty, issuance
    not registered, overlapping PRs).

## Hard rules

1. Never edit `st0x.liquidity` `config/**` to change a GCP bot.
2. Never apply without an authorized PR.
3. Never `systemctl restart t0-liquidity-stack` to activate a new secret
   version that Terraform has not pinned in `images.env`.
4. Never set `bot_enabled: false` or change image digests as part of an
   asset add.
5. Never print Secret Manager payloads or the secrets toml.
6. Never invent a token address, vault id, or flag default.
7. Never skip the "both tables" requirement.
8. Never treat staging as a sandbox for mainnet funds.

## Failure modes

- **Bot Restarting after roll**: toml rejected by this image. Revert the
  file and merge/dispatch again; there is no automatic revert.
- **CONFIG_VERSION unchanged**: apply did not run (prod: forgot dispatch
  or PAM denied) or the roll has not ticked yet.
- **Bare restart, no apply**: old pin comes back; the edit looks "missing".
- **PAM timeout**: rerun the failed apply job; reuse the open grant.
- **Overlapping toml PR**: merge conflict or lost edit. Linearize.
- **`/health` down during roll**: expected for seconds while compose
  downs. If it lasts minutes, the new config is crashing the process.
