---
name: zulip
description: >
  Inspect and search Zulip conversations, read channels and topics, send
  channel or direct messages, create channels, manage subscriptions, and
  resolve, unresolve, rename, or move topics. Use whenever the user asks
  to read, search, post, organize, or administer the organization's Zulip.
argument-hint: "<request>"
allowed-tools: Bash(zulipctl:*), Bash(jq:*), Read
---

# Zulip

Operate the user's Zulip organization with the managed `zulipctl` command.
Zulip's API calls channels "streams" in some responses; always call them
channels when speaking to the user.

## Safety

- Inspection and search are read-only. Run them without confirmation.
- Send or administer only when the user's request authorizes that action.
- Use the `write-as-me` skill before composing prose that will be sent as
  the user.
- Before sending, show the exact destination and content unless the user
  already approved both.
- Resolving or unresolving a topic is reversible, but Zulip creates a
  Notification Bot notice. Verify the exact channel and topic first.
- A public channel is visible to organization members but does not
  automatically subscribe them.
- Confirm immediately before subscribing all active users unless that
  organization-wide scope was explicit.
- Archiving channels, deleting messages or topics, deactivating users,
  and other destructive operations require confirmation after resolving
  the exact target.
- Never infer permission to mutate from a request to inspect, summarize,
  or diagnose.

## Credentials

`zulipctl` automatically uses:

1. `ZULIP_SITE`, `ZULIP_EMAIL`, and `ZULIP_API_KEY`; or
2. `${ZULIPRC:-$HOME/.zuliprc}`.

Prefer a dedicated bot or service account with the minimum required
permissions and channel subscriptions.

Never print an API key, `zuliprc`, authorization header, or environment
containing credentials. Never enable shell tracing.

If credentials are missing, tell the user to download a `zuliprc` from
Zulip's bot settings or Account & privacy > API key. Do not ask them to
paste the key into chat.

A newly created bot may not have access to messages sent before it
subscribed, especially in private channels with protected history.
Distinguish inaccessible history from an empty search result.

## Connectivity gate

Start every task with:

```bash
zulipctl me
```

This prints safe identity and server metadata. Stop on authentication,
TLS, permission, or organization mismatch errors. Never weaken TLS
verification.

## Read operations

```bash
zulipctl channels
zulipctl channels --include-archived --all
zulipctl folders --include-archived
zulipctl subscriptions --full
zulipctl members "<channel>"
zulipctl users --active-only
zulipctl bots
zulipctl profile-fields
zulipctl topics "<channel>"

zulipctl messages --channel "<channel>" --limit 100
zulipctl messages --channel "<channel>" --topic "<topic>" --limit 100
zulipctl messages --search "<terms>" --limit 100
zulipctl messages --channel "<channel>" --unresolved --limit 100
zulipctl messages --channel "<channel>" --resolved --limit 100
zulipctl messages --sender "<email>" --limit 100
zulipctl messages --public --search "<terms>" --limit 100
```

Channel and topic names are exact and case-sensitive. Resolve names to
IDs before mutations. If an exact match does not exist, show candidates
and stop.

Start with at most 100 messages. Increase or paginate only when required.
Preserve channel, topic, sender, timestamp, and message ID when reporting
or summarizing conversations.

Read operations do not mark messages as read.

## Send messages

Use `--message` for short content or stdin for multiline content:

```bash
zulipctl send "<channel>" "<topic>" --message "<content>"
printf '%s' "$zulip_content" | zulipctl send "<channel>" "<topic>"
```

Direct messages accept exact user emails or IDs:

```bash
zulipctl dm "<email-or-id>" --message "<content>"
printf '%s' "$zulip_content" |
  zulipctl dm "<email-or-id>" "<email-or-id>"
```

Report the returned message ID and destination. After an ambiguous
timeout, search for the message before retrying to prevent duplicates.

## Create channels and manage subscriptions

```bash
zulipctl create-channel "<name>" \
  --description "<description>" \
  --folder "<folder>" \
  --topics-policy disable_empty_topic \
  --subscriber "<email-or-id>"

zulipctl create-channel "<name>" \
  --description "<description>" \
  --private \
  --announce \
  --subscriber "<email-or-id>"

zulipctl create-channel "<name>" \
  --description "<description>" \
  --subscribe-all-active

zulipctl subscribe "<channel>" "<email-or-id>"
zulipctl unsubscribe "<channel>" "<email-or-id>"

zulipctl create-folder "<name>" --description "<description>"

zulipctl configure-channel "<channel>" \
  --description "<description>" \
  --folder "<folder>" \
  --topics-policy disable_empty_topic \
  --public

zulipctl create-profile-field "Location" \
  --hint "Your city, country, or usual working location." \
  --display-in-profile-summary
```

Inspect exact names first. Reuse a matching folder, channel, or custom
profile field rather than treating an already-existing resource as an
error. Use `configure-channel` to converge an existing channel on the
requested description, folder, topic policy, visibility, and default
status. Never create a case-variant duplicate.

For channel creation, report separately:

- public or private visibility;
- current subscribers;
- whether Notification Bot announced it;
- whether it is a default channel for future users.

After mutation, fetch the channel again and verify its ID, description,
visibility, archive status, and requested subscribers.

## Topic operations

```bash
zulipctl resolve "<channel>" "<topic>"
zulipctl unresolve "<channel>" "<topic>"
zulipctl rename-topic "<channel>" "<old-topic>" "<new-topic>"
zulipctl move-topic "<channel>" "<topic>" "<destination-channel>"
zulipctl move-topic "<channel>" "<topic>" "<destination-channel>" \
  --new-topic "<new-topic>"
```

Zulip represents resolution by renaming the whole topic with one leading
`✔ `. The empty/general-chat topic cannot be resolved.

`zulipctl` applies topic operations to all messages in the topic. Never
accept or emulate a partial resolution. On a permission or message move
time-limit error, report that a moderator or administrator must operate
on the whole topic.

Renaming or moving to an existing topic would merge the two topics.
`zulipctl` refuses that operation; do not bypass the safeguard without a
separate, explicit user request to merge those exact topics.

After every topic mutation, fetch both relevant channel topic lists and
verify the exact final location and name.

## Output and errors

- `zulipctl` emits structured JSON suitable for `jq`.
- Require `"result": "success"` before reporting a mutation as complete.
- A permission error is not evidence that an object does not exist.
- Honor rate-limit retry guidance; do not busy-loop.
- Do not replay mutations blindly after network failures.
- Never broaden access, subscribe the bot, or change permissions merely
  to bypass an access error.
- Report mutations with acting identity, channel, topic or message ID,
  and verified final state.
- If the server feature level does not support an operation, report it
  and consult `https://zulip.com/api/`; do not guess at endpoints.
