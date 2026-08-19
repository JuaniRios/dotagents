---
name: check-issuance-bot
allowed-tools: Bash(ssh:*), Bash(nix:*), Bash(age:*), Bash(awk:*), Bash(sqlite3:*), Bash(curl:*), Bash(cast:*), Bash(systemctl:*), Bash(journalctl:*), Bash(git:*), Read, Grep, Glob
description: Diagnose the issuance bot's health in production or staging over SSH with the repository-whitelisted local identity. Runs a general read-only service, API, event-store, signer, backfill, vault-poller, RPC, and Alpaca check first; investigates stuck mints/redemptions and guides carefully confirmed recovery only when needed.
argument-hint: <prod|staging>
---

# check-issuance-bot

**Required argument**: `prod` or `staging`.

> **There is no deployed staging issuance host yet.** The repo carries staging
> keys, `config.staging.toml`, and staging infra apps, but nothing runs behind
> them. If the user asks for `staging`, say so and confirm they meant `prod`
> before connecting -- do not report an unreachable host as an outage.

This command queries the selected live issuance server directly. It is
health-check-first and read-only by default. Do not recover, restart, deploy,
edit the database, or run an operator mutation merely because a problem is
found.

If the argument is missing or invalid, say:

`Usage: /check-issuance-bot <prod|staging>`

and stop.

Run from `~/Github/st0x.issuance`.

## Access the live server safely

The SSH identity is a plain local key, not a Nushell function, 1Password
identity, SSH-agent selection, or repo remote wrapper. Resolve and validate it
before opening any connection:

```bash
set -euo pipefail

environment='<validated prod or staging>'
shopt -s nullglob
matching_identities=()

for public_identity in "$HOME"/.ssh/*.pub; do
  held_public_key=$(awk 'NR == 1 { print $1 " " $2 }' "$public_identity")
  authorization=$(
    ST0X_ENVIRONMENT="$environment" \
    ST0X_HELD_PUBLIC_KEY="$held_public_key" \
    nix eval --raw --impure --expr '
      let
        keyConfig = import ./keys.nix;
        role = builtins.getAttr (builtins.getEnv "ST0X_ENVIRONMENT") keyConfig.roles;
      in
        if builtins.elem (builtins.getEnv "ST0X_HELD_PUBLIC_KEY") role.ssh
        then "authorized"
        else "unauthorized"
    '
  )
  private_identity="${public_identity%.pub}"
  if [ "$authorization" = authorized ] && [ -s "$private_identity" ]; then
    matching_identities+=("$private_identity")
  fi
done

if [ "${#matching_identities[@]}" -ne 1 ]; then
  printf 'Expected exactly one locally held identity authorized by keys.nix; found %s\n' \
    "${#matching_identities[@]}" >&2
  exit 1
fi
identity="${matching_identities[0]}"

encrypted_host="infra/.remote-$environment.age"
host_ip=$(age -d -i "$identity" "$encrypted_host")
test -n "$host_ip"
target="root@$host_ip"
ssh_options=(
  -F /dev/null
  -i "$identity"
  -o IdentitiesOnly=yes
  -o IdentityAgent=none
  -o BatchMode=yes
)

run_remote() {
  ssh "${ssh_options[@]}" "$target" "$1"
}
```

`keys.nix` is authoritative. Discover identities only through public sidecars
under `~/.ssh/*.pub`, compare their algorithm and base64 body to the selected
environment's `roles.<env>.ssh`, and require the corresponding private file.
Do not assume a filename, fingerprint, key owner, or key comment. Require
exactly one match; zero means this machine lacks an authorized key, while
multiple matches are ambiguous and require user direction. Never inspect or
try unmatched private keys.

`-F /dev/null` is mandatory so the user's global SSH config cannot add another
identity. Every SSH call must use the same explicit `ssh_options`; never call
the repo's remote executable or a direct flake remote app, because those
abstractions obscure the exact SSH identity set.

### Connectivity gate

Run exactly one probe before any other remote command and never parallelize it:

```bash
run_remote 'echo ok'
```

If it prints `ok`, continue and batch subsequent read-only checks into as few
remote calls as practical.

On any failure, timeout, refusal, permission error, or host-key error:

