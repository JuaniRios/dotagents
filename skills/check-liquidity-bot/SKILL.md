---
name: check-liquidity-bot
allowed-tools: Bash(gcloud:*), Bash(curl:*), Bash(jq:*), Bash(git:*), Bash(date:*), Bash(gh:*), Read, Grep
description: Diagnose the liquidity bot's health (hedging, rebalancing, errors, overall status) via the IAP dashboard APIs, Cloud Logging, and Datasette. SSH is not used for the check.
argument-hint: <prod|staging>
---

# /check-liquidity-bot

**Required argument**: `prod` or `staging`. Anything else: say
`Usage: /check-liquidity-bot <prod|staging>` and stop.

This command is **read-only**. It does not SSH into an operator session, does
not run `st0x-cli`, and does not POST `/liquidity-write`. Those are the fix
path (see **Fix path** at the end). Jakub is exposing the same CLI through the
ops API and a local client; until that is the default, diagnosis stays on
HTTPS + logs + Datasette.

## Access

Both environments are GCE VMs under docker compose. Humans reach them with a
`@t0trade.com` Google identity (`gcloud auth login you@t0trade.com`). Membership
of `engineering@t0trade.com` reads logs and Grafana; dashboard IAP is
`liquidity-readers@` + `liquidity-admins@`.

| | prod | staging |
|---|---|---|
| GCP project | `t0-liquidity` | `t0-liquidity-staging` |
| VM / zone | `t0-liquidity` / `europe-west3-b` | `t0-liquidity-staging` / `europe-west3-b` |
| Dashboard | `https://liquidity.t0trade.com` | `https://liquidity-staging.t0trade.com` |
| IAP backend | `t0-liquidity-dashboard` | `t0-liquidity-staging-dashboard` |
| Bot log | `projects/t0-liquidity/logs/liquidity-botlogs` | `projects/t0-liquidity-staging/logs/liquidity-botlogs` |
| Grafana `var-env` | `t0-liquidity` | `t0-liquidity-staging` |

Other log streams (same project): `liquidity-orders`, `gcplogs-docker-driver`
(raw stdout, TRACE-heavy), `syslog`. Grafana:
[Deployments](https://grafana.t0trade.com/d/t0-deployments/deployments),
`t0-liquidity`, `t0-liquidity-orders`, `t0-liquidity-performance`,
`t0-liquidity-pnl`, `t0-liquidity-logs`.

Config-as-data lives in `T0Trade/t0.devops`
(`terraform/<env>-liquidity/st0x-hedge.toml`), not in this repo.

### Bind the environment (once)

```bash
set -euo pipefail
environment='<validated prod or staging>'
ZONE=europe-west3-b
if [ "$environment" = staging ]; then
  PROJECT=t0-liquidity-staging
  HOST=https://liquidity-staging.t0trade.com
  BACKEND=t0-liquidity-staging-dashboard
  INSTANCE=t0-liquidity-staging
  LOGNAME='projects/t0-liquidity-staging/logs/liquidity-botlogs'
  CONFIG_PATH=terraform/staging-liquidity/st0x-hedge.toml
else
  PROJECT=t0-liquidity
  HOST=https://liquidity.t0trade.com
  BACKEND=t0-liquidity-dashboard
  INSTANCE=t0-liquidity
  LOGNAME='projects/t0-liquidity/logs/liquidity-botlogs'
  CONFIG_PATH=terraform/production-liquidity/st0x-hedge.toml
fi
```

### IAP token for dashboard DTO APIs

The SPA paths (`/health`, `/pnl`, `/trades`, `/logs`, `/orders/*`,
`/transfers/*`, `/performance/*`) sit on the **dashboard** IAP backend
(Google-managed OAuth). Mint a user identity token whose audience is that
backend's IAP client. Do **not** use `/liquidity-read/*` here: those backends
reject gcloud tokens on purpose (desktop OAuth client only, used by
`st0x-liquidity-client`).

```bash
CLIENT_ID=$(gcloud compute backend-services describe "$BACKEND" \
  --global --project "$PROJECT" --format='value(iap.oauth2ClientId)')
TOKEN=$(gcloud auth print-identity-token --audiences="$CLIENT_ID" --include-email)

api() {
  # usage: api /health   or   api /trades --data-urlencode 'limit=30'
  local path="$1"; shift
  curl -sS -m 90 -o "$OUT/body.json" -w '%{http_code}\n' \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
    -G "$HOST$path" "$@"
}
```

`$OUT` is the session scratchpad. Write the body with `-o` and let `-w` print
only the status.

### Cloud Logging

Prefer the project's own log (you hold PAM, so `logging.viewer` on the project
works). If that 403s, the hub bucket is the `engineering@` path:

```bash
gcloud logging logs list --project "$PROJECT"

gcloud logging read "logName=\"${LOGNAME}\" AND jsonPayload.level!=\"TRACE\" AND jsonPayload.level!=\"DEBUG\"" \
  --project "$PROJECT" --freshness 1h --limit 200 --order desc --format json
```

