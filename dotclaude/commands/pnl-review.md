---
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(date:*), Bash(tailscale:*), Read
description: Summarize the liquidity bot's realized, cost-adjusted PnL (net of observed costs; an upper bound) over a timeframe via the backend /pnl endpoint. Default last 24h; supports natural-language ranges (last week, yesterday, this month), market-session and symbol filters, and prod/staging.
argument-hint: [timeframe e.g. "last week"] [SYMBOL] [pre|rth|post|overnight|weekend] [staging]
---

# /pnl-review — realized PnL summary from the bot's `/pnl` endpoint

Summarize the liquidity bot's **net realized PnL** (gross spread minus costs plus
revenue) over a timeframe, by calling the backend `/pnl` HTTP endpoint and
presenting a scannable report. This endpoint (shipped in PR #926, merged to
master) is the same source the dashboard's PnL tab uses. It nets off the costs it
can observe -- Alpaca broker & regulatory fees, CCTP fees, tokenization fees,
conversion slippage -- with FIFO lot attribution. **It is not fully
cost-inclusive:** bot gas, wallet-transfer fees, margin interest and dividends
are `not_ingested`, and oracle writes are structurally zero for the current
setup. Net PnL is therefore an **upper bound**. Always confirm against
`costs.coverage[]` rather than assuming a zero line means a zero cost.

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
`date: invalid option -- 'v'`. Try GNU `-d` first, fall back to BSD `-v`, as a
plain inline command (a shell *function* definition would not match the
`Bash(date:*)` allowlist and would prompt on every call):

```bash
TZ=America/New_York date +%F                                                     # today ET
TZ=America/New_York date -d '1 days ago' +%F || TZ=America/New_York date -v-1d +%F   # yesterday
TZ=America/New_York date -d '6 days ago' +%F || TZ=America/New_York date -v-6d +%F   # "last week"
TZ=America/New_York date -d '29 days ago' +%F || TZ=America/New_York date -v-29d +%F # 30 days
```

`toDate` is inclusive. For "all time" omit both params.

## 3. Query the endpoint

Curl the vhost directly. Build the request with `curl -G --data-urlencode`
(never string-interpolate user input into the URL). `limit` only bounds the
per-fill `entries[]` array; `summary`, `costs`, `symbols`, and `windows` always
cover the **full** range, so a modest limit is fine. Save the JSON to the
scratchpad and check the HTTP code:

Write the body to a file with `-o` and let `-w` print the status as the *only*
stdout. Do not append the status to the body -- splitting it back off needs
`tail`/`head`, which are not in `allowed-tools`. `$OUT` is a path in your session
scratchpad directory.

```bash
curl -s -m 90 -o "$OUT/pnl.json" -w '%{http_code}\n' -G "https://st0x-liquidity-nixos.taile5cf8a.ts.net/pnl" \
  --data-urlencode 'fromDate=2026-07-08' \
  --data-urlencode 'toDate=2026-07-09' \
  --data-urlencode 'marketSessionFilter=post' \
  --data-urlencode 'symbol=COIN,QQQM' \
  --data-urlencode 'limit=500'
```

**Use `-m 90`, not a short timeout.** Each `/pnl` request replays the full FIFO
lot ledger *and* makes a live Alpaca `fetch_account_activities` call, so it is
genuinely slow; `-m 25` produces spurious `000` (curl-level) failures on
multi-day ranges. A `000` is a timeout or transport error, **not** a response --
retry once with the same timeout before concluding anything.

Only include `--data-urlencode` lines for filters that were actually requested.

**Pin the snapshot across multi-call runs.** The response echoes a top-level
`asOfRowid` (the persisted-event high-water mark). When an invocation makes more
than one call -- extended hours (`pre` + `post`), session comparisons, anything
-- read `asOfRowid` from the *first* response and pass
`--data-urlencode "asOfRowid=<value>"` on every subsequent call, so all calls see
the same event snapshot instead of straddling fills that landed between them.
Caveat: `asOfRowid` pins persisted SQLite events only; the live Alpaca activity
fetch is **not** snapshotted. Quote the `asOfRowid` in the report footer.

