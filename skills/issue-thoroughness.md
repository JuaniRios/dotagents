# Issue thoroughness

Shared policy for `plan-issue` and `implement-issue`. Read before choosing
planners, implementers, or reviewers. Record the level and one-line reason
in the plan and handoff. Reuse that decision across both skills.

| Level | Fits | Planning | Implementation review |
|---|---|---|---|
| Light | Mechanical, low-risk config or documentation edits with a direct check | Host writes and self-checks a short plan; no children or critique loop | Host implements and self-reviews; direct checks; CodeRabbit with a 2-round cap |
| Standard | Localized, well-understood behavior change with limited coupling | Host drafts; one independent host-model child reviews once | Host implements; one independent host-model child reviews the diff and PR description once; CodeRabbit with a 3-round cap |
| Deep | Broad, coupled, uncertain, or sensitive changes | Researched plan, planner per panel-runtime, then critique-loop | Isolated implementation work, review-loop, then finish-pr-review |

## Choose by risk, not file extension or line count

- Light examples: a wording fix, removing a proven-unused config key, or
  updating a non-sensitive setting within an established validated pattern.
- Standard examples: a narrow parser bug, a small UI behavior fix, or adding
  validation to an existing non-sensitive field. Usually one component and a
  few focused tests; no architectural decision or difficult rollout.
- Deep examples: cross-service contracts, concurrency or recovery changes,
  data migrations, permissions, signing, financial execution, and changes
  with hard rollback. A one-line trading-limit or authorization change can
  be deep. A large generated diff alone is not evidence of complexity.

Changing a comment in a sensitive module does not itself make the work deep.
Assess the changed behavior and blast radius. Config-only defaults to light
only when its semantics are understood and low risk; announce exceptions.

Respect an explicit thoroughness request. An explicit request for a full
local review overrides the lighter local-review default. CodeRabbit runs at
every implementation level; an explicit budget or request to continue until
converged overrides the default round cap. If the user
requests a lighter pass on sensitive work, explain the concrete risk and
agree on the reduced scope instead of silently skipping safety checks.

## Standard means one broad pass, not a small multi-model panel

Use one independent host-model reviewer per phase, not council-eval,
critique-loop, review-loop, or the multi-model panel. This single-reviewer
path does not claim panel quorum or multi-model convergence.

Give the reviewer the issue, relevant source, artifact, and acceptance tests.
Ask for correctness, scope, missed cases, and verification gaps. Apply valid
findings and check each fix with focused tests or direct evidence. Do not
restart broad review for ordinary fixes or wording edits. If independence is
needed to verify a fix, ask the same reviewer only about that fix.

A failed reviewer gets one retry; a missing response is not a clean pass.
Report incomplete coverage and request direction if no independent pass can
be obtained. Do not substitute a full panel merely to overcome a tool error.

## Escalation and completion

Reassess when investigation or the actual diff reveals hidden coupling,
sensitive behavior, uncertain contracts, or a material design choice.
Escalate before the risky work and explain why. An ordinary review finding
does not automatically escalate a standard task; a design-level finding does.

## CodeRabbit at every implementation level

Always invoke finish-pr-review on the implementation's in-scope PRs, including
config-only work. It handles existing feedback first, ensures a completed
full-review baseline, and uses incremental reviews thereafter. Reuse valid
current-head coverage instead of posting redundant requests. Planning alone
does not create a PR or trigger CodeRabbit.

- Light: at most 2 completed review rounds per PR for the run.
- Standard (medium): at most 3 completed review rounds per PR for the run.
- Deep: no fixed round cap; continue while making substantive progress.

Pass the level and cap explicitly. finish-pr-review owns round accounting,
fixes, replies, resolution, and final checks. A cap is a cost boundary, not
permission to leave substantive findings hidden or declare unreviewed fixes
converged. Report capped work as incomplete and ask whether to extend the
budget. This does not require adding a local model-review loop.

Required CI and repository checks still apply at every level. Use ci before
Rust or Nix pushes as required; depth controls review overhead, not whether
broken code may be shipped. Report skipped optional local reviews honestly. Do not
claim CodeRabbit convergence when no covered review occurred.

No level authorizes merging, deployment, or unrequested scope expansion.
