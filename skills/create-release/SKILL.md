---
name: create-release
description: Cut and publish a new GitHub release for the current repo. Drafts the body with the draft-release skill, picks the next version (or takes one as an argument), then creates the tag and release after you confirm.
allowed-tools: Bash(gh:*), Bash(git:*), Bash(test:*), Bash(mkdir:*), Bash(sed:*), Bash(grep:*), Bash(sort:*), Read, Write
argument-hint: [version]
disable-model-invocation: true
---

Create and publish a GitHub release for the repo you are currently in. The
release body is the full `draft-release` document; the version is either the
argument or a number you confirm interactively.

This command **mutates a public thing** — it creates a git tag on `origin` and
a published GitHub release. It never runs `gh release create` without an
explicit go-ahead in the same session.

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

Invoke the `draft-release` skill (Skill tool, `skill: draft-release`). It writes
`.tmp/release-notes-<last_tag>-to-<head_short_sha>.md` and prints it.

- If it reports an empty commit range, **stop**: "nothing to release since
  `<tag>`". Do not create an empty release.
- Do not write your own notes. The body always comes from `draft-release`.

Keep the file path — you need it in step 5.

## 3. Decide the version

**If a version argument was passed:** normalize it to a leading `v`
(`1.2.3` -> `v1.2.3`). Validate it is semver (`vMAJOR.MINOR.PATCH`, optional
`-pre` suffix). Reject anything else and ask again — never guess a fix.

**If no argument was passed:** derive a suggestion from the work in the range.
Strip the `v` from `$last_tag`, then bump by the strongest signal present in
the resolved PRs and commit subjects:

| Signal in the range | Bump |
| --- | --- |
| `feat!:`, `BREAKING CHANGE`, an incompatible config/secrets schema change | major |
| any `feat:` | minor |
| only `fix:` / `chore:` / `refactor:` / `docs:` / `ci:` | patch |

Then ask the user with the three concrete tags as options — the
suggested bump first, labelled `(Recommended)` — plus your one-line reason
("14 PRs, 3 feats, no breaking changes -> minor"). The user can always type
their own via Other.

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

## 4. Build the body, then confirm

Build the body file **before** you print anything. The drafted notes open with a
`# Release notes: <last_tag> -> <head>` H1 that must never reach GitHub — the
release already carries `$version` as its title, so publishing the H1 puts a
second, differently-worded heading above it. Strip it, keep everything else
(Summary, Highlights, Pull requests, Technical changelog):

```bash
body="$repo_root/.tmp/release-body-$version.md"
sed '1{/^# Release notes/d}' "$notes_file" | sed '1{/^$/d}' > "$body"
```

Then print, in one block:

- repo, new tag, target SHA (short) and its subject
- baseline tag and its publish date
- PR count and commit count from the draft
- the **entire contents of `$body`** — the exact bytes you are about to publish,
  H1 already gone. Never print the raw notes file here; showing a line that
  never publishes invites the user to spend a decision on it.

Then ask: publish this release, or abort. Only "publish" proceeds.
If the user wants edits to the wording, edit the `.tmp` notes file, rebuild
`$body`, re-print, and re-confirm.

If the user comments on the stripped H1 anyway (they may have seen it in
`draft-release`'s own printout in step 2), tell them plainly that the line does
not publish and carry on. Do not offer to keep it, and do not add a question
about it.

## 5. Publish

Publish `$body` as built in step 4 — do not rebuild it, and do not re-add the
H1:

```bash
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
2. **The body always comes from the `draft-release` skill.** Never hand-write
   release notes or use GitHub's `--generate-notes` — it drops Graphite-merged
   PRs.
3. **Always target `origin/master`'s head SHA**, never local HEAD or the
   current branch.
4. **The `# Release notes: ...` H1 is always stripped from the body.** It is not
   a choice, so never offer to keep it and never ask about it. GitHub renders
   `$version` as the title already.
5. **Tags are always `v`-prefixed** and always semver.
6. **Never overwrite, move, or delete an existing tag or release.** If the tag
   exists, stop and report.
7. Never create a release for an empty commit range.
8. Never push commits, merge, or otherwise change `master` as part of this —
   the release is cut from what is already on `origin/master`.

## Failure modes

- **No releases exist yet:** `draft-release` asks for a baseline; you ask for
  the first tag outright (`v0.1.0` / `v1.0.0`), no bump suggestion.
- **Empty range:** report "nothing to release since `<tag>`" and stop.
- **Tag/release already exists:** stop, print the existing release URL, ask for
  a different version.
- **Invalid version argument:** reject and ask; do not auto-correct beyond
  adding the `v` prefix.
- **`gh` not authenticated or no write access:** report the `gh` error verbatim
  and stop — the notes file is already on disk and can be reused.
- **`gh release create` fails after the tag was created:** report the state
  precisely (tag exists, release does not) and stop; let the user decide
  whether to delete the tag.
