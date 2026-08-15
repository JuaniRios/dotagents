---
name: edit-skill
description: >
  Modify a skill in ~/Github/dotagents/skills. Use when the user asks
  to edit, update, fix, or tweak a skill. `/edit-skill improve`
  diagnoses the last skill that ran in this session.
argument-hint: "improve | <skill> [change description]"
allowed-tools: Bash(*), Read, Write
---

# Edit skill

Edit `~/Github/dotagents/skills/<name>/SKILL.md`. There is one file per
skill. Run `nu ~/Github/dotagents/scripts/install-skills.nu` only if
you added a **new** sibling path that a harness must see (a new
directory). Edits to an existing `SKILL.md` are live through the
existing symlink.

If the request is to create a skill, stop and use `new-skill`.

## Improve mode

`/edit-skill improve` with no other argument: find the last skill that
ran (not this one), diagnose misses, propose a fix, wait for
confirmation, then edit.

## Steps

1. Resolve `~/Github/dotagents/skills/<name>/SKILL.md`. List
   `ls ~/Github/dotagents/skills/*/SKILL.md` if ambiguous.
2. Read it. Confirm name and description.
3. Apply the requested change. Keep structure. Update `description` if
   behavior changed. Do not add Claude-only tool names to the body.
   Multi-lab skills must follow
   `~/Github/dotagents/skills/panel-runtime.md` rather than forking a
   new catalogue.
4. Summarize the change. Iterate until the user is happy.
5. On the remote default branch (`main` in this repository):

```bash
cd ~/Github/dotagents
git checkout main
git status --short
git add skills/<name>/SKILL.md   # explicit paths only
git commit -m "refactor: update /<name> skill"
git push origin main
```

Stage only what you edited. This repo often has unrelated dirty files.

## Hard rules

1. Edit files in `~/Github/dotagents/skills/`, never in a harness dir.
2. Do not delete a skill without explicit confirmation.
3. Personal repo: edit and commit on the remote default branch only (`main`).
4. Show the change before committing.
5. Always push the commit to `origin main` in the same session. A skill edit is
   not complete while it exists only locally. If the push fails, report the
   failure instead of claiming completion.
