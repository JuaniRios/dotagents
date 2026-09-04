---
name: create-liquidity-release
description: >
  Cut a st0x.liquidity GitHub release, pin those digests on production
  liquidity in t0.devops, dispatch the gated apply, and cast this user's
  PAM vote. Use when the user says create-liquidity-release, ship a
  liquidity release to prod, or roll the production liquidity image.
argument-hint: [version]
allowed-tools: Bash(gh:*), Bash(git:*), Bash(gt:*), Bash(gcloud:*), Read, Grep
disable-model-invocation: true
---

# /create-liquidity-release

Ship a **new production liquidity image**. Staging is not this command
(`ci_rolls: true` there; master CI already writes staging).

This mutates GitHub and GCP. Two explicit go-aheads in this session:
the `create-release` publish confirm, then the pin+dispatch confirm.
A previous release or apply is not consent.

## 0. Repo

Must be `ST0x-Technology/st0x.liquidity` (`gh repo view --json nameWithOwner`).
Anything else: stop.

## 1. GitHub release

Follow the `create-release` skill from step 1 through its report.
Do not duplicate its version, notes, or confirm rules. Empty range or
existing tag: it stops; this command stops too.

Keep `$version` (leading `v`) and `$head_sha` (`origin/master`).

`create-release` already creates the GitHub release. The tag push still
runs `.github/workflows/release-tag.yml`, which **labels** the three
attested images in Artifact Registry. Wait for that workflow on
`$version` to succeed (or, if it fails because the release already
exists, continue only after all three AR tags resolve).

```bash
for image in t0-liquidity t0-liquidity-dashboard t0-liquidity-datasette; do
  gcloud artifacts docker images describe \
    "europe-west3-docker.pkg.dev/t0-artifacts/t0-liquidity/${image}:${version}" \
    --format='value(image_summary.digest)'
done
```

If any describe fails, stop. The pin would lie.

## 2. Pin PR in t0.devops

Prod does not read the GitHub tag. It runs
`terraform/production-liquidity/images.yaml`. Dispatching without this
pin reapplies the old digest.

Read the live `images.yaml` and `st0x-hedge.toml` from
`T0Trade/t0.devops` `main`. Build a PR that:

- Sets `version:` to `$version`.
- Sets `bot_image`, `dashboard_image`, `datasette_image` to the three
  digests from step 1 (`repo@sha256:...`). All three move together
  (one app-repo commit). Leave `exporter_image`, `bot_enabled`, and
  `secrets_version` alone unless the user asked and the new image
  requires a secrets-schema bump.
- **Same PR, config companion:** if the current pin is `v1.10.0` (or
  any image that rejects unknown `[rebalancing]` fields) and the new
  image is after st0x.liquidity #1352, add
  `[rebalancing].inventory_staleness_bound_secs = 300` to
  `st0x-hedge.toml` in this PR. The reverse is also required: never add
  that field without moving the image pin. Other required-by-new /
  rejected-by-old config fields ride this PR the same way.

Show the exact hunks. Ask: pin these digests, merge, and dispatch
`production-liquidity` on that merge, or abort.

On go-ahead, clone/update `~/Github/t0.devops`. Version control: follow
the `graphite` skill. One branch, those files only.

After submit, wait for the PR's `production-liquidity` **plan** (and
`images-version`) to go green. Then merge. Do not dispatch until `main`
contains that merge commit.

## 3. Dispatch — this run only

```bash
main_sha=$(gh api repos/T0Trade/t0.devops/commits/main --jq .sha)
gh workflow run production-liquidity.yml --repo T0Trade/t0.devops --ref main
```

Find the new `workflow_dispatch` run whose `headSha` is `$main_sha`.
Print its URL. That id is the only apply this command owns.

If another `production-liquidity` apply is already `in_progress` on
`Await PAM approval`, **do not approve it**. Say so. This command only
votes the grant for **this** run.

## 4. PAM vote

Identity and grant discovery: follow `review-pam-grants` steps 0–2 on
project `t0-liquidity`, entitlement `tf-apply-owner`.

Approve only if the waiting grant is **this** apply:

- Requester `tf-apply@t0-liquidity.iam.gserviceaccount.com`
- Justification `PRODUCTION APPLY on t0-liquidity (terraform/production-liquidity)`
- Actions URL is the run from step 3
- `CHANGE:` SHA is `$main_sha` (the pin merge), not an older dispatch
- `approvals_needed` is 2
- Duration `14400s`

If it does not match, skip or deny; do not vote. If it matches, approve
with an ASCII reason from the CHANGE line (`gcloud pam grants approve`
as in `review-pam-grants`). This command is the user's go-ahead for
**this** grant only.

## 5. Who else must approve

Prod apply is **2 of 4**. After this vote, re-describe the grant.

Read the live approver list from the entitlement (do not hard-code a
second copy):

```bash
gcloud pam entitlements describe tf-apply-owner \
  --location=global --project=t0-liquidity --format=json
```

Print:

- this account (already voted, or PERMISSION_DENIED)
- who has already approved
- who still can/should vote (entitlement principals minus already-approved)
- votes still needed
- the grant id and the apply run URL

One CLI approve is one vote. Do not say the apply ran.

## 6. After the second vote

The apply job waits 60 minutes. When the run succeeds, wait for the
2-minute `t0-liquidity-roll.timer`, then follow `check-liquidity-bot`
on `prod`.

If the bot is Restarting: the new image rejected the toml (or the toml
rejected the image). Do not restart the unit; pin and toml have to
match in a new apply.

## Hard rules

1. Never `gh release create` except inside `create-release`'s confirm.
2. Never dispatch `production-liquidity` until the pin PR is on `main`.
3. Never approve a PAM grant whose run URL or CHANGE SHA is not the
   dispatch this command just created.
4. Never add `inventory_staleness_bound_secs` without the image pin,
   and never pin a post-#1352 image without that field.
5. Never flip `bot_enabled` or bump `secrets_version` as a side effect.
6. Never print Secret Manager payloads or the secrets toml.
7. Never treat staging as this path.

## Failure modes

- **release-tag / AR describe fail:** tag exists, images unlabelled.
  Stop; do not pin a guessed digest.
- **images-version red:** `version:` does not resolve to the pin.
- **Stale in-flight apply:** do not vote it; dispatch a new run from
  current `main` after the pin merge.
- **This user's PAM vote PERMISSION_DENIED:** still print who can vote.
- **PAM timeout:** `gh run rerun <id> --failed`; the grant may still
  be reusable. Re-check it is still this SHA before voting again.
- **Bot crash-loop after roll:** image/config mismatch. New pin PR,
  do not docker restart.
