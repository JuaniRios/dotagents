---
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(date:*), Bash(tailscale:*), Read
description: Summarize the liquidity bot's realized, cost-inclusive PnL over a timeframe via the backend /pnl endpoint. Default last 24h; supports natural-language ranges (last week, yesterday, this month), market-session and symbol filters, and prod/staging.
argument-hint: [timeframe e.g. "last week"] [SYMBOL] [pre|rth|post|overnight|weekend] [staging]
---

# /pnl-review — realized PnL summary from the bot's `/pnl` endpoint

Summarize the liquidity bot's **net realized PnL** (gross spread minus costs plus
revenue) over a timeframe, by calling the backend `/pnl` HTTP endpoint and
presenting a scannable report. This endpoint (shipped in PR #926, merged to
master) is the same source the dashboard's PnL tab uses -- it is cost-inclusive
(Alpaca broker & regulatory fees, margin interest, bot gas, CCTP fees,
tokenization fees, conversion slippage, oracle writes, dividends), FIFO lot
attribution.

`/pnl` is proxied by nginx on each host's Tailscale MagicDNS vhost (`os.nix`:
`"/pnl" = apiProxy "/pnl"`), so **query it directly over HTTPS -- no SSH.** Any
tailnet member can run this command; a root SSH key is not required.

The argument is `$ARGUMENTS`. Parse it into a timeframe, optional filters, and
environment, then query and summarize. **Default timeframe: last 24h.**

## 1. Parse the argument

`$ARGUMENTS` is free text. Extract, in any order (all parts optional):

- **Environment**: `staging` -> base URL
  `https://st0x-liquidity-staging.tail6094d7.ts.net`. Anything else / omitted ->
  `prod` -> `https://st0x-liquidity-nixos.taile5cf8a.ts.net`. (MagicDNS names
  from `flake.nix` `tailscaleMagicDnsName`; reachable only over the tailnet.)
- **Timeframe** (natural language, ET calendar days -- see step 2):
  - empty / `last 24h` / `24h` -> **default**: yesterday..today (ET)
  - `today` -> today..today
  - `yesterday` -> yesterday..yesterday
  - `last week` / `past week` / `7d` / `last 7 days` -> trailing 7 days
    (today-6 .. today)
  - `last N days` / `Nd` -> today-(N-1) .. today
  - `this week` -> most recent Monday (ET) .. today
  - `last month` / `30d` -> today-29 .. today
  - `this month` -> 1st of current month (ET) .. today
  - explicit `YYYY-MM-DD` -> that single day; `YYYY-MM-DD to YYYY-MM-DD` -> that
    range
  - `all` / `all time` -> omit `fromDate`/`toDate` (full history)
- **Market session** (maps to `marketSessionFilter`): `pre`/`pre-market`/`premarket`
  -> `pre`; `rth`/`regular`/`market hours` -> `rth`; `post`/`after-hours`/`afterhours`
  -> `post`; `overnight` -> `overnight`; `weekend` -> `weekend`. Omitted -> no
  filter (all sessions). Note: there is **no single "extended" value** -- if the
  user says "extended hours", run the query twice (`pre` and `post`) and report
  both, or state that extended = pre + post.
- **Counter-trading** (maps to `counterTradingFilter`): `counter-active` ->
  `counter_trading_active`; `counter-inactive` -> `counter_trading_inactive`.
  Omitted -> no filter.
- **Symbol(s)**: any all-caps ticker(s) (e.g. `COIN`, `SPYM`, or `COIN,QQQM`) ->
  `symbol` (comma-separated). Do not treat session/env keywords as symbols.

State the resolved interpretation in one line before querying (env, resolved
`fromDate..toDate` in ET, any filters) so the user can catch a misparse.

## 2. Compute ET dates

The endpoint interprets `fromDate`/`toDate` as **America/New_York calendar
days**.

**`date` may be GNU or BSD here.** Even on macOS, a nix dev shell often puts GNU
coreutils `date` ahead of `/bin/date`, and BSD `-v` flags then fail with
`date: invalid option -- 'v'`. Use GNU `-d` first and fall back to BSD `-v`:

```bash
et() {  # et <offset-days>  ->  YYYY-MM-DD in ET
  TZ=America/New_York date -d "$1 days ago" +%Y-%m-%d 2>/dev/null \
    || TZ=America/New_York date -v-"$1"d +%Y-%m-%d
}
et 0    # today ET
et 1    # yesterday ET
et 6    # 7 days ago (for "last week")
et 29   # 30 days ago
```

`toDate` is inclusive. For "all time" omit both params.

## 3. Query the endpoint

Curl the vhost directly. Build the request with `curl -G --data-urlencode`
(never string-interpolate user input into the URL). `limit` only bounds the
per-fill `entries[]` array; `summary`, `costs`, `symbols`, and `windows` always
cover the **full** range, so a modest limit is fine. Save the JSON to the
scratchpad and check the HTTP code:

```bash
curl -s -m 90 -w '\n%{http_code}' -G "https://st0x-liquidity-nixos.taile5cf8a.ts.net/pnl" \
  --data-urlencode 'fromDate=2026-07-08' \
  --data-urlencode 'toDate=2026-07-09' \
  --data-urlencode 'marketSessionFilter=post' \
  --data-urlencode 'symbol=COIN,QQQM' \
  --data-urlencode 'limit=500' > "$SCRATCH/pnl.json"
```

**Use `-m 90`, not a short timeout.** Each `/pnl` request replays the full FIFO
lot ledger *and* makes a live Alpaca `fetch_account_activities` call, so it is
genuinely slow; `-m 25` produces spurious `000` (curl-level) failures on
multi-day ranges. A `000` is a timeout or transport error, **not** a response --
retry once with the same timeout before concluding anything.

