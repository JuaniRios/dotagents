---
name: plan-issue
description: Research a Linear issue and produce a Fable-drafted, adversarially critiqued (Codex + Opus) implementation plan, attached to the issue as a readable Linear document with a plain-language sign-off section and a detailed implementer guide. Use whenever the user asks to plan an issue or ticket, write or draft an implementation plan for a Linear issue, or prepare an issue for /implement-issue.
allowed-tools: Bash(linear:*), Bash(git:*), Bash(gt:*), Bash(gh:*), Bash(codex:*), Bash(grep:*), Bash(cat:*), Bash(ls:*), Bash(find:*), Bash(wc:*), Read, Write, Skill, Agent, AskUserQuestion, TodoWrite
argument-hint: <issue-link-or-number>
---

# Plan issue

Turn a rough Linear issue into a reviewed implementation plan, published as a
Linear **document** attached to the issue (readable inline in Linear). The
plan has two parts: a plain-language section the human signs off on, and a
detailed guide the implementer agent follows. `/implement-issue` and
`/implement-issue-stack` detect this document and use it instead of planning
themselves.

**The drafting model is always Fable — no exceptions.** If the session runs
on Fable, draft in the main session; otherwise delegate the
research-and-draft to a `model: fable` subagent and only critique-orchestrate
and publish from the main session.

**Critics never share the drafter's model family.** Here the drafter is
Fable, so the critics are one Codex CLI pass plus one Opus subagent (step 5).
If a port of this skill ever drafts on Codex, the critique pass runs on
Fable/Claude instead.

**Read-only with respect to the repo**: never edit code or mutate git state.
The only side effect is the Linear document.

`$ARGUMENTS` is the Linear issue link or number (e.g. `RAI-1520`). If empty,
ask for it.

## 1. Read the issue

Invoke the `linear-cli` skill. Resolve the ID and read it:

```bash
linear issue view <ISSUE-ID>
```

Capture title, problem statement, scope, acceptance criteria, parent issue,
and any referenced PRs. Then check whether a plan document already exists
(the CLI's `--issue` list filter is broken against the current schema; use
GraphQL):

```bash
linear api '{ issue(id: "<ISSUE-ID>") { documents { nodes { id title url } } } }'
```

If a document titled `<ISSUE-ID> Implementation Plan` exists, ask the user
whether to rewrite it (`linear document update` with the new content) or
stop. Never create a duplicate.

## 2. Situate against the current state

Before designing anything, establish what already exists:

- Current graphite stack: `gt log` — is this issue a follow-up to an open
  branch/PR in the stack? Which branch should the work stack on?
- Referenced PRs and parent issues: read them (`gh pr view`, `linear issue
  view`); read ADRs, SPEC sections, and docs the issue points at.
- Sanity-check the issue's aims against reality. If a scope line is already
  done, is a no-op, or contradicts the code, that is a finding for the plan's
  sign-off section — not something to silently plan around.

## 3. Research

Delegate broad code mapping to `Explore` subagents (call chains, integration
points, existing infrastructure to reuse); do targeted reads in the main
session. The plan must be grounded in the actual code: every claim about
what exists or is missing must come from the repo, never from the issue text
alone. Verify practical details a naive plan would trip on: config shape and
where it is deployed, test infrastructure gaps (e.g. mocks that do not exist
yet), crate/API boundaries, repo conventions (`CLAUDE.md`/`AGENTS.md`,
`docs/`).

## 4. Draft the plan document

Write the draft to a scratchpad file. Structure:

```
# <ISSUE-ID> Implementation Plan: <title>

One or two lines: what this stacks on / relates to.

## Part 1: Overview for review and sign-off
### What we do and why
### How it works
### Decisions that need your sign-off   (numbered, each self-contained)
### What you get at the end

## Part 2: Implementer guide
### Context: what already exists
### Architecture decisions              (each with rationale)
### <concrete sections as needed: config, change sites, worker design...>
### Test strategy                       (incl. e2e/infra gotchas found in 3)
### Acceptance criteria mapping
### Workflow                            (branch stacking, TDD, verification)
### Critique                            (appended in step 5)
```

