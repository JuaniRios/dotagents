---
name: check-liquidity-bot
description: "Use when the user asks to run the check-liquidity-bot workflow: diagnose the liquidity bot's health (hedging, rebalancing, errors, overall status) by querying the live server directly via `staging-remote`/`prod-remote`."
---

# check-liquidity-bot

Codex adaptation of the Claude slash command `check-liquidity-bot`. Follow the workflow below, but use Codex-native tools and normal user questions where the original mentions Claude-only mechanisms.

Compatibility notes:
- Treat `$ARGUMENTS` as the relevant arguments or intent from the user's request.
- Replace `AskUserQuestion` with a concise question to the user when a decision is required.
- Replace Claude `Agent` calls with Codex subagents only when the user explicitly asks for parallel agents; otherwise do the work locally.
- Ignore Claude `allowed-tools`, `argument-hint`, `TodoWrite`, and `Skill` tool references as tool-permission metadata.
- When the workflow mentions another slash command, use the corresponding Codex skill or follow that workflow directly.

**Required argument**: `prod` or `staging` -- which environment to check.

This skill queries the **live server directly** via the `<env>-remote` SSH
shim. There is no snapshot/download mode: every DB and log query runs against
the live server. This is fast, always-fresh, and avoids downloading the ~100MB
DB.

If the argument is missing or not one of `prod`/`staging`, tell the user:
"Usage: `check-liquidity-bot <prod|staging>`" -- and stop.

Set the remote shim based on the environment:
- `staging` -> `staging-remote`
- `prod` -> `prod-remote`

All DB queries go through `<env>-remote sqlite3 /mnt/data/st0x-hedge.db "..."`
and all log queries through `<env>-remote journalctl -u st0x-hedge ...`. Filter
at the source -- never pull the full journal.

Note on sqlite3 quoting through the shim: the SSH shim re-splits arguments, so
wrap the whole `sqlite3 ... "SELECT ..."` invocation in single quotes:
`prod-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT * FROM position_view;"'`.
Unquoted parentheses and semicolons in the SQL will otherwise break.

## 0. Connectivity gate (MANDATORY -- before any other remote command)

SSH goes through the 1Password SSH agent. If the user is AFK they cannot
approve the agent prompt, and **each failed attempt counts toward fail2ban**.
Spamming probes will ban the IP and make recovery harder.

**Run exactly one probe first -- never parallelize it with other remote calls:**

```bash
<env>-remote 'echo ok'
```

- **Success** (prints `ok`): proceed to section 1. Parallel remote queries are
  fine only after this gate passes.
- **Any failure** (non-zero exit, `agent refused operation`, `Permission
  denied`, `Connection refused`, timeout, or a hang you have to kill):
  **STOP immediately.**

On failure:

1. Report the exact error from that **single** probe.
2. Tell the user to come back, approve 1Password if prompted, unban the IP if
   already fail2ban'd, then re-run `check-liquidity-bot <env>` once SSH works.
3. **FORBIDDEN after a failed probe** (until the user re-runs the skill or
   explicitly confirms SSH works again):
   - any second `<env>-remote` / `ssh` attempt
   - retries, "one more try", verbose `ssh -v` diagnostics
   - key scanning (`ssh-add -l`, alternate identities, `IdentityAgent` tricks)
   - port scans (`nc`, checking 22/2222/public IP)
   - extra Tailscale diagnostics (do **not** run `tailscale status` /
     `tailscale ping` as a follow-up -- just report the probe error)

Do not try to "help fix" connectivity with more SSH. One probe, stop, wait for
the user.

## Inspecting the codebase to interpret behavior

Whenever you need to read the bot's source code to explain its behavior --
what a log line means, how hedging/rebalancing logic works, what an error
implies, which code path produced an observation -- **do NOT read the current
working-tree or checked-out branch.** The current branch may contain unmerged
or unreleased changes that do not reflect what is actually running in the
environment you are diagnosing. Reasoning from it will produce wrong
conclusions.

Instead, inspect the code at the exact commit deployed to that environment:

1. **Determine the deployed commit/version.** Query the server for the running
   build, e.g. `<env>-remote systemctl status st0x-hedge --no-pager` (start
   time) and `<env>-remote "readlink -f /nix/var/nix/profiles/per-service/st0x-hedge/bin/server"`
   (nix store path), and resolve it to a git commit.
2. **Read the code at that commit, read-only.** Use
   `git show <commit>:<path>` or `git grep <pattern> <commit>` against the
   local repo history. Never `git checkout`, never edit files, never assume the
   working tree matches.
3. If you cannot resolve the deployed commit, say so explicitly and state that
   any code-behavior claims are provisional -- do not silently fall back to the
   current branch.

## 1. First pass -- dashboard-backed status views

Before grepping logs, get a status-at-a-glance from the read-model views that
back the dashboard. This surfaces most problems immediately and tells you where
to dig. The live dashboard renders this same data over its `/ws` websocket;
querying the views directly is the scriptable equivalent.

