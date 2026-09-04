---
name: review-pam-grants
description: >
  Review Privileged Access Manager grants waiting on the user, say whether
  each looks expected or suspicious, and approve or deny only after they
  confirm. Use when asked to check PAM, approve a tf-apply grant, or when
  a gated t0.devops apply is stuck on Await PAM approval.
allowed-tools: Bash(gcloud:*), Bash(gh:*), Read, Grep
---

# /review-pam-grants

Find PAM grants this user can approve, analyse each one, then **ask**
before `gcloud pam grants approve` or `deny`. Never approve on sight.

Approving `tf-apply-owner` gives CI a time-bound `roles/admin` on that
GCP project (not standing owner). Production stacks need **2 of 4**
votes. One CLI approve is one vote.

## 0. Identity

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'
```

Require an `@t0trade.com` account. If gcloud asks to reauth, stop and
tell the user to run `gcloud auth login you@t0trade.com --no-launch-browser --update-adc`.
Do not impersonate a service account.

## 1. Grants waiting for this user

Discover entitlements this account can approve, then list
`APPROVAL_AWAITED` grants on each.

Known gated projects (try these; skip 403 / empty):

`t0-liquidity` `t0-oracle` `t0-pricing` `t0-bebop` `t0-artifacts`
`t0-price-publisher`

```bash
gcloud pam entitlements search \
  --caller-access-type=grant-approver \
  --location=global \
  --project="$PROJECT" \
  --format='value(name)'

gcloud pam grants search \
  --entitlement="$ENTITLEMENT_ID" \
  --location=global \
  --project="$PROJECT" \
  --caller-relationship=can-approve \
  --format=json
```

Keep grants whose `state` is `APPROVAL_AWAITED`. If the filter flag is
rejected, list and filter locally.

If none: say so and stop. Do not create a grant.

For each remaining grant:

```bash
gcloud pam grants describe "$GRANT_NAME" --format=json
gcloud pam entitlements describe "$ENTITLEMENT_ID" \
  --location=global --project="$PROJECT" --format=json
```

Record: project, entitlement id, grant name, state, requester,
requested duration, create time, justification, privileged role,
`approvals_needed`, who already approved.

Never print Secret Manager payloads or secrets toml.

## 2. Analyse

Pull the GitHub Actions URL and commit from the justification when
present. Fetch the run and the commit's files (`gh run view`,
`gh api repos/T0Trade/t0.devops/commits/$SHA`).

**Expected T0 apply** (looks good):

- Entitlement is `tf-apply-owner`.
- Requester is `tf-apply@$PROJECT.iam.gserviceaccount.com` (the only
  eligible principal on that entitlement).
- Requested duration is `14400s` (4 h).
- Justification starts with `PRODUCTION APPLY on $PROJECT (terraform/<stack>)`.
- It names a `T0Trade/t0.devops` Actions run that is in progress on
  `Await PAM approval`.
- `CHANGE:` matches that run's head commit subject.
- `BY:` is a GitHub actor, not a random email.
- Role binding is `roles/admin` on that project.
- `approvals_needed` is 2.

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

- Requester is a human, or any SA other than that project's `tf-apply`.
- Duration longer than 4 h.
- Entitlement is not `tf-apply-owner` (maker-recovery and other
  break-glass grants are a different class; name them and treat as
  high-risk).
- No Actions URL, URL is not `T0Trade/t0.devops`, or the run is not
  this grant's apply.
- Commit subject / SHA / files do not match `CHANGE:`.
- `bot_enabled: false`, a secrets pin bump, or an instance-replace
  the user did not just ask for.
- Justification empty, generic, or missing `PRODUCTION APPLY`.
- Project is not one of the gated prod stacks above.

Verdict per grant: **expected**, **suspicious**, or **not enough
evidence**. Say why in 3-6 bullets. Always state blast radius:
time-bound project `roles/admin` for CI.

## 3. Ask, then maybe approve

Show the table (project, entitlement, requester, duration, CHANGE,
run URL, verdict). Ask per grant: approve, deny, or skip.

Do not approve a **suspicious** grant unless the user explicitly
confirms they still want that one, after seeing the bullets.

On approve:

```bash
gcloud pam grants approve "$GRANT_ID" \
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
2. Never approve as a service account.
3. Never treat one vote as "the apply ran".
4. Never revoke a grant this skill just approved.
5. Never create a PAM grant from this skill.

## Failure modes

- **gcloud reauth / not @t0trade.com**: stop.
- **search empty**: this account is not an approver on that
  entitlement, or nothing is waiting.
- **approve PERMISSION_DENIED**: not in `pam_approval.approvers`.
- **FAILED_PRECONDITION**: grant is not `APPROVAL_AWAITED` (already
  active, denied, or expired).
