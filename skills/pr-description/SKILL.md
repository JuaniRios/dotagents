---
name: pr-description
allowed-tools: Bash(gt:*), Bash(git:*), Bash(gh:*), Bash(codex:*), Bash(mkdir:*), Bash(cat:*), Bash(test:*), Bash(basename:*), Bash(date:*), Bash(wc:*), Bash(command:*), Bash(printf:*), Bash(sha256sum:*), Bash(shasum:*), Read, Write
description: "Draft and publish a pull-request title and merge brief for the current branch. Use whenever a PR needs its description written or updated — after opening a PR, after `gt submit`, when a PR still has a placeholder title, or when the user says write/update the PR description, PR body, or PR summary. Reads the full parent-aware diff and the CI evidence, writes a short brief for the human who approves the merge (live effect, risk, decisions, proof, rollout) in plain ASD-STE100 English, runs a Codex reviewer over the draft, then pushes to GitHub."
argument-hint: [--stack] (optional — draft descriptions for every branch in the stack)
---

Draft a pull-request title and a **merge brief** for the current branch, run
a Codex reviewer over the draft, then push it to GitHub automatically.

Agents write most of the code, and agents review it line by line. The human
who approves the merge does not read the diff. The brief is for that human.
It holds only what they must judge: what changes in the running system, how
risky it is, which choices were made, what proves it works, what nobody
checked, and how it rolls out. Read the whole diff so the brief is right,
then leave the mechanics out. The diff, the code comments, and the Linear
plan already hold them.

Follow these steps precisely.

## 1. Load the required skills

Invoke **both** the `graphite` skill and the `write-as-me` skill before doing
anything else.

- `graphite` — version-control mechanics for the rest of this command.
- `write-as-me` — the PR body is prose the user ships under his own name, so
  it MUST be in his voice, not yours. Load it now, before you read the diff, so
  the first draft is already in-voice. The merge brief in step 5 fixes the
  *structure*; this is about *voice*. Do not skip it just because the diff is
  small.

You will be using `gt` for all version-control
reads in this command; raw `git` is only acceptable for read-only inspection
(`git diff`, `git log`, `git rev-parse`). Do **not** run `git commit`,
`gt modify`, `gt submit`, or any other mutating command until you have drafted
the description and run the Codex review pass (step 8). After that, push without
asking — the Codex review is the gate, not a human confirmation.

## 2. Orient on the branch

```bash
branch=$(git rev-parse --abbrev-ref HEAD)
parent=$(gt parent 2>/dev/null || git merge-base origin/main HEAD)
repo_root=$(git rev-parse --show-toplevel)
head_sha=$(git rev-parse HEAD)
```

If `gt parent` fails and you had to fall back to `git merge-base`, tell the
user — this usually means the branch isn't graphite-tracked and they may want
to run `gt track` first.

Print the branch, parent, head SHA, and which repo you're in. Stop and ask
the user if any of that looks wrong.

## 3. Read the full diff and the evidence

```bash
git --no-pager diff "$parent"..HEAD
git --no-pager diff --stat "$parent"..HEAD
git --no-pager log --oneline "$parent"..HEAD
gh pr checks 2>/dev/null
```

**Read the entire diff.** Skimming the commit messages is not enough. If the
diff is very large (>2000 lines), read it in chunks, do not truncate.

Then answer the approver's questions, not "what, why, how":

- **Live effect.** What changes in the running system after the merge (users,
  money, services, alerts)? When does it land: on merge, on the next release,
  or after a manual step? Or does nothing live change?
- **Risk triggers.** Does it touch a money path (funds movement, signing,
  pricing, quoting, hedging), keys, IAM, or secrets, production config or
  infrastructure, stored data or schemas, or anything hard to undo?
- **Decisions.** Which choices could a teammate reasonably have made
  differently? What was the alternative?
