---
name: strong-typing-inspector
description: "Use when the user asks to inspect a diff or PR for weak typing: raw primitives where domain types exist, missed newtypes, stringly typed IDs, unit confusion, and type-boundary leaks."
---

# strong-typing-inspector

Codex-native port of the former Claude slash command `strong-typing-inspector`.

Review a diff for places where stronger domain types would prevent bugs. This
is a review workflow, not an implementation workflow unless the user separately
asks for fixes.

## Scope

Review only the supplied diff, PR, or current branch diff. Existing code outside
the diff is context, not a finding target, unless the changed code introduces a
new dependency on the weakly typed behavior.

## Workflow

1. Resolve the diff.
   - If the user supplied a PR number/URL, fetch the PR diff.
   - If the user supplied a patch path, read that file.
   - Otherwise inspect the current branch against its Graphite parent when
     available:
     ```bash
     gt parent
     git --no-pager diff "$(gt parent)"..HEAD
     ```
     Fall back to the repo's default branch merge-base only when Graphite parent
     is unavailable.

2. Discover local domain types before judging.
   - Search for newtypes, enums, value objects, ID wrappers, amount/quantity
     types, unit-specific types, and parsing/validation constructors.
   - Read relevant docs such as `docs/domain.md`, `AGENTS.md`, or local module
     docs when present.

3. Inspect the diff for:
   - raw `String`/`&str` identifiers where an ID type exists,
   - raw integers/decimals for amounts, prices, shares, timestamps, basis
     points, percentages, or chain IDs,
   - booleans that should be an enum,
   - untyped maps/JSON values crossing a boundary without validation,
   - conversion code that unwraps, truncates, rounds, clamps, or drops units,
   - functions that accept several same-typed parameters where ordering mistakes
     are plausible,
   - public APIs leaking SDK primitives instead of domain types.

4. Verify each finding.
   A finding is actionable only if:
   - a stronger local type already exists, or
   - the diff creates repeated primitive usage where a new domain type would
     encode a real invariant, or
   - the primitive crosses an external or persistence boundary without
     validation.

5. Report findings first, ordered by severity.
   Use this format:
   ```text
   Findings
   - [severity] path:line - Title
     Evidence: <what in the diff is weakly typed>
     Risk: <bug class enabled>
     Fix: <specific stronger type or constructor>

   Open questions
   - ...

   No findings
   - Say this explicitly if the diff is clean.
   ```

## Hard Rules

- Do not flag style-only preferences.
- Do not demand newtypes where the value is purely local and has no meaningful
  invariant.
- Do not review unrelated old code.
- Prefer existing domain vocabulary and types over inventing new names.
- If you cannot verify that a stronger type exists or is justified, list it as
  an open question, not a finding.