**Service health:**
```bash
<env>-remote systemctl is-active st0x-hedge
<env>-remote systemctl status st0x-hedge --no-pager   # uptime, restarts, PID
```
If stopped, this is the most critical finding -- lead the report with it.

**Counter-trades (offchain hedge orders) -- status distribution + recent:**
```bash
<env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT status, COUNT(*) FROM offchain_order_view GROUP BY status;"'
<env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT view_id, status, substr(payload,1,120) FROM offchain_order_view ORDER BY rowid DESC LIMIT 30;"'
```

**CRITICAL blind spot -- the dashboard hides failed counter-trades.** The
dashboard trade view only renders **Filled** counter-trades: the history
loader's `try_to_trade()` drops any non-filled order and the live broadcast
no-ops on the `Failed` status. A hedge that errors out (e.g. an un-fillable
symbol the broker rejects dozens of times a day) will **never appear on the
dashboard**. So "the dashboard looks fine" does NOT mean hedging is fine --
always query `offchain_order_view` for `Failed` counts here, and scan logs for
`Offchain venue rejected` / `broker reports Failed` in section 2.

**Stuck / failed rebalance transfers (mints, redemptions, USDC bridges).** The
neatest way to spot a stranded transfer is to find any aggregate whose LATEST
event is a failure:
```bash
<env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "
  WITH latest AS (SELECT aggregate_id, MAX(sequence) ms FROM events GROUP BY aggregate_id)
  SELECT e.event_type, COUNT(*) FROM events e JOIN latest l
    ON e.aggregate_id=l.aggregate_id AND e.sequence=l.ms
  WHERE e.event_type LIKE \"%Failed%\" OR e.event_type LIKE \"%Rejected%\" OR e.event_type LIKE \"%DetectionFailed%\"
  GROUP BY e.event_type ORDER BY COUNT(*) DESC;"'
```
For any non-zero bucket, list the offending aggregates (their seq-1 event
carries the symbol/quantity) to see exactly what is stranded.

**Positions / inventory:**
```bash
<env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT * FROM position_view;"'
```

**Profitability:** for any "are we making money?" question, use the pnl-review
workflow (which wraps the backend `/pnl` endpoint) rather than eyeballing
trades.

If everything above looks clean, the bot is probably healthy -- do a quick log
scan (2a) to confirm, then report. If anything looks off, dig into the relevant
section below.

## 2. Detailed analysis

### 2a. Logs

Pull a recent window from the server (filter at the source):
```bash
<env>-remote "journalctl -u st0x-hedge --since '1 hour ago' --no-pager | grep -iE 'error|warn|panic'"
<env>-remote "journalctl -u st0x-hedge -n 200 --no-pager"
```
Focus on:
- **Errors/warnings**, categorized: transient network issues (RPC timeouts,
  subgraph errors, otel export timeouts) -- usually noise; logic bugs or
  unexpected states -- critical; panics (`panic`, `thread.*panicked`) -- crash.
- **Restart loops**: repeated "Started st0x" / "Initializing" in quick
  succession suggests crash-looping.
- **Last activity timestamp**: if the service is active but the last log is
  hours old (during market hours), it may be hung.
- **Market hours context**: during market close (nights, weekends), reduced
  offchain activity is normal -- note it if relevant.

### 2b. Hedging

**Config-aware analysis.** Only assets with `trading = "enabled"` are expected
to be hedged. Onchain trades on disabled assets produce no offchain hedge by
design -- note as INFO, never WARNING/CRITICAL. Read the deployed config:
```bash
<env>-remote "grep -iE '\[assets|trading|rebalancing' /run/st0x/st0x-hedge.config"
```

Check (only for **trade-enabled assets**), using the `offchain_order_view`
data from section 1:
- **Are offchain orders being placed?** Onchain trades on enabled assets with
  no corresponding offchain orders = hedging broken.
- **Success rate**: Filled vs Failed vs Pending. High failure rate = problem.
- **Failed order patterns**: extract error messages. Common: "insufficient
  buying power" (underfunded), "market is closed" (outside hours), auth errors,
  "Order failed with no error reason" (often an un-fillable/restricted symbol
  the broker rejects post-acceptance -- if it repeats many times, flag it and
  consider whether the symbol should be `trading = "disabled"`).
- **Direction correctness**: onchain buys -> offchain sells and vice versa.
- **Post-deploy hedging**: if recently redeployed, confirm hedging resumed.

Event-type distribution (useful for spotting anomalies):
```bash
<env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY COUNT(*) DESC;"'
```

### 2c. Inventory and positions

From `position_view` (section 1):
- **Net position**: for trade-enabled assets, near-zero is expected -- a large
  absolute value means hedging is failing. For trade-disabled assets, non-zero
  is expected (unhedged by design) -- report as INFO.