- `200` -> parse and report (step 4). **A `200` does not mean your filters were
  honored** -- see the symbol-skip trap under Failure modes.
- `404` -> nginx on this host isn't proxying `/pnl` (the vhost `locations` block
  in `os.nix` is missing `"/pnl"`, or the host is running an older closure).
  Say so plainly and stop.
- `400` -> bad date filter, or **every** symbol in the filter was invalid; show
  the body (it names the field) and fix the parse.
- `000` / empty -> timeout or tailnet transport error. Retry once, then check
  `tailscale status`.
- `502` -> nginx is up but the bot's listener on `:8001` is down.

## 4. Report

Extract with `jq` from `summary`, `costs`, `symbols`, `windows`, `warnings`,
`availableRange`, `sampleStats`. All money fields are decimal strings -- print to
cents.

**Gross vs net is the single easiest thing to get wrong here.** `summary` and
`costs` are net-capable; `symbols[]` carries only *directly attributable* costs;
`windows[]` carries **no costs at all**. Never place a number from one of those
tiers next to a number from another without labeling which is which.

Structure the report:

1. **Headline** -- one line:
   `Net realized PnL: $<net> over <from>..<to> ET (<env><, filters>)`
   using `summary.netRealizedPnlUsd`. Include any `marketSessionFilter` /
   `counterTradingFilter` / `symbol` filter in the `<, filters>` slot -- a
   filtered report that doesn't say so reads as a whole-book report. Then the
   bridge:
   `gross $<summary.grossRealizedPnlUsd> - costs $<summary.trackedCostsUsd> + revenue $<summary.trackedRevenueUsd> = net $<summary.netRealizedPnlUsd>`.
   If the resolved `fromDate` precedes `availableRange.firstDate`, say the window
   is clipped by data availability.
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
   `costs.missingCostObservationCount` if > 0.
   Then read `costs.coverage[]` (`source`, `status`, `note`) and **list every
   entry whose `status` is not `included`**. A `not_ingested` line is a cost that
   is missing from net, which is categorically different from a genuine zero --
   "list only non-zero lines" would otherwise render untracked bot gas as if it
   were free. Say plainly that net is an upper bound whenever any
   `not_ingested` line exists.
5. **Per-symbol** -- table from `symbols[]` sorted by `netRealizedPnlUsd` desc:
   symbol, net PnL, gross PnL, matched shares, `inventoryDriftShares` (open
   position carried). Call out the top winner and worst loser explicitly, and for
   each give the one-line bucket split (`counterTradePnlUsd` /
   `onchainNettingPnlUsd` / `directionalExposurePnlUsd`) -- which bucket a
   symbol lost in is usually the actual insight, since a counter-trade loss is a
   real leak while a directional loss is price movement.
   **`symbols[].netRealizedPnlUsd` deducts only costs Alpaca attributed to that
   symbol.** Account-level costs (unsymboled fee rows, margin interest, CCTP,
   tokenization) sit in `costs.genericCostsUsd` and hit the session net only, so
   per-symbol nets **do not sum to `summary.netRealizedPnlUsd`**. Compute the
   residual (`summary.netRealizedPnlUsd - sum(symbols[].netRealizedPnlUsd)`) and
   print it as an explicit "unattributable (generic) costs" footer row rather
   than letting the reader find the gap.
6. **Daily breakdown (GROSS)** -- from `windows[]`, one window per ET day
   (`granularity: "day"`). **There is no window-level total field**: sum that
   window's `symbols[].totalPnlUsd`. Costs are never windowed, so this column is
   **gross of costs** -- label it "gross" and never set it beside the net
   headline unlabeled. Sanity check: the daily gross column must reconcile to
   `summary.totalPnlUsd`, *not* to `summary.netRealizedPnlUsd`. If you catch
   yourself comparing a daily sum to the net headline, you are mixing tiers.
   Tag weekends (`isWeekend`) and `marketSession`. Skip zero days.
