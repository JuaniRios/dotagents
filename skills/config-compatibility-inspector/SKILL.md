---
name: config-compatibility-inspector
description: Lightweight review of config-schema and deployment compatibility. Use only when explicitly requested or when a review workflow selects its config-compatibility lane. Flags config changes that cannot be parsed by the deployed binary, schema changes that reject deployed configs, and unsafe rollout order.
argument-hint: "[pr-number | pr-url]"
allowed-tools: Bash(gh:*), Bash(git:*), Bash(rg:*), Bash(grep:*), Bash(wc:*), Bash(test:*), Read, Grep, Glob
---

# Config compatibility inspector

Review only the compatibility boundary between configuration, binaries, and
rollout order. This is a focused, lightweight check. Other reviewers own
general correctness, code quality, and product behavior.

## Trigger surfaces

Run when the diff changes any of:

- Deployed configuration.
- Config structs, deserializers, defaults, validation, or schema versions.
- Deployment or release workflows.
- Checks that validate config against a branch or released image.

Skip when the diff cannot change config syntax, required fields, validation,
or deployed values.

## 1. Get the diff

If the user supplied a PR reference, use it with `gh pr diff`. Otherwise the
calling review workflow supplies a diff path in its appended instructions.

Read the changed files and the relevant repository instructions. Find the
actual deployed config paths, parser entrypoints, release workflow, and
validation checks. Do not assume their names.

## 2. Build the compatibility matrix

Verify both directions:

1. The currently deployed or released binary accepts the candidate deployed
   config.
2. The candidate binary accepts every config that can remain deployed during
   rollout.

Also verify the exact binary and config pair used by the release gate. A unit
test that parses only a current fixture does not prove either deployment
direction.

Treat these failure modes separately:

- A strict old parser rejects a new unknown key.
- A strict new parser rejects an old config that lacks a required key.

## 3. Verify rollout order

For a new required field, the safe default sequence is:

1. Add tolerant parser support while production config stays unchanged.
2. Release and deploy the compatible binary.
3. Add the production config field.
4. After production contains it, make the field required.

An existing field-value change can use a config-only rollout if the deployed
binary accepts it.

A coordinated code-and-config release is an explicit exception. It must
validate the exact pair and prevent either half from deploying alone. Flag any
period where the repository's production config cannot start with the live
binary or the candidate binary.

## 4. Findings

Flag:

- A new config key that the deployed binary rejects.
- A new required field that rejects the current deployed config.
- A config-only rollout that needs unreleased parser support.
- A binary rollout whose bundled config targets the old schema.
- Validation that checks only one compatibility direction.
- A coordinated rollout that can accidentally deploy either half alone.
- Rollout notes that claim compatibility without evidence.

Do not flag ordinary value changes when both relevant validators accept them.
Do not require a production config change in the initial parser-support PR.

## Evidence

Inspect repository instructions, config tests, release workflows, PR checks,
and versioned image selection. Prefer executed validators against the actual
candidate config. If deployed-version evidence is unavailable, say so and
limit the finding to the missing proof.

## Severity

- **critical**: rollout can crash-loop production or apply a config to an
  incompatible binary.
- **high**: the PR cannot complete its stated rollout without unsafe ordering
  or a bypass.
- **medium**: required compatibility evidence or rollback sequencing is
  missing.
- **low**: documentation is ambiguous but execution remains safe.

## Output

For each finding, provide:

```text
<file>:<line> [severity]
Incompatible pair: <binary/schema> + <config>
Failure phase: <merge, config-only rollout, binary rollout, or rollback>
Evidence: <validator, workflow, test, or missing proof>
Safe sequence: <smallest ordered fix>
```

If there is nothing to flag, output exactly:

```text
CONFIG COMPATIBILITY INSPECTION — <PR ref or branch>
Both compatibility directions and the rollout order are satisfied.
```

## Hard rules

1. Stay in the config-compatibility lane.
2. Review the transition, not only the final state.
3. Treat unknown new fields and missing required fields as separate directions.
4. Never recommend bypassing a validator or required check.
5. Do not invent the deployed version, config source, or release order.
