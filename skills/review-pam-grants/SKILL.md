---
name: review-pam-grants
description: >
  Review Privileged Access Manager grants waiting on the user and approve
  them after the user confirms. Covers both orgs: T0 (`@t0trade.com`) and
  S01 (`@s01issuer.com`). First check that both accounts have valid tokens,
  and run gcloud-login for any that do not. Then find open grants and
  verify each is safe. Last, wait for the user's confirmation and approve.
  Use when asked to approve or check PAM, approve a tf-apply, prod-ssh, or
  app-deploy grant, or when a gated t0.devops or s01.devops apply is stuck on Await PAM
  approval.
allowed-tools: Bash(gcloud:*), Bash(gh:*), Read, Grep
---

# /review-pam-grants

Three steps, always in this order:

1. Check that both accounts have valid tokens. Run `gcloud-login` for
   each one that does not.
2. Find open PAM grants and verify each one is safe.
3. Wait for the user's confirmation. If they confirm, approve.

Never approve on sight.

Approving `tf-apply-owner` gives CI a time-bound `roles/admin` on that
GCP project (not standing owner). Production stacks need **2 of 4**
votes. One CLI approve is one vote.

## Never use IPv6

Never use IPv6. On this network IPv6 connections hang, and Python tools
(`gcloud`, `zulipctl`) try IPv6 first, so they stall until a timeout and
then report a vague error. Before any `gcloud` or Zulip call, turn IPv6
off on every network service:

```bash
networksetup -listallnetworkservices | tail -n +2 | sed 's/^\*//' |
  while IFS= read -r s; do networksetup -setv6off "$s"; done
```

This is macOS. On a Linux host, check `ip -6 addr show scope global`; if
it lists an address, report that IPv6 is on and stop. Do not turn IPv6
back on.

## 0. Check both accounts

The user has one Google account per org. Each org's projects accept only
that org's account:

| Org | Account | Projects |
| --- | ------- | -------- |
| T0  | `@t0trade.com` | `t0-*` |
| S01 | `@s01issuer.com` | `s01-*` |

Check both accounts before you search, every time:

```bash
for ACCOUNT in juan@t0trade.com juan@s01issuer.com; do
  if gcloud auth print-access-token --account="$ACCOUNT" >/dev/null 2>&1; then
    echo "$ACCOUNT ok"
  else
    echo "$ACCOUNT EXPIRED"
  fi
done
```

If either account is missing, expired, or reports a reauth error, run the
`gcloud-login` skill for that account. Do this always; do not tell the
user to log in by hand and stop, and do not skip that org. Log in one
account at a time. After the logins, run the check again. Do not continue
until both accounts are `ok`.

Do not switch the active account. Pass `--account="$ACCOUNT"` on every
`gcloud` command, with the account for that project's org. Do not suppress
`gcloud` stderr: an auth failure must not look like "no grants". If a
reauth error appears later in the run, run `gcloud-login` for that
account and repeat the search for that org. Do not impersonate a
service account.

## 1. Find open grants

Search every project the account can see. Do not search only a fixed
list: a fixed list misses new gated projects. For each project, find the
entitlements this account can approve, then list the grants on each.
Run it once per account (`juan@t0trade.com`, then `juan@s01issuer.com`):

```bash
bash -c '
ACCOUNT="$1"
ERR=$(mktemp)
for PROJECT in $(gcloud projects list --account="$ACCOUNT" --format="value(projectId)"); do
  if ! OUT=$(gcloud pam entitlements search --account="$ACCOUNT" \
      --caller-access-type=grant-approver --location=global \
      --project="$PROJECT" --format="value(name)" 2>"$ERR"); then
    if grep -qiE "reauth|credentials|login" "$ERR"; then
      echo "AUTH ERROR on $PROJECT:"; cat "$ERR"; exit 1
    fi
    continue  # 403 or PAM API disabled: skip this project
  fi
  for NAME in $OUT; do
    case "$NAME" in projects/*/locations/global/entitlements/*) ;; *) continue ;; esac
    ENTITLEMENT_ID=${NAME##*/}
    echo "== $PROJECT $ENTITLEMENT_ID"
    gcloud pam grants search --account="$ACCOUNT" \
      --entitlement="$ENTITLEMENT_ID" --location=global --project="$PROJECT" \
      --caller-relationship=can-approve --format=json
  done
done' _ "$ACCOUNT"
```

Skip a project that returns 403, returns nothing, or has the PAM API
disabled. Do not skip an auth or reauth error: follow step 0.

Known gated projects. This is a check, not the search scope. Expect the
search to find at least these:

- T0: `t0-liquidity` `t0-oracle` `t0-pricing` `t0-bebop` `t0-artifacts`
  `t0-price-publisher` `t0-alpaca-ops` `t0-exporters`
  `t0-loopyloupe-operator` `t0-uni-v4-price-oracle` `t0-turnkey-audit`
  `st0x-artifacts`