Part 1 rules (this is what the human reads and approves):

- ASD-STE100 style: short sentences, active voice, simple words.
- No code identifiers: no interface, function, type, or file names. Describe
  behavior, not implementation ("the bot puts a small task in its internal
  work queue", not "enqueue `RecordX` via apalis").
- Every open decision, discovered scope conflict, deviation from the issue
  text, and deploy-time prerequisite goes in "Decisions that need your
  sign-off" — that list is the whole point of Part 1.

Part 2 rules (this is what the implementer agent follows):

- Concrete: name files, symbols, and change sites. Reference sites by
  symbol, with line numbers only as hints ("re-locate by symbol").
- State each architecture decision with its rationale so the implementer can
  deviate intelligently when reality differs.
- Include repo-specific gotchas found during research; do not make the
  implementer rediscover them.

Whole-document rules: no em dashes (use colons, semicolons, hyphens); do not
restate what repo docs already say — link/point instead.

## 5. Adversarial critique (Codex + Opus, in parallel)

Before publishing, get two **independent critiques of the draft in
parallel** (mirrors `/implement-issue` step 5):

- An **Opus subagent** (`Agent`, `model: opus`, xhigh effort): adversarial
  critique — simpler designs, conflicts with `SPEC.md`/repo conventions,
  missing test coverage, hidden coupling, steps that will not survive
  contact with the code, and whether Part 1's sign-off list actually
  contains every decision buried in Part 2.
- A **Codex pass** (`Bash`): pipe the draft to
  `codex exec --sandbox read-only -m gpt-5.5 -C "$repo_root" "<critique
  prompt: same focus, plus 'what would a staff engineer push back on?'>"`.

If the `Agent` tool is unavailable, run only the Codex critique and flag the
missing Opus pass in the report.

Incorporate the feedback, then append a `### Critique` section at the end of
Part 2 noting which points were adopted and which rejected (one-line
rationale each). This section is published with the document — it shows the
human reviewer what was already challenged.

## 6. Publish to Linear

```bash
linear document create -t "<ISSUE-ID> Implementation Plan" --issue <ISSUE-ID> -f <scratchpad-path>
```

- The title must be exactly `<ISSUE-ID> Implementation Plan` — it is the
  detection contract for `/implement-issue` and `/implement-issue-stack`.
- Do not pass `--icon` (rejected by the current API).
- On rewrite (step 1), use `linear document update <doc-id>` instead.

## 7. Report

- Verdict: does the issue make sense against the current state? Any aims
  that are stale or no-ops.
- The document URL.
- The sign-off decisions, restated briefly so the user can approve from the
  chat without opening Linear.
- Critique highlights: the strongest points raised and whether they were
  adopted.

## Hard rules

1. Never edit code or mutate git/graphite state. The Linear document is the
   only side effect.
2. Document title is exactly `<ISSUE-ID> Implementation Plan` (detection
   contract).
3. Part 1 contains no code identifiers and follows ASD-STE100. No em dashes
   anywhere in the document.
4. Ground every claim in the repo; verify the issue's assumptions against
   the code and surface conflicts in the sign-off section.
5. Never duplicate an existing plan document — update it.
6. The drafting model is always Fable (main session or `model: fable`
   subagent). Critics never share the drafter's model family: exactly one
   Codex CLI pass + one Opus subagent (`model: opus`, xhigh effort).
7. Never publish an uncritiqued plan — step 5 runs before step 6, and the
   published document carries the `### Critique` section.

## Failure modes

- `linear document list --issue` fails with an `IssueFilter` schema error:
  expected; use the GraphQL query from step 1.
- `--icon` on `document create` is rejected: create without it.
- Issue not found: stop and tell the user.
