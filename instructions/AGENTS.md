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