- S01: `s01-issuance` `s01-artifacts` `s01-observability`
  `s01-alpaca-ops` `s01-exporters` `s01-tsalt-ui` `s01-tsalt` `s01-site`

If the search finds an approvable entitlement on a project that is not
on this list, report it. Verify it with the same rules.

Gotchas:

- `gcloud pam` writes `Parsed [...] resource:` info lines to stderr.
  These are not errors. Use the exit code to find a failure, not the
  stderr text.
- `--format='value(name)'` can give output that the shell splits badly.
  Use only words with the full `projects/.../entitlements/<id>` shape.
  The entitlement ID is the last path segment. Ignore all other words.
- In zsh, `set -- $x` and unquoted `$x` do not word-split. Run loops
  that split fields under `bash -c`, as above.

`can-approve` never returns the user's own grant: PAM does not let a
requester approve their own request, even when they are a listed
approver. If the user asks about a grant they requested, list it with
`--caller-relationship=had-created`, report its approvals, and name the
other approvers who can still vote. Do not try to approve it.

Keep grants whose `state` is `APPROVAL_AWAITED`. If the filter flag is
rejected, list and filter locally.

If none: say so and stop. Do not create a grant.

For each remaining grant:

```bash
gcloud pam grants describe "$GRANT_NAME" --account="$ACCOUNT" --format=json
gcloud pam entitlements describe "$ENTITLEMENT_ID" --account="$ACCOUNT" \
  --location=global --project="$PROJECT" --format=json
```

Record: project, entitlement id, grant name, state, requester,
requested duration, create time, justification, privileged role,
`approvals_needed`, who already approved.

Never print Secret Manager payloads or secrets toml.

## 2. Verify each grant is safe

Pull the GitHub Actions URL and commit from the justification when
present. Fetch the run and the commit's files (`gh run view`,
`gh api repos/$DEVOPS_REPO/commits/$SHA`). `$DEVOPS_REPO` is
`T0Trade/t0.devops` for T0 and `S01-Issuer/s01.devops` for S01.

**Expected apply** (looks good):

- Entitlement is `tf-apply-owner`.
- Requester is `tf-apply@$PROJECT.iam.gserviceaccount.com` (the only
  eligible principal on that entitlement).
- Requested duration is `14400s` (4 h).
- Justification starts with `PRODUCTION APPLY on $PROJECT (terraform/<stack>)`.
- It names a `$DEVOPS_REPO` Actions run that is in progress on
  `Await PAM approval`.
- `CHANGE:` matches that run's head commit subject.
- `BY:` is a GitHub actor, not a random email.
- Role binding is `roles/admin` on that project.
- `approvals_needed` matches the entitlement: 2 for production stacks.
  S01 `s01-observability` and T0 `t0-exporters` need 1 of 4, so one
  vote runs the apply. Approvers on every entitlement are jakub, josh,
  juan, kais (at that org's domain); Jakub replaced Alastair. If an
  entitlement still lists alastair (seen on `s01-artifacts`
  `tf-apply-owner`, 2 of 4, on 2026-11-23), its PAM config has not been
  applied yet: report the drift.

**Alpaca ops stacks** (`t0-alpaca-ops` in `T0Trade/t0.devops`,
`s01-alpaca-ops` in `S01-Issuer/s01.devops`, both
`terraform/production-alpaca-ops`): production `tf-apply-owner` stacks.
Each needs 2 of 4 votes from jakub, josh, juan, kais (at that org's
domain). The rules above apply: requester
`tf-apply@$PROJECT.iam.gserviceaccount.com`, `roles/admin`, at most
`14400s`. The usual diff class is the bot gateway (`t0-liqbot`,
`s01-issuancebot`): `*_image` digest pins and `*_config_version` pins.
The apply creates or rolls Cloud Run services that call the live Alpaca
account, so state that in the blast radius.

**S01 tsalt.xyz release** (`s01-tsalt-ui` `app-deploy`, 1 of 4 from
jakub, josh, juan, kais): requester is
`tsalt-ui-releaser@s01-artifacts.iam.gserviceaccount.com`, at most
`3600s`, `roles/run.developer`. Expected when the justification names the
`S01-Issuer/tsalt-ui` `release` run that is in progress and quotes the old
and new `tsalt-ui` image digests. Blast radius: for 1 h the releaser can
deploy the tsalt.xyz Cloud Run service.

**Other S01 entitlements** (on `s01-issuance`, each 2 of 4 from jakub,
josh, juan, kais):

- `prod-ssh`: a human requester (one of those four) gets IAP tunnel,
  OS admin login, and use of the VM service account for at most
  `3600s`. Expected when the justification names a concrete task and the
  user knows about it. Blast radius: root shell on the production
  issuance VM, including its secrets.
- `app-deploy`: requester is
  `issuance-releaser@s01-artifacts.iam.gserviceaccount.com`, at most
  `3600s`, `roles/storage.objectAdmin`. Expected when it names the
  release run it gates.

**T0 liquidity after the Cloud Run cutover** (staging 2026-11-03,
production 2026-11-04): the bot is the Cloud Run service `t0-liquidity`
(`europe-west3`) on Cloud SQL `t0-liquidity-pg`. The `t0-liquidity` VM is
stopped and kept one week as the SQLite rollback baseline.

- An `app-deploy` grant for a liquidity release is expected to give
  `run.developer` plus actAs on `t0-liquidity` (the release gate is
  `cloud-run`), not GCS write on `images.env`.
- A `prod-ssh` grant on `t0-liquidity` now only reaches the stopped VM.
  Treat it as suspicious unless the user expects VM work, such as the
  reviewed rollback or the VM's retirement.
- An apply that sets `bot_enabled: true`, restores
  `GATED_SERVICE_REPLICAS=1`, or starts the VM while `cloud_run_image` is
  set is **suspicious**: the SQLite bot is not fenced by the Postgres
  lease and would trade beside the Cloud Run bot. It is safe only as the
  documented rollback, after `cloud_run_image: ""` deleted the service.

Call out the **diff class** from the commit files, in plain language:

- toml-only (config release, no image move)
- `images.yaml` digest / `version` pin (code that will run)
- `bot_enabled` or `GATED_SERVICE_REPLICAS` (start/stop the bot)
- liquidity `cloud_run_image`, `cloud_run_config_version`, or
  `cloud_run_ops_routes` (the Cloud Run bot: create, roll, or delete it,
  or move the ops API routes)
- alpaca-ops gateway `*_image` digest or `*_config_version` pin (Cloud
  Run services that call the live Alpaca account)
- `secrets_version` (secrets pin)
- IAM / KMS / PAM / workflow files (identity)

An `IMAGE ROLL` block in the justification is a digest swap. Quote new
vs old.

**Suspicious** (recommend skip or deny unless the user already expected
exactly this):

- Requester is not the entitlement's eligible principal: for
  `tf-apply-owner`, a human or any SA other than that project's
  `tf-apply`.
- Duration longer than the entitlement's maximum (4 h for
  `tf-apply-owner`, 1 h for `prod-ssh` and `app-deploy`).
