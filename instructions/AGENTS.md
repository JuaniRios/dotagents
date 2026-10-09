# Global agent instructions

Load the `graphite` skill at the start of every session and follow it for all
version-control and pull-request work, including which pull-request links to
show me. Claude Code expands the import below. Every other tool, Codex
included, must open that file itself before any version-control work.

@~/Github/agent-skills/skills/graphite/SKILL.md

## Zulip identities

The `zulip` skill comes from T0Trade/agent-skills. On machines that have both
`~/.zuliprc-personal` (Juan) and `~/.zuliprc-bot` (Juan-Bot):

- Read as Juan. Use `~/.zuliprc-personal` for every inspection, search,
  scrape, and summary, because it sees every channel and Juan's DMs. Also use
  it for organization-admin work and for messages Juan explicitly asks to send
  as himself.
- Use Juan-Bot only to send messages to Juan, such as work-update reports and
  gcloud-login prompts. Never read with it.
- Pass `--config` on every `zulipctl` command. Do not rely on `~/.zuliprc`.
- Use the `write-as-me` skill for any prose sent as Juan.
- Add Juan-Bot (`juan-bot@raingroup.zulipchat.com`) to the initial subscribers
  of every new private channel unless Juan excludes bots: after creation, Zulip
  may only allow a current content-access member to invite it. Report it apart
  from the human subscribers.

## Pull requests are not done until finish-pr passes

When you open a PR or push changes to one, run the `finish-pr` skill on it
before you report the work as done. This applies to every request, not only
`implement-issue`. Pushing a branch, opening a PR, or seeing local tests pass
does not finish the work.

A PR is done only when `finish-pr` marked it ready for review: Rain Marvin
(and CodeRabbit in `ST0x-Technology`) approved the exact published head, CI
is green on that head, and every review thread has a reply and is resolved.
If CI fails or a bot does not approve, keep fixing and looping. If a real
blocker stops you, report the PR as blocked with the failing check or the
missing approval. Never call it done, finished, or wrapped up.

Skip this only when the user explicitly asks for a draft or a push without
review.