- **Inventory snapshot freshness**: check the latest `InventorySnapshotEvent::*`
  `fetched_at` -- if stale (>~30 min while the bot is running), the inventory
  polling loop may have stopped.
  ```bash
  <env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT event_type, substr(payload,1,120) FROM events WHERE event_type LIKE \"InventorySnapshot%\" ORDER BY rowid DESC LIMIT 6;"'
  ```
- **Onchain vs offchain split**: large imbalances may be intentional (vault
  funding) or indicate a rebalancing issue.

### 2d. Rebalancing

If rebalancing is **enabled** for any asset (per config):
- Query recent rebalance events:
  ```bash
  <env>-remote 'sqlite3 /mnt/data/st0x-hedge.db "SELECT event_type, substr(payload,1,160) FROM events WHERE event_type LIKE \"%Rebalanc%\" ORDER BY rowid DESC LIMIT 20;"'
  ```
- Scan logs: `<env>-remote "journalctl -u st0x-hedge --since '24 hours ago' --no-pager | grep -i rebalanc | grep -ivE 'trace'"`.
- Reconcile any failure buckets found in section 1 (stuck mints/redemptions/USDC
  bridges) against what actually happened on-chain / at the broker before
  concluding value is stranded -- a "timeout" failure often self-heals or is
  premature.

If rebalancing is **disabled** for all assets, note it briefly and skip.

On-chain vault balances / Raindex order state are not exposed over
`<env>-remote`; if you need them, read them on-chain via `cast`/RPC against the
deployed OrderBook and token contracts (addresses in the deployed config), and
say so in the report rather than guessing.

## 3. Produce the health report

Structure the report as:

1. **Overall verdict**: one line -- Healthy / Degraded / Critical
2. **Service**: running/stopped, uptime since last start, deployed version
3. **Hedging**: working/broken/degraded, success rate, error patterns, gaps
4. **Rebalancing**: enabled/disabled, working/broken (if enabled), any stranded
   transfers
5. **Inventory**: net position, snapshot freshness, balance overview
6. **Issues found**: ranked by severity (CRITICAL > WARNING > INFO). For each
   issue, use this structured format so the user can copy-paste it directly to
   their team channel:

   ### `<Short issue name>`

   **What it does**: What the component/subsystem is supposed to do.

   **How it's erroring**: The exact error message pattern, how frequently it
   occurs, and where it appears (log source, DB status, etc.).

   **Why it errors**: Root cause or most likely explanation based on the data
   available.

   **Impact**: Whether it affects bot operation (trading, hedging, rebalancing)
   or is purely noise/observability. Be definitive -- say "None" if there's no
   operational impact, not "probably fine."

   Severity categories for reference:
   - CRITICAL: bot stopped, panics, hedging failure on enabled assets, crash
     loops, stranded equity/USDC value
   - WARNING: repeated failed orders on enabled assets, hedging gaps on enabled
     assets, stale inventory snapshots, growing net position on enabled assets
   - INFO: minor transient errors, expected market-hours gaps, unhedged
     positions on trade-disabled assets (working as designed)

Be direct. If everything is healthy, say so in 3-4 lines. Don't pad. If there
are problems, lead with the worst ones and be specific about what's wrong.

## 4. Follow-up diagnostic queries

Everything in this skill is already live via `<env>-remote`, so follow-up
questions need no special handling -- keep using `<env>-remote` to query the
live DB (`/mnt/data/st0x-hedge.db`) and logs (`journalctl -u st0x-hedge`).
Filter at the source and pull only what you need.

## Hard rules

1. Never modify any files or state -- this is a read-only diagnostic workflow.
   (Recovery/mutating CLI commands are out of scope here.)
2. Never run `cargo run` or start any services.
3. Never read secret files (`.env`, credentials, keys, the decrypted
   `/run/agenix/*`). Read the plaintext config (`/run/st0x/st0x-hedge.config`)
   only for operational flags, never secrets.
4. **One SSH probe, then stop on failure.** After section 0 fails, do not open
   any more SSH sessions -- extra attempts risk fail2ban while 1Password is
   unapproved. Report the single error and wait for the user. Do not guess
   credentials.
5. Never read the `.db` file as a whole -- always use `sqlite3` queries via the
   remote shim.
6. Report findings honestly -- don't minimize issues or speculate beyond what
   the data shows.
7. When inspecting source code to explain behavior, read the code at the
   deployed commit, never the current working-tree branch (see "Inspecting the
   codebase to interpret behavior"). Never `git checkout` -- use
   `git show <commit>:<path>` / `git grep <commit>`.

## Failure modes

- **`<env>-remote` unreachable / agent refused / permission denied**: section 0
  already failed. Report that one error and stop. Do **not** retry, key-scan,
  port-scan, or open more SSH sessions -- that is how fail2ban bans the IP when
  the user is AFK and cannot approve 1Password.
- **Empty DB / no events**: the bot may have just been deployed or the DB reset.
  Note this rather than reporting "everything is broken."
- **Dashboard looks fine but hedging is broken**: remember the blind spot in
  section 1 -- failed counter-trades never render on the dashboard. Always
  confirm via `offchain_order_view` Failed counts and logs.