Only include `--data-urlencode` lines for filters that were actually requested.
The last line of output is the HTTP status; split it off before parsing the body
with `jq`.

- `200` -> parse and report (step 4).
- `404` -> nginx on this host isn't proxying `/pnl` (the vhost `locations` block
  in `os.nix` is missing `"/pnl"`, or the host is running an older closure).
  Say so plainly and stop.
- `400` -> bad date/symbol filter; show the body (it explains which field) and
  fix the parse.
- `000` / empty -> timeout or tailnet transport error. Retry once, then check
  `tailscale status`.
- `502` -> nginx is up but the bot's listener on `:8001` is down.

## 4. Report

Extract with `jq` from `summary`, `costs`, `symbols`, `windows`, `warnings`,
`availableRange`. All money fields are decimal strings -- print to cents.

Structure the report:

1. **Headline** -- one line:
   `Net realized PnL: $<net> over <from>..<to> ET (<env><, filters>)`
   using `summary.netRealizedPnlUsd`. Then the bridge:
   `gross $<summary.grossRealizedPnlUsd> - costs $<summary.trackedCostsUsd> + revenue $<summary.trackedRevenueUsd> = net $<summary.netRealizedPnlUsd>`.
2. **Volume & return** -- `summary.onchainNotionalUsd` (liquidity traded),
   `summary.offchainNotionalUsd` (Alpaca hedge leg), `summary.matchedShares`,
   `summary.matchedLotCount`. Compute **return = net / onchain notional** as a
   percentage and in bps. State the denominator (onchain notional = the volume
   quoted; the round-trip is ~2x because it counts the hedge leg too).
3. **PnL buckets** -- `counterTradePnlUsd` (clean hedged counter-trades),
   `onchainNettingPnlUsd` (onchain-vs-onchain), `directionalExposurePnlUsd`
   (delayed/inventory). These are gross-of-cost building blocks.
4. **Costs** -- from `costs`: list only non-zero lines among
   `brokerFeesUsd`, `regulatoryFeesUsd`, `marginInterestUsd`, `botGasUsd`,
   `cctpFeesUsd`, `tokenizationFeesUsd`, `conversionSlippageUsd`,
   `oracleWriteCostUsd`, `walletTransferFeesUsd`, `offchainExecutionFeesUsd`,
   `unclassifiedCostsUsd`; and revenue `dividendRevenueUsd`. Flag
   `costs.missingCostObservationCount` if > 0 (some costs not yet observed ->
   net is optimistic).
5. **Per-symbol** -- table from `symbols[]` sorted by `netRealizedPnlUsd` desc:
   symbol, net PnL, gross PnL, matched shares, `inventoryDriftShares` (open
   position carried). Call out the top winner and worst loser explicitly.
6. **Daily breakdown** -- from `windows[]`: per-day total (sum each window's
   `symbols[].totalPnlUsd`, or use the window rollup), tagging weekends and the
   `marketSession` if a session filter was applied. Skip zero days.
7. **Inventory / open risk** -- `summary.inventoryDriftShares` and
   `inventoryDriftUsd`: net open (unhedged) position carried out of the window;
   its PnL is unrealized and NOT in the net figure.
8. **Warnings & caveats** -- surface `warnings[]` verbatim (dedup). Always note:
   realized PnL only (open inventory excluded), FIFO-by-timestamp attribution
   (not exact hedge parentage), ET-day granularity, and any missing cost
   observations.

Lead with the number. Keep it scannable -- tables for per-symbol and daily,
prose only where it adds insight (e.g. "SPYM dragged; COIN carried it"). If the
window is empty (no fills), say so instead of printing a wall of zeros.

## Hard rules

1. **Read-only.** Only GET the endpoint and read the DB indirectly through it.
   Never write, restart, or mutate anything.
2. **Never interpolate `$ARGUMENTS` into the URL.** Always `--data-urlencode`.
3. **Net is cost-inclusive but gross-of-unobserved-costs.** If
   `missingCostObservationCount > 0`, say the net is optimistic -- do not present
   it as final.
4. **Don't invent numbers.** Every figure comes from the JSON. If a field is
   absent, say so; do not estimate.
5. **ET days, inclusive `toDate`.** State the resolved range so the user can
   verify the window.
6. Default env is **prod**; only use the staging host when the user says
   `staging`.
7. **Query over HTTPS, never over SSH.** Do not shell into the box with
   `prod-remote`/`staging-remote` to reach `localhost:8001` -- `/pnl` is proxied
   on the tailnet vhost, and SSHing in as root to read a report is needless
   privilege.

## Failure modes

- **404**: nginx isn't proxying `/pnl` on this host. State it and stop -- do not
  fall back to hand-rolled SQL PnL, and do not SSH in to reach `:8001` directly.
- **400**: invalid `fromDate`/`toDate`/`symbol`; the body names the field. Re-parse.
- **`000` / timeout**: the request exceeded `-m 90`, or the tailnet is down.
  Retry **once**; if it fails again check `tailscale status`. Do not retry blindly
  in a loop -- each attempt costs a live Alpaca API call.
- **`502`**: nginx up, bot listener down. Say so; don't retry.
- **DNS / no route to host**: not on the tailnet (or the host is offline --
  staging is frequently down). Check `tailscale status`.
- **`summary` present but all zeros / `total: 0`**: no fills matched the window
  or filters. Report "no activity in <range>" rather than a zero-filled table.
- **Staging unreachable**: staging is often offline; say so and offer prod.