- **Proof.** What evidence shows it works? Read the CI results, not only the
  test names. For Terraform, open the plan log of every affected stack and read
  its summary (`Plan: X to add, Y to change, Z to destroy`, plus any `must be
  replaced`). For a bug fix, find the test that reproduces the bug.
- **Gaps.** What did nobody verify? What can only be seen after deploy?
- **Rollout.** Which steps come after the merge, what should someone watch,
  and how is it undone? Check that the obvious rollback really undoes the
  change. A revert does not remove state that someone installed by hand, and
  adding back an old key may not disable a new one.
- **Order.** Must another PR, in any repo, merge before or after this one?

## 4. Check for an existing PR description

```bash
gh pr view --json number,title,body,url 2>/dev/null
```

If a PR exists:
- Record its number, URL, current title, and current body.
- **Preserve intentional user edits.** If the existing body contains
  information not derivable from the diff (context about priorities,
  stakeholder asks, deploy notes, screenshots, TODO lists), that content
  must be carried over into the new draft. Do not overwrite user-authored
  content silently.
- If the existing body was obviously auto-generated by a previous run of
  this command, or follows an old What / Why / How template, you may
  regenerate it from scratch.

If no PR exists yet, note it. The final step calls `gt submit`.

**Persist screenshots before regenerating.** Screenshots vanish when the
body is rewritten, so capture them before drafting:

- **Already-hosted images** (`![...](https://...)` or `<img src="https://...">`
  in the existing body — GitHub `user-attachments`, release assets, etc.): the
  URLs are durable. Copy the exact markdown verbatim and re-insert it in step 6;
  never drop it on regen.
- **Local or in-session screenshots the user referenced** (a pasted image, a
  `./shot.png` or `/tmp/...` path): these are NOT hosted yet, so they won't
  survive a rewrite and a local path renders broken on GitHub. `gh` cannot
  upload images into the body's CDN — copy the file to a scratch location
  (`mktemp`) so it persists, then ask the user to drag-drop it onto the PR for a
  durable URL and offer to splice that URL into the body. Never invent a URL.

Screenshots are evidence, so they go in the Proof section.

## 5. Use the merge brief

Use the merge brief below for every repository in `ST0x-Technology` and
`T0Trade`. The org default template at
`ST0x-Technology/.github/pull_request_template.md` holds the same format.
Ignore a leftover What / Why / How template in these orgs.

In a repository owned by any other organization, check for its own template
(`.github/`, the repo root, `docs/`, and `PULL_REQUEST_TEMPLATE/`). If there
is one, follow its sections and apply the writing rules of step 6 inside
them. If there is none, use the merge brief.

```markdown
<Headline: 1 to 3 sentences.> [RAI-123](https://linear.app/<workspace>/issue/RAI-123)

**Live effect:** <...> · **Risk:** <level> (<triggers>) · **Ships:** <...> · **Blocks:** <...>

## Needs your call
- @person <the question>

## Decisions
- <X, not Y, because Z.> [file.ext](<diff link>)

## Risks
- <What can go wrong, how bad, what limits it.>

## Proof
- <The strongest evidence.>
- **Not verified:** <what nobody checked.>

## Rollout
1. <Step, and the signal to check.>
2. Rollback: <how, and any trap.>
```

## 6. Draft the title and the brief

### Title

Draft a concise PR title (under 70 characters). Rules:

- **Always use conventional-commit style: `type: short summary`** (e.g.,
  `feat: add buying power to status scripts`, `fix: erroring rpc client`).
  Pick the `type` that fits the change: `feat`, `fix`, `refactor`, `perf`,
  `docs`, `test`, `chore`, etc. The title MUST start with one of these
  prefixes followed by `: `.
- **Never lead the title with an issue ID.** Titles must NOT start with a
  Linear/Jira/GitHub issue key like `RAI-801:`, `LINEAR-456:`, or `#123:`.
  The issue belongs in the body (linked), not the title. If a discovered or
  existing title leads with an issue ID, strip the ID and rewrite the title in
  conventional-commit form.
