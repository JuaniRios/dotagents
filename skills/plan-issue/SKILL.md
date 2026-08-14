---
name: plan-issue
description: >
  Research a Linear issue and publish a Fable-drafted (or host-drafted)
  implementation plan as a Linear document, critiqued by Opus + Sol +
  Grok. Use when the user asks to plan an issue or prepare it for
  implement-issue. Read-only on the repo.
argument-hint: "<issue-link-or-number>"
allowed-tools: Bash(*), Read, Write
---

# plan-issue

Turn a Linear issue into a reviewed implementation plan attached as a
Linear document titled `<ID> Implementation Plan` (the detection
contract for `implement-issue`). Read
`~/Github/dotagents/skills/panel-runtime.md` for planner/critics.

Never edit code or mutate git. The Linear document is the only side
effect.

## 1. Read the issue

`linear issue view <ID>`. If `<ID> Implementation Plan` already
exists, ask whether to rewrite or stop.

## 2. Situate

`gt log`, referenced PRs, parent issues, ADRs. Flag stale or already-done
aims in the sign-off section.

## 3. Research

Explore children for call chains and reuse. Every claim about what
exists must come from the repo.

## 4. Draft

Scratch file. Part 1 (human sign-off): ASD-STE100, no code identifiers,
numbered decisions. Part 2 (implementer): files, symbols, tests,
workflow. No em dashes. Do not restate repo docs — point at them.

## 5. Critique

Panel-runtime **Plan critics**: planner is Fable if Claude is
reachable, else host. Critics: Opus + Sol + Grok in parallel. Label
`claude-host` vs `portable`. Append `### Critique` (adopted / rejected).

## 6. Publish

```bash
linear document create -t "<ID> Implementation Plan" --issue <ID> -f <path>
```

No `--icon`. Rewrite uses `linear document update`.

## 7. Report

Verdict against current state, document URL, sign-off decisions,
critique highlights.

## Hard rules

1. No code or git mutation.
2. Title is exactly `<ID> Implementation Plan`.
3. Part 1 has no code identifiers. No em dashes anywhere.
4. Ground every claim in the repo.
5. Never publish an uncritiqued plan.
6. Critics per panel-runtime. Never impersonate a dropped lab.