Hub fallback (same lines, no per-project viewer):

```bash
gcloud logging read "logName=\"${LOGNAME}\" AND jsonPayload.level!=\"TRACE\"" \
  --project=t0-observability --bucket=aggregated-logs --location=europe-west3 \
  --view=_AllLogs --freshness=1h --limit=200 --order=desc --format=json
```

Filter on `jsonPayload.message` and `jsonPayload.level`, never `textPayload`
(a textPayload filter returns nothing). `gcplogs-docker-driver` is TRACE-heavy:
always add `AND NOT jsonPayload.message:"TRACE"`.

### Datasette (ad-hoc SQL)

Datasette serves the live DB on the VM at `127.0.0.1:8081`. It is **not** on
the public load balancer. Reach it with one IAP-SSH curl; that is a Datasette
query, not an operator session. Do not `docker exec`, do not open a shell.

```bash
datasette() {
  local sql="$1"
  gcloud compute ssh "$INSTANCE" --project "$PROJECT" --zone "$ZONE" \
    --tunnel-through-iap --quiet \
    --command "curl -sS --get 'http://127.0.0.1:8081/st0x-hedge.json' --data-urlencode 'sql=${sql}' --data-urlencode '_shape=objects'"
}
```

Use this for views the HTTP API does not expose (`position_view`, full
`offchain_order_view` status split, raw `events`). Prefer the DTO APIs when
they already answer the question.

## 0. Connectivity gate

One `/health` call first. Do not parallelize it with anything else.

```bash
api /health
```

- **200** and JSON with `status`, `gitCommit`, `uptimeSeconds`: continue.
- **401/403**: IAP rejected the identity. Report the status and body, stop.
  Common causes: not logged in as `@t0trade.com`, wrong audience, not in
  `liquidity-readers@` / `liquidity-admins@`.
- **000** / timeout: transport. Retry once. Then stop.
- **502**: the dashboard LB is up but the bot/dashboard container is not.
  Critical. Continue only with Cloud Logging to see why.

## Inspecting the codebase