- Entitlement is not one listed above (maker-recovery and other
  break-glass grants are a different class; name them and treat as
  high-risk).
- No Actions URL, URL is not that org's `$DEVOPS_REPO`, or the run is
  not this grant's apply.
- Commit subject / SHA / files do not match `CHANGE:`.
- `bot_enabled: false`, a secrets pin bump, or an instance-replace
  the user did not just ask for.
- Justification empty, generic, or missing `PRODUCTION APPLY`.
- Project is not one of the gated prod stacks above.

Verdict per grant: **expected**, **suspicious**, or **not enough
evidence**. Say why in 3-6 bullets. Always state blast radius
(time-bound project `roles/admin` for CI on `tf-apply-owner`).

## 3. Wait for confirmation, then approve

Show the table (project, entitlement, requester, duration, CHANGE,
run URL, verdict). Ask per grant: approve, deny, or skip. Then wait for
the user's answer. Do not approve while you wait.

When the user confirms a grant, approve it yourself with the command
below. Do not hand the vote back to the user.

Do not approve a **suspicious** grant unless the user explicitly
confirms they still want that one, after seeing the bullets.

On approve:

```bash
gcloud pam grants approve "$GRANT_ID" \
  --account="$ACCOUNT" \
  --entitlement="$ENTITLEMENT_ID" \
  --location=global \
  --project="$PROJECT" \
  --reason="$REASON"
```

`$REASON` is short ASCII from the CHANGE line (PAM is picky about
unicode). On deny, same shape with `gcloud pam grants deny`.

Re-describe the grant. If it is still `APPROVAL_AWAITED`, say how many
votes are still needed (prod apply is 2). If it is `ACTIVE` /
`ACTIVATING`, the apply job should proceed; do not revoke.

Timeouts: the apply job waits 60 minutes. Missed window:
`gh run rerun <run-id> --failed` (the grant may still be reusable).

## Hard rules

1. Never use IPv6. Turn it off before any `gcloud` call.
2. Check both accounts first. Run `gcloud-login` for any account
   whose token is missing or expired; never stop at a reauth error.
3. Never approve or deny without an explicit per-grant answer.
   After that answer, cast the vote yourself.
4. Never approve as a service account, or with one org's account on the
   other org's project.
5. Never treat one vote as "the apply ran".
6. Never revoke a grant this skill just approved.
7. Never create a PAM grant from this skill.

## Failure modes

- **gcloud reauth / expired token**: run `gcloud-login` for that
  account, check both accounts again, then continue.
- **search empty with an error hidden**: the search is not valid.
  Check the accounts again before you report "no grants".
- **search empty**: this account is not an approver on that
  entitlement, or nothing is waiting.
- **approve PERMISSION_DENIED**: not in `pam_approval.approvers`.
- **FAILED_PRECONDITION**: grant is not `APPROVAL_AWAITED` (already
  active, denied, or expired).
