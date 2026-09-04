---
name: add-assets-everywhere
description: >
  Plan then apply a new tokenized-equity listing across pricing, oracle,
  Bebop, issuance, liquidity, and dashboards. Use when asked to add, list,
  launch, or enable new assets everywhere, on the quoting path, or from a
  registry PR.
argument-hint: "<SYMBOL...>"
allowed-tools: Bash(gh:*), Bash(git:*), Bash(gt:*), Bash(gcloud:*), Bash(cast:*), Bash(curl:*), Bash(jq:*), Bash(date:*), Read, Grep
---

# /add-assets-everywhere

Onboard one or more tokenized equities across the live T0 plane. **Plan
first. Mutate only after the user confirms the plan.**

Required: one or more underlying symbols (`NKE MCD`). Anything else: say
`Usage: /add-assets-everywhere <SYMBOL...>` and stop.

This skill **orchestrates**. Do not copy sibling procedures into this file.

| Surface | How |
|---|---|
| Issuance | follow `add-issuance-assets` after plan confirm |
| Liquidity bot | follow `add-liquidity-assets` after plan confirm |
| Pricing, oracle, Bebop, observability | this skill (no sibling) |
| t0.devops git | `graphite` skill |
| Prod PAM | `review-pam-grants` (never approve on sight) |
| Liquidity verify | `check-liquidity-bot` |

Do not follow `st0x.liquidity/docs/how-to-add-new-asset.md`. It is stale
(Docker issuance, Fireblocks, `config/prod` toml that GCP does not read).

## What actually has to change

Live config is `T0Trade/t0.devops`, not the app-repo baked copies.

| # | Surface | Files | Apply |
|---|---|---|---|
| 1 | Pricing | `terraform/{staging,production}-pricing/st0x-pricing.toml` | Staging: merge auto. Prod: merge of this toml starts `release-pricing.yml` (PAM) |
| 2 | Signed oracle | `terraform/{staging,production}-oracle/oracle-config.toml` | Staging: merge auto. Prod: **dispatch** `production-oracle.yml` then PAM. `release-oracle.yml` watches `images.yaml` only |
| 3 | Prod Bebop quoter | `terraform/production-bebop/t0-bebop.toml` | **Dispatch** `production-bebop.yml` then PAM |
| 4 | Issuance | API on the NixOS host | `add-issuance-assets` (stop/seed/start) |
| 5 | Liquidity | `terraform/{staging,production}-liquidity/st0x-hedge.toml` | Staging: merge auto, **trading disabled**. Prod: **dispatch** `production-liquidity.yml`, 2-of-N PAM, 2-min roll timer, **trading enabled** |
| 6 | Dashboards | `terraform/modules/gcp-observability/price-parity/<SYM>-{buy,sell}.bin` (oracle probe bodies only) | Merge auto. Skip if the bins cannot be produced |

Same hunks go in **both** staging and prod toml copies in **one PR**. That is
not a promotion. Image digests promote staging → prod via `images.yaml`;
runtime toml does not.

### Staging is not a rehearsal of the launch path

Do **not** wait for a staging-first cycle before the prod files.

- Staging pricing uses **paper Alpaca**. Staging oracle has a **different KMS
  signer** (customers do not trust it) and is IAM-gated. Staging Bebop uses
  test `maker_id = st0x`, a thin wallet, and today only quotes `wtSGOV`.
- None of that hits Hydrex, prod Bebop (`st0x-rfqt`), or the prod oracle
  signer.
- CI (`pricing-config`, `oracle-config`) is the real toml gate. A Cloud Run
  config the app rejects fails the startup probe; traffic stays on the
  previous revision.
- Staging liquidity **is** live Base + Alpaca with a different EOA. Treat it
  as real funds, not a sandbox. Always add the symbol there with
  `trading = "disabled"`. Prod gets `trading = "enabled"`.
- Skip staging Bebop unless the user asked. Adding pairs there does not
  rehearse the prod vault-sourced maker.

### Out of scope (name in the plan, do not do)

- **Registry merge.** Addresses may come from an **open** `st0x.registry` PR.
  Launch docs merge the registry at Phase 6, not here, unless the user
  explicitly asks.
- **Ethereum / HyperEVM** rows unless that registry list already has real
  addresses. Do not invent them.
