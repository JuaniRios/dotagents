---
name: create-release
description: "Use when the user asks to cut, create, tag, or publish a new GitHub release for the current repo: draft the notes with the draft-release workflow, agree a semver tag, then create the release after explicit confirmation."
---

# create-release

Create and publish a GitHub release for the repo you are currently in. The
release body is the full `draft-release` document; the version is either the
version the user passed or a number you agree with them first.

This workflow **mutates a public thing** — it creates a git tag on `origin` and
a published GitHub release. Never run `gh release create` without an explicit
go-ahead in the same session, even when the user's request sounds decisive.

Compatibility notes:
- Treat the user's stated version (if any) as the version argument.
- Ask short, direct questions when a decision is needed.
- Do the work locally; use subagents only if the user explicitly asks.

Follow these steps precisely.

## 1. Orient on the repo

```bash
repo_root=$(git rev-parse --show-toplevel)
nwo=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')
git fetch origin master --tags --quiet
head_sha=$(git rev-parse origin/master)
last_tag=$(gh release view --json tagName --jq '.tagName' 2>/dev/null)
```

Print the repo (`$nwo`), the baseline release tag, and the `origin/master` head
SHA. **The release always targets `origin/master`**, never the checked-out
branch or local HEAD — you may be in a worktree or on a feature branch.

If `gh release view` fails, there are no releases yet; carry on and handle it
in step 3.

## 2. Draft the notes

Run the `draft-release` skill's workflow. It writes
`.tmp/release-notes-<last_tag>-to-<head_short_sha>.md` and prints it.

- If the commit range is empty, **stop**: "nothing to release since `<tag>`".
  Do not create an empty release.
- Do not write your own notes. The body always comes from `draft-release`.

Keep the file path — you need it in step 5.

## 3. Decide the version

**If the user gave a version:** normalize it to a leading `v` (`1.2.3` ->
`v1.2.3`). Validate it is semver (`vMAJOR.MINOR.PATCH`, optional `-pre`
suffix). Reject anything else and ask again — never guess a fix.

**If no version was given:** derive a suggestion from the work in the range.
Strip the `v` from `$last_tag`, then bump by the strongest signal present in
the resolved PRs and commit subjects:

| Signal in the range | Bump |
| --- | --- |
| `feat!:`, `BREAKING CHANGE`, an incompatible config/secrets schema change | major |
| any `feat:` | minor |
| only `fix:` / `chore:` / `refactor:` / `docs:` / `ci:` | patch |

Ask the user which of the three concrete tags to use, naming the suggested one
first with your one-line reason ("14 PRs, 3 feats, no breaking changes ->
minor"). They may answer with a different version.

If there are **no releases yet**, do not suggest a bump: ask directly what the
first tag should be, offering `v0.1.0` and `v1.0.0`.

Then check the tag is free:

```bash
git tag --list "$version"
gh release view "$version" --json tagName 2>/dev/null
```

If either returns anything, **stop** and report it. Never move, delete, or
force an existing tag.

Warn (do not block) if `$last_tag` uses a different prefix convention than the
`v` you are about to publish.

## 4. Confirm

Print, in one block:

- repo, new tag, target SHA (short) and its subject
- baseline tag and its publish date
- PR count and commit count from the draft
- the **entire release body** you are about to publish

Then ask the user to confirm publishing, or abort. Only an explicit yes
proceeds. If they want wording changes, edit the `.tmp` notes file, re-print,
and re-confirm.

## 5. Publish

Strip the `# Release notes: ...` H1 line from the drafted file into a body file,
keeping everything else (Summary, Highlights, Pull requests, Technical
changelog):

```bash
body="$repo_root/.tmp/release-body-$version.md"
sed '1{/^# Release notes/d}' "$notes_file" | sed '1{/^$/d}' > "$body"
gh release create "$version" \
  --target "$head_sha" \
  --title "$version" \
  --notes-file "$body" \
  --latest
```

`gh release create` creates the tag at `--target` for you; do not push a tag
by hand first.

## 6. Report

Print the release URL (`gh release view "$version" --json url --jq '.url'`),
the tag, the target SHA, and the PR/commit counts it covers.

Do not announce the release anywhere else (Telegram, Linear, Slack) unless the
user asks — that is a separate step.

## Hard rules

1. **Never run `gh release create` without an explicit confirmation** in this
   session (step 4). Approval for a previous release does not carry over.
2. **The body always comes from the `draft-release` workflow.** Never
   hand-write release notes or use GitHub's `--generate-notes` — it drops
   Graphite-merged PRs.
3. **Always target `origin/master`'s head SHA**, never local HEAD or the
   current branch.
4. **Tags are always `v`-prefixed** and always semver.
5. **Never overwrite, move, or delete an existing tag or release.** If the tag
   exists, stop and report.
6. Never create a release for an empty commit range.
7. Never push commits, merge, or otherwise change `master` as part of this —
   the release is cut from what is already on `origin/master`.

## Failure modes

- **No releases exist yet:** `draft-release` asks for a baseline; you ask for
  the first tag outright (`v0.1.0` / `v1.0.0`), no bump suggestion.
- **Empty range:** report "nothing to release since `<tag>`" and stop.
- **Tag/release already exists:** stop, print the existing release URL, ask for
  a different version.
- **Invalid version:** reject and ask; do not auto-correct beyond adding the
  `v` prefix.
- **`gh` not authenticated or no write access:** report the `gh` error verbatim
  and stop — the notes file is already on disk and can be reused.
- **`gh release create` fails after the tag was created:** report the state
  precisely (tag exists, release does not) and stop; let the user decide
  whether to delete the tag.
