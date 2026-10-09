---
name: review-pam-grants
description: >
  Review Privileged Access Manager grants waiting on the user, say whether
  each looks expected or suspicious, and approve or deny only after they
  confirm. Covers both orgs: T0 (`@t0trade.com`) and S01 (`@s01issuer.com`).
  Use when asked to check PAM, approve a tf-apply, prod-ssh, or app-deploy
  grant, or when a gated t0.devops or s01.devops apply is stuck on Await PAM
  approval.
allowed-tools: Bash(gcloud:*), Bash(gh:*), Read, Grep
---

# /review-pam-grants

Find PAM grants this user can approve, analyse each one, then **ask**
before `gcloud pam grants approve` or `deny`. Never approve on sight.

Approving `tf-apply-owner` gives CI a time-bound `roles/admin` on that
GCP project (not standing owner). Production stacks need **2 of 4**
votes. One CLI approve is one vote.

## 0. Identity

The user has one Google account per org. Each org's projects accept only
that org's account:

| Org | Account | Projects |
| --- | ------- | -------- |
| T0  | `@t0trade.com` | `t0-*` |
| S01 | `@s01issuer.com` | `s01-*` |

```bash
gcloud auth list --format='value(account)'
```

Do not switch the active account. Pass `--account="$ACCOUNT"` on every
`gcloud` command, with the account for that project's org. Check each org
on its own: an expired login in one org must not stop the review of the
other. If gcloud asks to reauth for an org, skip that org, report it, and
tell the user to run
`gcloud auth login <account> --no-launch-browser --update-adc` (or use
`gcloud-login`). Do not impersonate a service account.

## 1. Grants waiting for this user

Discover entitlements this account can approve, then list
`APPROVAL_AWAITED` grants on each.

Known gated projects (try these; skip 403 / empty):

- T0: `t0-liquidity` `t0-oracle` `t0-pricing` `t0-bebop` `t0-artifacts`
  `t0-price-publisher`
- S01: `s01-issuance` `s01-artifacts` `s01-observability`

```bash
gcloud pam entitlements search \
  --account="$ACCOUNT" \
  --caller-access-type=grant-approver \
  --location=global \
  --project="$PROJECT" \
  --format='value(name)'

gcloud pam grants search \
  --account="$ACCOUNT" \
  --entitlement="$ENTITLEMENT_ID" \
  --location=global \
  --project="$PROJECT" \
  --caller-relationship=can-approve \
  --format=json
```

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

## 2. Analyse

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
  S01 `s01-artifacts` and `s01-observability` need 1 (approvers juan,
  kais).

**Other S01 entitlements** (on `s01-issuance`, each 2 of 4 from alastair,
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

Call out the **diff class** from the commit files, in plain language:

- toml-only (config release, no image move)
- `images.yaml` digest / `version` pin (code that will run)
- `bot_enabled` or `GATED_SERVICE_REPLICAS` (start/stop the bot)
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

## 3. Ask, then maybe approve

Show the table (project, entitlement, requester, duration, CHANGE,
run URL, verdict). Ask per grant: approve, deny, or skip.

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

1. Never approve or deny without an explicit per-grant answer.
2. Never approve as a service account, or with one org's account on the
   other org's project.
3. Never treat one vote as "the apply ran".
4. Never revoke a grant this skill just approved.
5. Never create a PAM grant from this skill.

## Failure modes

- **gcloud reauth for one org**: skip that org, review the other,
  report the login command.
- **search empty**: this account is not an approver on that
  entitlement, or nothing is waiting.
- **approve PERMISSION_DENIED**: not in `pam_approval.approvers`.
- **FAILED_PRECONDITION**: grant is not `APPROVAL_AWAITED` (already
  active, denied, or expired).
