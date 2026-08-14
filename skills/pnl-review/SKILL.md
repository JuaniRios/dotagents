---
name: pnl-review
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(date:*), Bash(tailscale:*), Read
description: Answer any question about the liquidity bot's profitability -- from a vague "are we making money?" to a per-fill drill-down -- via the backend /pnl endpoint (realized PnL net of observed costs; an upper bound). Written for a mixed audience; answers are plain business language, no internal jargon. Default last 24h; supports natural-language ranges (last week, yesterday, this month), market-session and symbol filters, and prod/staging.
argument-hint: [question or timeframe e.g. "last week"] [SYMBOL] [pre|rth|post|overnight|weekend] [staging]
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

Parse the user's request. Parse it into a timeframe, optional filters, and
environment, then query and summarize. **Default timeframe: last 24h.**

## 1. Parse the argument

The user's request is free text. Extract, in any order (all parts optional):

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
  - **Evaluative question with no timeframe** ("are we making money", "is this
    profitable", "how's the bot doing") -> trailing 7 days, not the 24h
    default -- one day is too thin a basis for a profitability verdict. State
    the chosen window in the verdict so the reader knows the basis.
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
per-fill `entries[]` array (the fill-level drill-down -- see **Response
schema**); `summary`, `costs`, `symbols`, and `windows` always cover the
**full** range, so a modest limit is fine for report runs. For a fill-level
question, raise `limit` and check `hasMore`/`total` to confirm you pulled every
matching lot. Save the JSON to the scratchpad and check the HTTP code:

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

## 4. Answer the ask

First decide the response shape from the user's arguments:

- **Targeted question** -- the argument asks for a specific quantity or a
  yes/no (e.g. "did COIN make money yesterday", "what were our CCTP fees last
  week", "worst single trade this month", "how many post-market fills did MSTR
  do"). Answer *that*: lead with the one figure or verdict, read from the exact
  field that holds it (see **Response schema** at the end for the field map),
  and include only the sections below that bear on the answer. Still label gross
  vs net, and still state the upper-bound caveat whenever you quote a net. Do
  not emit the full 8-section report for a one-figure question.
- **Open-ended ask** -- empty argument, or "how did we do", "summarize",
  "pnl for last week", "are we making money", "is this thing profitable",
  "how's the bot doing". Evaluative/vague questions are open-ended asks:
  produce the full report below, opening with a one-sentence verdict that
  answers the question as literally asked ("Yes -- the bot made $X net over
  the last week on $Y of volume").
- **Unanswerable ask** -- the question needs data this endpoint doesn't have:
  unrealized/open-position gains, return on invested capital (there is no
  capital base in the response), forecasts, or benchmark comparisons. Say
  plainly what the report does and doesn't cover, then give the nearest
  answerable figure (e.g. for "what's our ROI" give net PnL as a % of volume
  traded and say it is a per-dollar-traded margin, not return on capital).
  Never guess or extrapolate.

### Audience: finance-literate, not technical

Assume the reader understands P&L, gross vs net, volume, margins, fees, and
basis points -- but knows **nothing** about this codebase, the bot's
internals, or crypto plumbing. This command is used by non-engineers; write
every answer accordingly:

- **No internal jargon or field names in the answer.** JSON keys, `jq`, curl,
  HTTP codes, nginx, tailnet, FIFO internals -- all invisible. The parenthetical
  resolved-interpretation line (step 1) may stay technical; the report may not.
- **Translate the PnL buckets** every time they appear:
  - counter-trade PnL -> "hedged spread capture" -- profit from an onchain
    trade plus its offsetting broker hedge. This is the core strategy, so
    call it that: a loss here is a real leak worth flagging.
  - directional exposure PnL -> "market-move P&L" -- gain/loss from prices
    moving while the bot held unhedged inventory. Market luck, not edge.
  - onchain netting PnL -> "onchain buys matched directly against onchain
    sells" (no broker hedge involved).
  - inventory drift -> "open (unhedged) position carried out of the period";
    its gains/losses are not in the net figure.
  - onchain notional -> "volume traded onchain"; offchain notional -> "hedge
    volume at the broker".
  - matched lots/shares -> "completed round-trips".
  - FIFO attribution -> omit, or at most "profits matched trade-by-trade,
    oldest first".
- **The upper-bound caveat in business language**: "true net profit is
  slightly lower than shown -- a few costs (blockchain gas fees, wallet
  transfer fees, margin interest) aren't tracked automatically yet." Never
  present the raw `not_ingested` vocabulary.
- **Contextualize magnitudes.** A bare dollar figure means little: pair net
  PnL with the volume that produced it and the % / bps margin, and say the
  denominator is volume traded, not capital invested.
- **Failures get one plain sentence** ("the reporting service is unreachable
  right now; nothing is wrong with the trading itself") plus one short
  technical line for whoever fixes it. Never dump curl or nginx detail on a
  non-technical reader.

Extract with `jq` from `summary`, `costs`, `symbols`, `windows`, `warnings`,
`availableRange`, `sampleStats`, and -- for fill-level questions -- `entries`.
All money fields are decimal strings -- print to cents.

**Gross vs net is the single easiest thing to get wrong here.** `summary` and
`costs` are net-capable; `symbols[]` carries only *directly attributable* costs;
`windows[]` carries **no costs at all**. Never place a number from one of those
tiers next to a number from another without labeling which is which.

### Full report

Structure the report:

1. **Headline** -- a verdict sentence answering the ask, then one line:
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
3. **PnL buckets** -- `counterTradePnlUsd` (hedged spread capture),
   `onchainNettingPnlUsd` (onchain-vs-onchain netting),
   `directionalExposurePnlUsd` (market-move P&L on unhedged inventory). Use
   the plain-language names from the audience glossary, and say which bucket
   is the strategy working vs market luck. These are gross-of-cost building
   blocks.
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
8. **Warnings & caveats** -- surface `warnings[]` (dedup), rephrased in plain
   language if the raw string is jargon. Always note, in business terms:
   realized profit only (gains/losses on open positions excluded), profits
   matched trade-by-trade oldest-first (not exact hedge parentage), ET-day
   granularity, and the untracked-costs caveat from the audience section.

Lead with the verdict and the number. Keep it scannable -- tables for
per-symbol and daily, prose only where it adds insight (e.g. "SPYM dragged;
COIN carried it"). If the window is empty (no fills), say so instead of
printing a wall of zeros.

## Hard rules

1. **Read-only.** Only GET the endpoint and read the DB indirectly through it.
   Never write, restart, or mutate anything.
2. **Never interpolate the user's arguments into the URL.** Always `--data-urlencode`.
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
10. **Plain business language in every answer.** The reader may be a
    non-technical stakeholder: no JSON field names, no internal bucket names
    unglossed, no infrastructure vocabulary. Precision lives in the numbers
    and their labeled windows, not in jargon. See the audience section in
    step 4.

## Failure modes

When any of these hits, report it to the reader as one plain sentence (what it
means for them: "the reporting service is unreachable; the trading itself is
unaffected") plus one short technical line for whoever will fix it. Details
below are for diagnosis, not for pasting into the answer.

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

## Response schema

Field map for targeted queries. Money fields are decimal strings (print to
cents); share fields are high-precision decimals. Fields already covered by the
step-4 report are not re-explained here -- this section exists so an ad-hoc
question about a field the report ignores has a map instead of a guess.

**Top-level keys**: `asOfRowid` (persisted-event high-water mark; pin it across
multi-call runs), `attributionMethod` (always FIFO replay), `availableRange`
{`firstAt`,`lastAt`,`firstDate`,`lastDate`}, `summary`, `costs`, `symbols[]`,
`windows[]`, `entries[]`, `costEntries[]`, `sampleStats`, `warnings[]`,
`symbolUniverse[]` (every symbol the backend knows, not just the active ones),
`total` (matched-lot count in range), `hasMore` (true if `entries[]` was
truncated by `limit`).

**`summary`** (session-wide, net-capable) adds, beyond the fields step 4 uses:
`realizedPnlUsd` (= gross), `directionalInventoryBaselinePnlUsd` /
`directionalImbalanceExcessPnlUsd` (the two halves of
`directionalExposurePnlUsd`), `openLongShares` / `openShortShares` (the gross
open legs behind net `inventoryDriftShares`), `unmatchedOffchainShares` /
`unmatchedOffchainNotionalUsd` / `unmatchedOffchainFillCount` (offchain fills
with no onchain parent), `openLotCount` (open FIFO lots carried out).

**`costEntries[]`** (one row per cost/revenue ledger entry -- use for "which
events drove the CCTP/tokenization line"): `category`, `accountingBucket`,
`effect` (cost|revenue|none), `amountUsd`, `occurredAt`, `aggregateType`,
`aggregateId`, `eventRowid`, `symbol` (null if unsymboled), `detail`.

**`symbols[]`** (per-symbol; carries only Alpaca-attributed costs, so the nets
do NOT sum to `summary.netRealizedPnlUsd`) adds, beyond step 4:
`realizedPnlUsd`, the two `directional*` halves, `trackedCostsUsd` /
`trackedRevenueUsd`, `matchedLotCount`, `onchainFillCount` / `offchainFillCount`,
`openLongShares` / `openShortShares`, `unmatchedOffchainShares` /
`unmatchedOffchainFillCount`.

**`windows[]`** (one per `granularity` bucket -- `day` here): `windowId`,
`label` (the ET day), `startAt`, `endAt`, `granularity`, `isWeekend`,
`marketSession` (`mixed` when a day spans sessions), `counterTradingSession`,
and `symbols[]` {`symbol`, `totalPnlUsd`, the PnL buckets}. No cost fields --
window PnL is GROSS.

**`entries[]`** (per-closed-lot drill-down, bounded by `limit` -- the fill-level
query surface): `symbol`, `pnlBucket` (the lot's bucket, e.g. `counter_trade`),
`openedAt` / `closedAt` / `matchedAt`, `shares`, `openingVenue` /
`closingVenue` (onchain|offchain), `openingDirection` / `closingDirection`,
`onchainPriceUsdc` / `offchainPriceUsd`, `spreadUsd`, `realizedPnlUsd`,
`elapsedSeconds` + `counterTradeThresholdSeconds` + `delayedCounterTrade`
(whether the hedge beat the counter-trade window), `onchainTradeId` /
`offchainOrderId`, `openingFillId` / `closingFillId`, `openingRowid` /
`closingRowid`. Sort by `realizedPnlUsd` for best/worst trade. For a
session-scoped fill question, re-query with `marketSessionFilter` rather than
bucketing `entries[]` by timestamp locally.

**`sampleStats`** (fill census, always full-range): `firstAt`, `lastAt`,
`symbolCount`, `onchainFillCount`, `offchainFillCount`, `totalFillCount`, and
`symbols[]` {per-symbol `firstAt` / `lastAt` / fill counts}.