- **Quant spread artifact.** Default is the interim hardcoded spread (below).
- **Price publisher.** No per-token list; it consumes the pricing websocket.
- **App-repo** `st0x.pricing` / `st0x.bebop` baked tomls. Live is t0.devops.
- **`st0x.liquidity` `config/**`.** GCP does not read those.
- **`images.yaml` digest bumps.**
- **Hydrex / Raindex pool / customer venue setup.** Ops, not this skill.
- **Logos / website.** Separate frontend PR.
- **Alpaca tokencache.** After issuance, Alpaca refreshes on its own. A mint
  `"not found in tokencache"` is wait-or-ask-Alpaca, not a retry loop.
- **Fireblocks whitelist.** Issuance signs with Turnkey. If a mint fails on
  a Turnkey policy, that is a human console task.
- **Pyth / `parity_pyth_feed_ids`.** Out of this flow. Do not add feed ids.

## Address map

Source: `ST0x-Technology/st0x.registry` `token-lists/base.json` on `main`,
or the matching file on an open registry PR (`gh pr diff`).

| Registry field | Meaning | Goes to |
|---|---|---|
| `symbol` | `wtSYM` | pricing `[[assets]].symbol`, oracle `[[tokens]].symbol`, Bebop comment |
| `address` | wrapped `wt*` | pricing `vault` and `[[tokens]].address`, oracle `address`, Bebop `[[pairs]].base`, liquidity `tokenized_equity_derivative` |
| `extensions.unwrappedAddress` | `t*` vault | issuance `vault`, liquidity `tokenized_equity` |
| `extensions.receiptAddress` | ERC-1155 | on-chain check only; issuance discovers `vault.receipt()` |

Never send a wrapper or receipt as the issuance `vault`.

On-chain before the plan (public Base RPC is fine):

- unwrapped `symbol() == tSYM`, `decimals() == 18`, `receipt()` equals the
  registry receipt
- wrapped `symbol() == wtSYM`

## Toml shapes (pricing / oracle / Bebop)

Copy a sibling **in that same file**. Default spread is the Aug 2026 interim
used for INTC/AAPL/… until quant cuts an artifact:

```toml
[[assets]]
symbol = "wtSYM"
upstream = "SYM"
vault = "<wrapped>"
fixed_half_spread_bps = 25.0

[[tokens]]
chain_id = 8453
address = "<wrapped>"
symbol = "wtSYM"
```

A symbol gets **either** `fixed_half_spread_bps` **or**
`[[spread_model.profiles]]` (rth/pre/post + bebop overlay), never both. The
config test rejects the overlap. Do not add profile rows for an uncalibrated
listing.

Oracle (each env):

```toml
[[tokens]]
address = "<wrapped>"
symbol = "wtSYM"
```

Prod Bebop: copy an existing `[[pairs]]` block; only `base` changes (the
wrapped address). Shared hook/inventory/`0xfab` stay as in that file.