1. Report the exact error from that one probe.
2. Stop all remote work immediately.
3. Do not retry, use another transport, inspect keys, run `ssh -v`, key-scan,
   port-scan, or add Tailscale probes.
4. Tell the user to correct the host key, network, or fail2ban state and rerun
   `/check-issuance-bot <env>` after access works.

## Know the deployed layout

Both environments are NixOS hosts:

- Service: `st0x-issuance.service`
- Local HTTP API: `http://localhost:8000`
- SQLite event store: `/mnt/data/issuance.db`
- Deployed revision: `/run/st0x/st0x-issuance.git-rev`
- Per-service profile:
  `/nix/var/nix/profiles/per-service/st0x-issuance/`
- Secrets: `/run/agenix/st0x-issuance.env`
- On-host operator CLI: `issuer`

There is no Docker deployment. Do not use `docker`, legacy `/mnt/volume_*`
paths, or infer the running build from the system Nix generation. The service
profile and system generation move independently.

The host may not have `python3` or `jq`. Filter and aggregate on the server with
`journalctl`, `sqlite3`, shell tools, and raw `curl`; perform JSON formatting or
exact Decimal calculations locally.

Never print secret values. Source the secret file only inside the remote
payload that needs it, consume the value there, and print only safe results such
as HTTP status, chain ID, or an aggregate response with credentials removed.

## What the CLI and API are for

Use the live API for service-owned inspection and recovery:

| Surface | Typical use | Default safety |
|---|---|---|
| `GET /admin/stuck` | List mints/redemptions that need attention | Read-only |
| `POST /admin/reprocess/mint/<id>` | Resume a stuck mint | Mutating; may submit or confirm on-chain work |
| `POST /admin/recover/redemption/<id>` | Resume a redemption through its state-aware recovery path | Mutating; may call Alpaca or submit/confirm a burn |
| `POST /admin/force-complete/redemption/<id>` | Record a specifically verified landed burn | Irreversible terminalization |
| `POST /admin/close/redemption/<id>` | Close after explicit off-chain reconciliation | Irreversible terminalization |

Admin endpoints require `X-API-KEY`. Read `ISSUER_API_KEY` only inside the
remote command and never echo it.

Use the on-host `issuer` CLI for operator workflows tied directly to the event
store and deployed configuration:

- Safe orientation: `issuer --help`, `issuer <subcommand> --help`
- Read-only domain state: `issuer status <UNDERLYING>`
- Mutations or operational workflows include `freeze`, `unfreeze`,
  `migrate-receipts`, `confirm-custody`, `force-complete-redemption`,
  `sweep-legacy-receipts`, and `burn-excess ... --execute`
- `verify-custodians` performs credential/signing checks; `--smoke` submits a
  live zero-amount transaction
- `burn-excess` is dry-run unless `--execute` is present, but still follow its
  own evidence and confirmation workflow

Treat the deployed binary's `--help` and the source at the deployed revision as
authoritative. Do not rely on remembered flags or stale docs.

## Inspect deployed code, not the current checkout

When a log, state, API response, or CLI option needs source interpretation:

1. Read the deployed revision from the server.
2. Use local read-only commands such as:
   `git show <revision>:<path>` and `git grep <pattern> <revision>`.
3. Never check out the revision.
4. If the revision is unavailable locally, say that source-based conclusions
   are provisional. Do not silently read the current working tree instead.

## 1. General health check -- always run this first

Run the complete read-only pass even when the user mentions one stuck
transaction. A clean `/admin/stuck` response alone is not proof of health.

Batch these checks after the successful connectivity gate.

### Service and deployed build

Collect:

```bash
systemctl is-active st0x-issuance.service
systemctl show st0x-issuance.service \
  -p ActiveState -p SubState -p NRestarts -p MainPID \
  -p ExecMainStartTimestamp --value
cat /run/st0x/st0x-issuance.git-rev
nix-env -p /nix/var/nix/profiles/per-service/st0x-issuance \
  --list-generations | tail -3
readlink -f /nix/var/nix/profiles/per-service/st0x-issuance
```

Healthy means the service is active, has a live PID, is not crash-looping, and
the recorded revision/profile matches the deployment the user expects. Do not
call a revision stale merely because it differs from the local checkout.

### Logs and startup sequence