Do not reason from the current checkout. `/health` returns `gitCommit` (the
image's `ST0X_GIT_COMMIT`). Read source with `git show <commit>:<path>` /
`git grep <pattern> <commit>` against `~/Github/st0x.liquidity`. Never
`git checkout`. If the SHA is missing locally, say so and treat code claims
as provisional.

Trading flags come from the live config, not the app repo:

```bash
gh api -H 'Accept: application/vnd.github.raw' \
  "repos/T0Trade/t0.devops/contents/${CONFIG_PATH}"
```

Only assets with `trading = "enabled"` are expected to hedge. Disabled-asset
fills with no hedge are INFO.

## 1. First pass

Batch after `/health` is 200. Profitability questions go to `/pnl-review`
(same IAP host; that skill owns `/pnl`).

```bash
api /orders/pending
api /trades --data-urlencode 'limit=30'
api /transfers --data-urlencode 'limit=30'
api /transfers/interrupted
api /performance/reliability
api /logs --data-urlencode 'level=ERROR,WARN' --data-urlencode 'limit=100'
```

Then Datasette for the two views the DTO APIs do not fully cover:

```bash
datasette 'SELECT status, COUNT(*) AS n FROM offchain_order_view GROUP BY status'
datasette 'SELECT * FROM position_view'
datasette 'WITH latest AS (SELECT aggregate_id, MAX(sequence) AS ms FROM events GROUP BY aggregate_id)
SELECT e.event_type, COUNT(*) AS n
FROM events e JOIN latest l ON e.aggregate_id = l.aggregate_id AND e.sequence = l.ms
WHERE e.event_type LIKE "%Failed%" OR e.event_type LIKE "%Rejected%" OR e.event_type LIKE "%DetectionFailed%"
GROUP BY e.event_type ORDER BY n DESC'
```

Always look at the offchain-order status split even when the dashboard looks
clean. Filled / Failed / Cancelled / Pending across every symbol is the
fastest hedge-health signal. Pair it with a log scan for
`Offchain venue rejected` / `broker reports Failed`.

If `/health` is 200, interrupted transfers are empty, pending orders are not
stuck, net positions on trade-enabled assets are near zero, and ERROR/WARN
logs are empty or expected noise, do a short log scan (2a) and report Healthy.

## 2. Detailed analysis

### 2a. Logs

Cloud Logging is the historical source; `/logs` is the bot's own rotated
files (same process, shorter window).

Focus on:

- **Errors/warnings**: RPC timeouts / otel export = usually noise; logic bugs
  or unexpected states = critical; `panic` / `thread.*panicked` = crash.
- **Restart loops**: repeated "Started st0x" / "Initializing".
- **Last activity**: active process, last line hours old during market hours
  = hung.
- **Market hours**: regular hours, plus extended hours only for assets with
  `extended_hours_counter_trading = "enabled"`. Overnight / weekend / holiday
  with zero fills is the correct state, never a finding.
- Known lines: `database or disk is full`, `Order fill poll failed`,
  `Skipping Alpaca-to-Base USDC rebalance` (unsettled Alpaca cash; vault
  refills next morning in 10k slices), `withdraw4 from vault`,
  `Alpaca to Base rebalance completed`.

### 2b. Hedging

Only trade-enabled assets. Onchain trade on an enabled asset with no
offsetting offchain order = hedging broken. High Failed rate = problem.
Common rejects: insufficient buying power, market closed, auth,
"Order failed with no error reason" (un-fillable symbol — consider
`trading = "disabled"`). Onchain buy -> offchain sell and vice versa.

### 2c. Inventory and positions

From `position_view`: near-zero net on trade-enabled assets is expected; a
large absolute value means hedging is failing. Non-zero on trade-disabled
assets is INFO.

Inventory snapshot recency is **not** a liveness signal. The poller
suppresses unchanged snapshots, so a static book (market closed) freezes
the newest event for hours. Do not report that as "polling stopped". Scan
logs for `Inventory polling failed` on `target: "inventory"` instead.

```bash
datasette 'SELECT event_type, substr(payload,1,120) AS payload FROM events WHERE event_type LIKE "InventorySnapshot%" ORDER BY rowid DESC LIMIT 6'
```

### 2d. Rebalancing

If any asset has rebalancing enabled: `/transfers`, `/transfers/interrupted`,
`/performance/rebalances`, `/performance/equity-rebalances`, plus logs
matching `rebalanc`. A "timeout" failure often self-heals; reconcile against
broker / chain before calling value stranded.

On-chain vault balances are not in these APIs. Read them with `cast` against
addresses in the t0.devops config, and say so.

## 3. Health report

1. **Verdict**: Healthy / Degraded / Critical
2. **Service**: `/health` status, `uptimeSeconds`, `gitCommit`
3. **Hedging**: working/broken/degraded, success rate, error patterns
4. **Rebalancing**: enabled/disabled, stranded transfers
5. **Inventory**: net position, snapshot freshness
6. **Issues**, ranked CRITICAL > WARNING > INFO, each as:

   ### `<Short issue name>`

   **What it does**:
   **How it's erroring**:
   **Why it errors**:
   **Impact**: (say "None" if none)

   CRITICAL: bot down, panics, hedging failure on enabled assets, crash
   loops, stranded equity/USDC. WARNING: repeated failed orders or growing
   net on enabled assets. INFO: expected market-hours gaps, unhedged
   disabled assets.

If healthy, 3-4 lines. If not, lead with the worst issue.

## 4. Follow-up

Keep using `api`, Cloud Logging, and `datasette`. Do not switch to an
operator SSH session for more of the same questions.

## Hard rules

1. Read-only. No `st0x-cli`, no `docker exec` of a mutating command, no
   POST to `/liquidity-write`, no `systemctl`, no deploy.
2. Never interpolate user input into URLs; use `--data-urlencode`.
3. Never print secrets or Secret Manager payloads.
4. One `/health` probe first; after 401/403, stop.
5. Reason from the deployed `gitCommit`, not the working tree.
6. Do not treat a stale inventory snapshot as a dead poller.
7. `/pnl-review` for profitability, not eyeballing trades.

## Failure modes

- **gcloud missing / not `@t0trade.com`**: report `gcloud auth list` and stop.
- **IAP 401/403**: identity or group. Stop. Do not fall back to SSH for the
  check.
- **Datasette curl fails**: container down or port not published. Note it;
  continue with DTO APIs and logs.
- **Per-project logging 403**: retry via the `t0-observability` hub bucket.
- **Empty DB / no events**: just deployed, or DB reset. Note, do not call
  everything broken.
- **Repeated Failed on one symbol**: usually broker-rejected / un-fillable.
  Flag `trading = "disabled"`.

## Fix path (out of scope for this command)

Mutations still need IAP SSH into the bot container, until the local ops
client is the default:

```bash
gcloud compute ssh "$INSTANCE" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command 'sudo docker exec "$(sudo docker ps -qf name=bot)" /bin/st0x-cli \
    --config /run/t0-config/st0x-hedge.toml \
    --secrets /run/t0-secrets/t0-liquidity-secrets.toml \
    <command>'
```

`sudo` is required (OS Login user is not in `docker`). The image has no
shell; `docker exec` must invoke `/bin/st0x-cli` directly. The IAP-gated
write API is `POST /liquidity-write/transfers/recheck/{kind}/{id}` and
`POST /liquidity-write/transfers/resume`, via `st0x-liquidity-client`
(desktop OAuth, not gcloud tokens). Do not run either from this skill.