7. **Inventory / open risk** -- `summary.inventoryDriftShares` and
   `inventoryDriftUsd`: net open (unhedged) position carried out of the window;
   its PnL is unrealized and NOT in the net figure. Add the one-line fill census
   from `sampleStats` (`onchainFillCount` / `offchainFillCount` /
   `totalFillCount`) -- it distinguishes an empty window from a thin one.
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
3. **Every figure carries its window.** When an invocation makes more than one
   `/pnl` call (different dates, sessions, or symbols), each number you report
   must state its exact `fromDate..toDate` and filters -- inline or as a table
   column. **Never reuse a figure fetched under one window while discussing
   another.** A per-symbol number from a 2-day range and one from a 1-day range
   are different quantities and will silently contradict each other. If two calls
   differ only by window, render them as two labeled columns of one table, not as
   interleaved prose.
4. **Call budget: at most 3 `/pnl` requests per invocation.** Each replays the
   full ledger and spends live Alpaca API rate budget shared with the hedging
   path. The extended-hours pattern (`pre` + `post`) uses 2. If the question
   genuinely needs more, say what it will cost and ask first. **Never loop
   per-symbol** -- `symbol` accepts a comma-separated list, and a single
   unfiltered call already returns per-symbol (`symbols[]`) and per-day
   (`windows[]`) decomposition.
5. **Net is an upper bound.** It deducts only observed costs. If
   `missingCostObservationCount > 0`, or any `costs.coverage[]` entry is
   `not_ingested`, say the net is optimistic -- do not present it as final.
6. **Don't invent numbers.** Every figure comes from the JSON. If a field is
   absent, say so; do not estimate. Never re-derive a figure the endpoint already
   reports.
7. **ET days, inclusive `toDate`.** State the resolved range so the user can
   verify the window.
8. Default env is **prod**; only use the staging host when the user says
   `staging`.
9. **Query over HTTPS, never over SSH.** Do not shell into the box with
   `prod-remote`/`staging-remote` to reach `localhost:8001` -- `/pnl` is proxied
   on the tailnet vhost, and SSHing in as root to read a report is needless
   privilege.

## Failure modes

- **404**: nginx isn't proxying `/pnl` on this host. State it and stop -- do not
  fall back to hand-rolled SQL PnL, and do not SSH in to reach `:8001` directly.
- **400**: invalid `fromDate`/`toDate`, or **every** symbol in the filter was
  invalid; the body names the field. Re-parse.
- **Silent symbol skip (a `200` you must not trust)**: if *some* symbols in the
  filter are invalid, the endpoint drops them, narrows the query, and still
  returns `200` -- the loss appears only as a
  `"Skipped N invalid symbol filters..."` string in `warnings[]`. So
  `symbol=COIN,TYPO` quietly returns a COIN-only report. **After every call,
  grep `warnings[]` for `invalid symbol` before reporting anything**; if present,
  re-check your parse and tell the user which symbols were dropped. Do not
  present a narrowed result as the requested one.
- **`000` / timeout**: the request exceeded `-m 90`, or the tailnet is down.
  Retry **once**; if it fails again check `tailscale status`. Do not retry blindly
  in a loop -- each attempt costs a live Alpaca API call.
- **`502`**: nginx up, bot listener down. Say so; don't retry.
- **DNS / no route to host**: not on the tailnet (or the host is offline --
  staging is frequently down). Check `tailscale status`.
- **`summary` present but all zeros / `total: 0`**: no fills matched the window
  or filters. Report "no activity in <range>" rather than a zero-filled table.
- **Staging unreachable**: staging is often offline; say so and offer prod.
