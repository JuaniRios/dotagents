---
name: gcloud-login
description: >
  Restore Google Cloud CLI authentication when gcloud reports expired
  credentials, “Reauthentication failed”, or “cannot prompt during
  non-interactive execution”, and when the user asks to authenticate gcloud
  noninteractively.
allowed-tools: Bash(gcloud:*), Bash(test:*), Bash(chmod:*), Bash(stat:*)
---

# /gcloud-login

Restore `gcloud` authentication from the credential configuration referenced by
`~/Github/dotagents/.env`.

This skill may run automatically after a `gcloud` command fails specifically
because authentication expired. After successful authentication, retry the
original read-only command once. Never retry mutations automatically.

## Required configuration

`~/Github/dotagents/.env` must contain:

```bash
GCLOUD_CREDENTIAL_FILE=/absolute/path/to/google-credential.json
```

It may also contain:

```bash
GCLOUD_ACCOUNT=user-or-service-account@example.com
```

`GCLOUD_CREDENTIAL_FILE` must reference a workload-identity, external-account,
or service-account JSON file accepted by `gcloud auth login --cred-file`.

## Procedure

1. Disable shell tracing with `set +x`.
2. Confirm `~/Github/dotagents/.env` exists. Do not print its contents.
3. Load it in an isolated shell. Treat it as trusted user-owned configuration.
4. Require `GCLOUD_CREDENTIAL_FILE` to be set, absolute, and readable. Never
   print its value or inspect the credential JSON.
5. Run:

   ```bash
   gcloud auth login --cred-file="$GCLOUD_CREDENTIAL_FILE" --quiet
   ```

6. If `GCLOUD_ACCOUNT` is set, activate it:

   ```bash
   gcloud config set account "$GCLOUD_ACCOUNT" --quiet
   ```

7. Verify authentication without printing a token:

   ```bash
   gcloud auth print-access-token >/dev/null
   ```

8. Report the active account from `gcloud auth list`; do not report tokens,
   credential paths, JSON contents, or environment values.
9. If invoked because another read-only operation failed, retry that operation
   exactly once. If it still fails, report the exact non-secret error and stop.

## Failure handling

- Missing `.env`: ask the user to create it.
- Missing or invalid `GCLOUD_CREDENTIAL_FILE`: explain the required variable
  without displaying its current value.
- Browser or authorization-code prompt: stop; the configured credential is not
  actually noninteractive.
- Permission or IAP failure after login: report it separately; authentication
  succeeded but authorization did not.
- Never fall back to automating Google email/password login.
- Never create, copy, print, commit, or modify credential material.

## Hard rules

1. Never enable shell tracing.
2. Never print or inspect `.env`, credential JSON, access tokens, refresh tokens,
   passwords, or authorization codes.
3. Never pass secrets directly on a command line.
4. Never use this skill to bypass 2FA or organization access controls.
5. Authentication recovery does not authorize a previously failed mutation to
   be retried.
