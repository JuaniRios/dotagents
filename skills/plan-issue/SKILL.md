---
name: plan-issue
description: >
  Research a complex Linear issue and publish a multi-model implementation
  plan as a Linear document, critiqued by opus 5 + sol 5.6 + grok 4.6. Use
  only when the issue needs substantial research, architectural decisions,
  cross-component coordination, or non-trivial sequencing. Do not use for
  simple, localized, or mechanically obvious changes such as removing one
  config entry. Read-only on the repo.
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

## Complexity gate

Use this skill only when a multi-model plan would materially reduce execution
risk. At least one of these must apply:

- The issue spans multiple components or repositories with meaningful coupling.
- The implementation requires an architectural or domain-model decision.
- Several plausible approaches need research and comparison.
- The work has dependent phases, migration risks, or difficult rollback needs.
- The issue is ambiguous enough that implementation should wait for explicit
  design sign-off.

Do not use this skill for small, localized work with an obvious implementation,
including config entry changes, asset additions or removals, straightforward
dependency bumps, copy edits, narrow renames, or isolated one-file fixes. Handle
those directly with a proportionate inline plan or the trivial fast path in
`implement-issue`.

If the user explicitly invokes `plan-issue` for a trivial issue, explain that a
multi-model plan would add overhead without reducing risk and offer a concise
inline plan instead. Proceed with this skill only if the user then explicitly
insists on the full multi-model plan.

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

Panel-runtime **Plan critics**: planner is fable 5 if the Claude
harness is reachable, else the host model. Critics: opus 5, sol 5.6,
grok 4.6 in parallel. Label `claude-host` vs `portable`. Append
`### Critique` (adopted / rejected).

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
6. Critics per panel-runtime. Never impersonate a dropped model.