- The title should capture the *what* at a glance — the body has the details.
- If the existing PR already has a user-authored title that looks intentional
  AND already complies with the rules above (conventional-commit prefix, no
  leading issue ID), preserve it and note it in the draft display. Otherwise
  rewrite it to comply — do not preserve a non-compliant title just because it
  looks intentional.

### Scope: write for the approver

- Every line must help a human decide to merge, or know what to watch after
  the merge. If a reviewer agent can learn it from the diff, cut it.
- No "How" or "Implementation" section. Mechanics stay in the diff, the code
  comments, and the Linear plan. A mechanic that matters to the approver (a
  latency cost, a new funding requirement, a lock held longer) is a Decision
  or a Risk, so it goes there.
- Describe the change in system terms (behavior, money, services, alerts),
  not in code terms. Use identifiers only as pointers.

### Headline

1 to 3 sentences, with no heading above them. Say what the system does after
the merge, where its output goes, and why now. Link the issue. In a stack,
say which part this is and what the next part adds.

### Slot line

Always present, directly under the headline, in this order:

- `Live effect:` none, or what changes for users, money, services, or alerts.
- `Risk:` low, medium, or high, with the triggers in parentheses. The
  triggers are: money path, keys or IAM, production config or
  infrastructure, stored data, and hard to undo. Name them even for low risk
  (for example "no money path, no keys or IAM, easy to undo"), so the reader
  can check the claim.
  - Low: no trigger hits, or the change is read-only and a revert undoes it.
  - Medium: a trigger hits, and a revert or a config change undoes it.
  - High: a trigger hits, and undo is hard (a migration, an on-chain action,
    moved funds, a key or IAM change).
- `Ships:` on merge, on the next release, or after a manual step.
- `Blocks:` PRs, in any repo, that must merge after this one. Omit this slot
  when there are none.

### Sections

Every section below the slot line is optional. Delete a section that has
nothing real to say. A trivial PR is the headline plus the slot line.

- **Needs your call.** Only when the author needs a human decision. @mention
  the person who must answer. It comes first, above Decisions.
- **Decisions.** At most 3. Only choices a teammate could reasonably dispute.
  Write each as "X, not Y, because Z." End each with a diff link.
- **Risks.** At most 3. What can go wrong, how bad it is, and what limits it
  or which issue follows up. Add a diff link when the risk lives in code.
- **Proof.** The strongest 1 to 3 pieces of evidence: the test that
  reproduces the bug, the staging check, the Terraform plan summary, a
  screenshot. Never a list of every test, a test count, or the lint, fmt,
  and review runs that the checks tab already shows. Always end with a
  `**Not verified:**` bullet that names what nobody checked, human or agent.
  If you checked everything you could, name what the checks cannot cover
  (for example, live traffic).
- **Rollout.** Only when live behavior changes or a manual step is needed.
  Numbered steps, each with the signal to check. The last step is the
  rollback, with any trap named. Carry user-written deploy notes into this
  section.

### Budget

Length follows risk, not diff size. About 150 words for low risk, 250 for
medium, and 400 for high, not counting URLs. At most 3 bullets per section,
each one or two lines.

### Diff links

Link each Decision, and each Risk that lives in code, to its lines in the
PR's Files view:

```bash
path_hash=$(printf '%s' "$path" | sha256sum | cut -d' ' -f1)   # shasum -a 256 on macOS
echo "https://github.com/$owner/$repo/pull/$pr_num/files#diff-${path_hash}R${line}"
```

`$path` is repo-relative and `$line` is the line number in the head version
of the file. Use the file name as the link text. If no PR exists yet, add the
links after `gt submit` opens it (step 9).

### Banned