Liquidity: both tables, per `add-liquidity-assets`, with this skill's
flag default (it overrides that skill's "disabled until booted" default):

| env | `trading` | `rebalancing` | `wrapped_equity_recovery` | `extended_hours_counter_trading` |
|---|---|---|---|---|
| staging | `"disabled"` | `"disabled"` | `"disabled"` | `"disabled"` |
| prod | `"enabled"` | `"enabled"` | `"enabled"` | `"enabled"` |

Do not ask. Only flip a flag if the user named a different set.

Observability: Pyth is out of this flow (no `parity_pyth_feed_ids` row).
The probe discovers symbols from pricing `/metrics`. The remaining optional
artifact is the oracle-leg body pair
`price-parity/<SYM>-buy.bin` / `<SYM>-sell.bin` (ABI-encoded `/context/v5`
orders). Do **not** copy another symbol's bins. If you cannot produce them,
omit them and list them as a leftover.

## Phase A — plan (no mutation)

1. Resolve the registry source (`main` vs open PR). Stop if a symbol is
   missing from both, or if Ethereum/HyperEVM rows would invent addresses.
2. Verify on-chain. Stop on mismatch.
3. Inventory: is it already in each live file / issuance API? Skip those
   surfaces.
4. `gh pr list --repo T0Trade/t0.devops --state open` for overlapping toml
   PRs. Reuse a correct open stack; do not open a third unsigned copy.
5. `t0.devops` **requires signed commits**. If this environment cannot sign,
   the plan must say so: PRs opened from here will not merge.
6. Show the plan. Wait. Confirm authorizes **only** the listed actions.

Plan shape (fill every row):

```
Assets: SYM…   (registry: main | PR #N, Base-only | +eth/hyperevm)
On-chain: tSYM/wtSYM/decimals/receipt OK

#  Surface            Change                         You / colleague
1  Pricing s+p        [[assets]]+[[tokens]], 25bps   PR review; prod PAM on release-pricing (auto after merge)
2  Oracle s+p         [[tokens]]                     PR review; you dispatch production-oracle.yml; PAM
3  Prod Bebop         [[pairs]]                      PR review; you dispatch production-bebop.yml; PAM
4  Issuance           POST + seed checkpoints        none (this session, ~2 min downtime)
5  Liquidity          staging disabled, prod enabled dispatch production-liquidity.yml; 2-of-N PAM
6  Observability      oracle bins if we can make them merge auto; else leftover
7  Registry merge     no                             launch Phase 6 (unless you asked)
8  Alpaca tokencache  no                             wait / ask Alpaca after issuance
9  Hydrex / pools     no                             ops

t0.devops PR: one PR, staging+prod copies together.
Apply after merge, in order: pricing serving → oracle dispatch → Bebop dispatch.
Liquidity PAM may run after pricing. Issuance is independent of the PR.

Overlapping PRs: …
Signed commits: this machine can / cannot sign.
```

Ask explicitly only if the bins cannot be produced (leave them, or wait), and
whether to merge the registry. Do not ask about liquidity flags.

## Phase B — execute (only after confirm)

Reuse an already-correct open PR rather than rewriting it. If you author:

1. `~/Github/t0.devops`, `graphite` skill (`gt sync`, `gt create`, `gt submit`).
   One PR with every confirmed toml/tf/bin hunk. Then `pr-description`.
2. CI must be green (`pricing-config`, `oracle-config`, terraform plans).
3. Commits must verify signed. Unsigned → do not merge; say who must
   force-push a signed commit.
4. Need a review that is not the author. Ask in the plan; ping after submit.
5. Merge only when signed + approved + green.
6. Apply in order:
   1. Wait until prod pricing serves `wtSYM` (snapshot/metrics). Approve the
      `release-pricing` PAM grant via `review-pam-grants` when it appears.
   2. Dispatch `production-oracle.yml` on `main`. PAM. Confirm oracle `/quote`
      no longer returns `Unknown tStock token` for the wrapper.
   3. Dispatch `production-bebop.yml`. PAM.
   4. Liquidity: `add-liquidity-assets` twice — staging with all flags
      `"disabled"`, prod with all flags `"enabled"` (this overrides that
      skill's "disabled until booted" default). Prod dispatch + PAM + roll
      + `check-liquidity-bot`.
7. Issuance: `add-issuance-assets` with the same address table. Can run as
   soon as the plan is confirmed; it does not wait for the t0.devops merge.
8. Do not merge the registry PR unless the confirmed plan said to.

Missed PAM window (job waits ~60 min): `gh run rerun <id> --failed`.

## Report

PR URL(s), which applies ran, new listings (issuance enabled, pricing
serving, oracle quoting, Bebop pair present, liquidity flags), leftover
human items (PAM votes still needed, unsigned commits, Alpaca cache,
registry, bins, Hydrex).

## Hard rules

1. No mutation before plan confirm.
2. Never invent an address, vault id, or spread.
3. Never use the wrapper as the issuance vault.
4. Never add `spread_model.profiles` next to `fixed_half_spread_bps`.
5. Never bump `images.yaml` for a listing.
6. Never edit `st0x.liquidity` `config/**` to change a GCP bot.
7. Never approve PAM on sight — `review-pam-grants`.
8. Never merge unsigned `t0.devops` commits.
9. Never treat staging as a dry run of prod quoting or of mainnet inventory.
10. Never skip overlapping-PR detection.

## Failure modes

- **Registry PR only, not on main:** fine as an address source; do not merge
  it as part of this run unless confirmed.
- **Open t0.devops stack already does this:** reuse it; do not duplicate.
- **Unsigned commits / no signing agent:** PRs stay `BLOCKED`. Stop and name
  who must sign.
- **Oracle/Bebop toml merged but not live:** forgot the manual dispatch.
- **Bebop quoting a symbol pricing does not serve:** apply order was wrong;
  pricing first.
- **Issuance 422 on POST:** unconfigured network or vault already claimed.
- **Liquidity bot Restarting after roll:** toml rejected; revert and
  re-apply. No automatic revert.
- **Oracle-leg coverage gap on the new symbol:** missing `*-buy.bin` /
  `*-sell.bin`. Pricing discovery still lists it; the oracle probe does not.