Use the actual service start timestamp and filter at the source:

- ERROR/WARN/PANIC entries since start
- restart/initialization loops
- signer initialization (`Turnkey wallet initialized`, signer backend resolved)
- required view rebuild completion
- receipt-inventory reconciliation/backfill completion
- one poller per configured vault/network
- recent poll cursor lines showing block advancement
- automatic recovery exhaustion or manual-intervention messages
- latest meaningful activity timestamp

Scan logs before making any probe that could create a warning. Attribute
warnings caused by this check to the check itself.

A quiet environment can have little business activity; that is not a
failure if service loops and block cursors are advancing.

### API and stuck work

Call authenticated `GET /admin/stuck`, capturing the HTTP status and body.
Report every entry with:

- aggregate type and ID
- network, asset, and quantity
- state and age
- detail
- persisted `tx_hash`/`tx_id`, if present

`200` with an empty list means only that no request currently crosses the
endpoint's stuck threshold. It does not replace the other health signals.

Do not hand-maintain a guessed list of terminal events. Prefer the deployed
`/admin/stuck` projection; if a DB query appears to disagree, inspect the
aggregate and view code at the deployed revision before raising an alarm.

### Asset, vault, backfill, and poller coverage

From startup logs and read-only SQLite queries, establish:

- configured/enabled asset count
- listing count by network
- distinct vaults expected
- distinct vaults actually polled
- receipt backfill/reconciliation completed for every enabled listing
- backfill start blocks are plausibly near the intended deployment/checkpoint
- poll checkpoints advance at the expected chain cadence
- no missing or duplicate aggregate/view coverage

A registered asset that is not backfilled or polled is degraded even when the
service is active.

### External dependencies

Use safe, read-only probes and expose no credentials:

- Alpaca account endpoint: expect HTTP `200`
- RPC: request `eth_chainId` and verify it matches each configured network
- signer: rely on successful startup initialization and recent successful
  service use; do not create a transaction merely to prove signing
- API: authenticated `/admin/stuck` must return `200`

`HTTP 000` from Alpaca is commonly a misspelled variable. Confirm the deployed
environment contains the expected variable *names*--especially
`ALPACA_API_BASE_URL`--without printing values before diagnosing an outage.

Do not run `verify-custodians --smoke`, restart the service, or send a live
transaction as part of the general check.

### Optional database checks

Use only targeted `SELECT` queries. Run `PRAGMA quick_check` only when database
symptoms justify it. Never copy/download the whole production DB for a routine
health check and never use `Read` on it.

## 2. Decide whether the bot is working properly

Call the bot healthy only when all applicable signals pass:

- service active, stable, and not restarting
- deployed revision/profile identified and expected
- no unexplained ERROR/WARN/PANIC activity
- signer initialized
- required views rebuilt
- all assets/listings covered by backfill and active vault pollers
- block cursors advancing
- authenticated admin API working
- `/admin/stuck` empty, or every returned item understood and explicitly
  reported
- Alpaca reachable with HTTP `200`
- RPC chain IDs correct and polling current

Use `Degraded` when the bot runs but one or more responsibilities are impaired.
Use `Critical` when it is stopped/crash-looping, cannot sign, cannot reach a
required external system, has stranded financial state, or cannot safely
process requests.

## 3. Diagnose problems without mutating state

For each issue:

1. Pull only relevant logs and event history, filtered by aggregate ID,
   transaction hash, asset, network, and time.
2. Read the deployed source for the state/error.
3. Determine whether automatic recovery is still active, exhausted, or waiting
   on an external result.
4. Reconcile exact on-chain state when a mint deposit or redemption burn is
   uncertain.
5. Present evidence, impact, and the safest next action.

For financial comparisons use exact integer or `Decimal` arithmetic--never
floating point. A burn/deposit match must agree on network, contract/vault,
addresses, exact amount, receipt/event semantics, transaction status, and
aggregate context. Nearby or approximate matches are leads, not proof.

Do not restart a service as a diagnostic shortcut. Startup runs automatic
recovery, so a restart can trigger external actions and is itself mutating.

## 4. Recovery guidance -- confirmation boundary

First present:

- environment and deployed revision
- affected aggregate and current state
- API/CLI operation proposed
- exact external/on-chain evidence
- expected state change and possible external side effects
- verification plan
- exact command or request, with secrets redacted

Then obtain explicit confirmation in the current session before **every**
state-changing action, in either environment.

Confirmation is required for:

- any admin `POST`, including normal reprocess/recover
- any state-changing `issuer` command
- `verify-custodians --smoke`
- `burn-excess ... --execute`
- service start/stop/restart
- deploy/rollback
- database writes, migrations, restores, or file replacement
- funding, transfers, burns, mints, or any other on-chain transaction

A confirmation for normal recovery does not authorize force-completion,
closing, restart, deployment, or another aggregate. Ask again when the action
or target changes.

Prefer the least final path:

1. Allow active automatic recovery to finish when evidence shows progress.
2. With confirmation, use the aggregate's normal recovery endpoint.
3. Re-read `/admin/stuck`, the aggregate state, logs, and on-chain result.
4. Force-complete only a burn that the deployed verifier can prove exactly.
5. Close only after off-chain reconciliation and acknowledgement of any
   unresolved persisted transaction identity.

Never force-complete from an approximate event match. Never close merely to
make `/admin/stuck` empty. Never submit a second mint deposit while an existing
prepared/submitted identity is uncertain or still mineable.

The on-host CLI may have its own interactive confirmation. That is an
additional safeguard, not a substitute for user confirmation before
invocation.

## 5. Verify any approved action

After a confirmed mutation:

- capture the response/status without secrets
- re-fetch `/admin/stuck`
- reload the specific aggregate/view state
- inspect relevant logs
- verify any claimed on-chain result by receipt and exact events
- state whether it completed, progressed, stayed unchanged, or failed
- do not cascade into another mutation without new confirmation

## 6. Report

Lead with one line: `Healthy`, `Degraded`, or `Critical`.

Then report:

1. Environment, deployed revision, service state, uptime/restarts
2. API, signer, views, backfill, vault pollers, RPC, and Alpaca
3. Stuck aggregates
4. Issues ranked `CRITICAL`, `WARNING`, `INFO`
5. Read-only investigation performed
6. Mutations: `None` unless explicitly approved; otherwise exact actions and
   verification
7. Concrete next step

If healthy, keep the report brief but name the signals actually checked. If
degraded or critical, lead with the worst operational impact and avoid
speculation.

## Hard rules

1. The general check is read-only and always comes first.
2. Use only `run_remote` with the dynamically discovered, whitelist-verified
   identity and explicit SSH options defined above.
3. Run one connectivity probe; after failure, stop without retrying.
4. Never parallelize SSH calls; batch sequential diagnostics.
5. Never reveal secrets or access secret files locally.
6. Never mutate API, CLI, systemd, deploy, database, or chain state without
   explicit current-session confirmation.
7. Never use restart as a harmless health probe.
8. Never use approximate financial/on-chain evidence.
9. Never use floating point for token/share amounts.
10. Never infer deployed behavior from the current checkout.
11. Never treat empty `/admin/stuck` as a clean bill of health.
12. Never use Docker or legacy production paths.
13. Never write to the live SQLite database during diagnosis.
14. Never minimize an issue or claim a check passed when it was not run.

## Failure modes

- Identity or whitelist validation failure: report which prerequisite failed
  and stop without trying another key.
- SSH failure: report the one exact error and stop.
- Host-key verification failure: the known-host record must be corrected; do
  not bypass verification or run `ssh-keyscan`.
- `docker` or legacy-volume path errors: use the NixOS layout above.
- Missing on-host `python3`/`jq`: consume raw output remotely and process
  locally.
- `/admin/stuck` 401: verify the secret variable name and deployed config
  without printing the key.
- Alpaca `HTTP 000`: first rule out `ALPACA_API_BASE_URL` misspelling/empty
  expansion.
- System generation older than service start: inspect the per-service profile;
  this alone is not a failed deploy.
- Apparent non-terminal DB rows absent from `/admin/stuck`: verify the deployed
  view/aggregate terminal classification before alarming.
- Missing/reverted/unknown transaction receipt: treat the result as uncertain;
  do not replace, duplicate, close, or force-complete it.
- Inconclusive RPC/on-chain history: report it as inconclusive and stop before
  mutation.