- Restating the diff, and file-by-file lists.
- The story of the investigation.
- A "How" or "Implementation" section.
- Test counts, and lists of lint, fmt, or review runs.
- The CodeRabbit "Summary by CodeRabbit" block. Drop it when you rewrite a
  body. The user does not want it. If it comes back after the next
  CodeRabbit review, tell the user that "High Level Summary"
  (`reviews.high_level_summary`) is on again for that org in the CodeRabbit
  app, or that the repo has a `.coderabbit.yaml` that turns it on.

### Writing rules

- **Write it in the user's voice, per the `write-as-me` skill loaded in step
  1.** Register 3-4. Terse, why-first, honest about what's untested or fragile,
  concrete identifiers in backticks. **Never use em dashes** — use a comma,
  parentheses, "so"/"cause", or split the sentence. No corporate boilerplate
  ("Key changes include", "In summary", "It's worth noting"), no adjective
  inflation ("comprehensive", "seamless", "robust"). Always use the Oxford comma.
- **Write in ASD-STE100 (Simplified Technical English).** The reviewer may be a
  non-native speaker, so the body must read once and be clear. One idea per
  sentence. Sentences under ~20 words. Active voice with a real subject ("the
  handler retries the burn", not "the burn is retried"). Simple tenses only. One
  word for one thing, reused across the whole body, no synonym variation. No noun
  stack longer than 3 words. Keep the articles and the "that". No Latin ("e.g.",
  "i.e.", "etc." become "for example", "that is", "and so on") and no slash
  conjunctions ("and/or"). Expand an acronym the first time it appears. This
  governs *sentence construction* only, it never overrides the voice, the
  abbreviations, or the honesty from `write-as-me`. If plainness and the voice
  conflict, keep the voice and split the sentence.
- **Accurate, not flowery.** Describe what the code actually does, not what
  you wish it did. If the diff is a refactor, say so in the slot line. Don't
  overstate impact.
- **Link issues** you can discover from branch name, commit messages, or
  existing PR body. GitHub issues/PRs autolink from `#123` (use the repo's
  convention, e.g. `Closes #123`). **Linear issue references MUST be real
  markdown hyperlinks** — never leave a bare `RAI-374` or `LINEAR-456` in
  the body, because Linear IDs do not autolink on GitHub. Use the
  `linear-cli` skill (or `linear issue view <ID>`) to fetch the issue's
  URL, then write it as `[RAI-374](https://linear.app/<workspace>/issue/RAI-374)`.
  If the existing PR body or repo already shows a workspace URL pattern,
  match it. If you cannot resolve the URL, ask the user rather than
  leaving the ID bare.
- **Preserve user-authored content from the existing body** in the section
  it belongs to. Deploy notes go in Rollout, screenshots in Proof, and open
  questions in Needs your call.
- **Don't invent evidence.** Put in Proof only what you verified in the diff
  or the CI results. If there are no tests, say so in Not verified.
- **Remove template HTML comments** (`<!-- ... -->`). They are instructions,
  not content.
- **Do not hard-wrap body text.** Write each paragraph and bullet as one
  continuous line — let it run long. GitHub and the Graphite dashboard wrap
  soft-wrapped text to the viewport; manual newlines mid-sentence render as
  ragged breaks. Only insert newlines where they're semantically real
  (between paragraphs, list items, headings, code blocks). This is the
  opposite of the 80-char wrapping convention used in source/markdown files.

## 7. Stack mode

If the user passed `--stack` (check the user's arguments):

- For each branch in the current stack from `gt log short`, repeat steps
  2–6 with the diff scoped to that branch's parent-vs-HEAD.
- Draft one brief per branch. Each headline says which part of the stack it
  is and what the next part adds.
- Show **all** drafts at once in step 8 so the user can review them in
  order.

## 8. Codex review pass

When called by implement-issue, honor its recorded issue-thoroughness level:
light uses host self-review with no spawned reviewer; standard reuses the
single independent code-and-description pass if it covered this draft and
diff. A standard-path skeleton uses host self-review until that final combined
pass; do not spawn an interim reviewer. Verify wording corrections directly.
Neither path launches
an additional description reviewer. Deep and standalone invocations retain
the review below. This exception also replaces the reviewer gate referenced
in steps 1 and 9; all accuracy and publishing requirements still apply.

Before pushing, get a second opinion from a Codex reviewer on whether the
draft is an accurate, approver-scoped brief of the diff. This replaces the
human confirmation step — the Codex reviewer is the quality gate.

First check Codex is available: `command -v codex`. If it's missing, skip this
step (note it in the output) and proceed straight to push.

Write the draft (title + body) and pipe the diff to Codex:

```bash
cat "$out_dir/diff.patch" | CODEX_HOME="$HOME/.codex" codex exec \
  --sandbox read-only \
  -m gpt-6.1-sol \
  -c model_reasoning_effort="high" \
  -C "$repo_root" \
  "The diff is on stdin. Below is a proposed PR title and merge brief for it.
The brief is for the human who approves the merge, not for someone reading
the code. Agents already review the code line by line.

Title: <draft title>

<draft body>

Review the brief against the diff. Check:
(1) ACCURATE: does it match what the diff does, with no invented evidence?
(2) APPROVER-SCOPED: does every line help a human decide to merge, or know
what to watch after the merge? Flag any line that restates the diff, lists
files, narrates the investigation, lists tests or lint runs, or explains
mechanics (a How section is not allowed).
(3) COMPLETE: is the slot line present (Live effect, Risk with its triggers,
Ships, and Blocks when needed) and is the risk level right? Is a disputable
decision, a risk, a rollout step, or a rollback trap missing? Does Proof end
with an honest 'Not verified' bullet?
(4) BUDGET: is it within about 150 words for low risk, 250 for medium, or
400 for high, with at most 3 bullets per section?
(5) IN VOICE: terse and direct, no em dashes anywhere, no corporate
boilerplate ('Key changes include', 'In summary', 'It's worth noting'), no
adjective inflation ('comprehensive', 'seamless', 'robust')?
(6) PLAIN: does it follow ASD-STE100 (Simplified Technical English)? One
idea per sentence, sentences under ~20 words, active voice with a real
subject, simple tenses, one word per concept reused throughout, no noun stack
over 3 words, no Latin abbreviations ('e.g.', 'i.e.', 'etc.'), no 'and/or'.
Flag any sentence a non-native speaker would have to read twice.

If the draft is good as-is, reply with exactly 'LGTM'. Otherwise reply with a
short bulleted list of concrete fixes (what to cut, what to add, what to
correct). Be terse — no preamble." \
  > "$out_dir/codex-review.log" 2>&1
```

Extract Codex's reply after the bare `codex` marker line (same as `/review-pr`):

```bash
marker=$(grep -n '^codex$' "$out_dir/codex-review.log" | tail -1 | cut -d: -f1)
test -n "$marker" && tail -n +$((marker + 1)) "$out_dir/codex-review.log" | sed '/^tokens used$/,$d'
```

The reviewer is sol 6.1 on the ccx account (`CODEX_HOME=~/.codex`), the same
as the review panels in `skills/panel-runtime.md`. If the output says "hit
your usage limit", rerun the same command once with the ccxx account
(`CODEX_HOME="$HOME/.codex-2"`). If both accounts are out of credits, or
the call still fails, skip the review and proceed to push.

**Apply Codex's feedback automatically** when it's reasonable — incorporate the
suggested cuts/additions/corrections into the draft. You do not need user
approval to apply them. If Codex says `LGTM`, keep the draft as-is. Briefly note
in the output what Codex flagged and what you changed (or that it was clean).

`$out_dir` is a scratch dir you create up front, e.g.
`out_dir=$(mktemp -d -t pr-desc.XXXXXX)`. Write the parent-aware diff from step 3
to `$out_dir/diff.patch` so it's available here.

## 9. Show the final draft and push automatically

Print the final draft (post-Codex) inside a labeled code block, for the user's
records — do **not** wait for confirmation:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PR description — <branch>
(existing PR: #<n> — updating)   [or: no PR yet — creating]
Codex: <LGTM | applied: <one-line summary of changes> | skipped: <reason>>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Title: <final title>

<full final body>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Then push immediately using the mechanics below.

- **If a PR already exists:**

  ```bash
  body_file=$(mktemp -t pr-body.XXXXXX.md)
  cat > "$body_file" <<'EOF'
  <final description here>
  EOF
  gh pr edit <pr-number> --title "<final title>" --body-file "$body_file"
  rm "$body_file"
  ```

- **If no PR exists yet:**

  Use `gt submit` (never `gh pr create`) so graphite stays consistent:

  ```bash
  body_file=$(mktemp -t pr-body.XXXXXX.md)
  cat > "$body_file" <<'EOF'
  <final description here>
  EOF
  gt submit --no-interactive --no-edit-description
  # gt submit does not accept --body-file directly; after it opens the PR,
  # add the diff links (step 6) now that the PR number exists, then use
  # gh pr edit to set the title and full description
  pr_num=$(gh pr view --json number --jq .number)
  gh pr edit "$pr_num" --title "<final title>" --body-file "$body_file"
  rm "$body_file"
  ```

  If `gt submit` fails (uncommitted changes, auth, etc.), stop and report
  the exact error — do not try to work around it.

- **In stack mode:**

  Update each PR in dependency order (trunk-ward first). Use `gh pr edit` per
  PR. Do not re-run `gt submit` once per branch — one `gt submit --stack`
  handles everything.

## 10. Confirm

After pushing, print the PR URL(s). Use the Graphite app link, not the GitHub
one:

```bash
gt pr
```

If `gt pr` is unavailable, take the number from `gh pr view --json number` and
print `https://app.graphite.com/github/pr/<owner>/<repo>/<number>`. Never print
the GitHub URL for a work repository.

And a one-line confirmation per PR updated.

## Hard rules

1. Push automatically after the Codex review pass — do **not** ask the user
   for confirmation. The Codex reviewer is the quality gate, not the human.
2. Write for the approver, not the code reader. No How section, no restated
   diff, no file lists, no test counts. If an agent can learn it from the
   diff, cut it.
3. Always include the slot line (Live effect, Risk with its triggers, Ships,
   and Blocks when needed) and a `Not verified` bullet in Proof.
4. Stay within the word budget for the risk tier: about 150 words for low,
   250 for medium, and 400 for high. Delete empty sections.
5. Always use `--body-file` with `gh pr edit` — never pass multi-line
   markdown as a `--body` string.
6. Always diff against `gt parent`, never against trunk on a stacked branch.
7. Preserve user-authored content from the existing PR body.
8. Never fabricate tests, screenshots, plan output, or deploy notes that
   aren't real.
9. Use `gt submit` to open new PRs, in every work repository.
10. Never leave a bare Linear ID (`RAI-374`, `LINEAR-456`, etc.) in a PR
    body — always render it as a markdown hyperlink to the Linear issue.
11. Never hard-wrap PR body text — write each paragraph/bullet as one long
    line and let the UI soft-wrap it. Newlines only between semantic blocks.
12. Preserve screenshots across regeneration — re-insert already-hosted image
    markdown verbatim, and never replace a real screenshot with a local path or
    an invented URL.
13. Always draft the body in the user's voice via the `write-as-me` skill,
    loaded in step 1. Never ship a PR description containing an em dash.
14. Always write the body in ASD-STE100 (Simplified Technical English): one idea
    per sentence, short sentences, active voice, simple tenses, one word per
    concept, no Latin abbreviations. Plainness shapes the sentences, the voice
    still owns the tone.
