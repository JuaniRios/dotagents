---
name: teach
description: "Use when the user asks to be taught a topic, codebase area, workflow, a PR or Graphite stack, or what happened in the session. Builds a lightweight teaching plan (plus a study file for PR stacks), explains incrementally, and checks understanding."
---

# teach

Codex-native port of the former Claude slash command `teach`.

Teach the user a topic or session outcome interactively. The goal is durable
understanding, not a single dump of information.

## Workflow

1. Identify the teaching target.
   - If the user named a topic, use it.
   - If they ask about the current session, summarize from visible context and
     local artifacts.
   - If they named a PR (URL, `#number`, or branch name), the target is the
     **entire Graphite stack** containing that PR, never the single PR. See
     the stack mode section below.
   - If the target is ambiguous, ask one concise question before proceeding.

2. Create a lightweight teaching note under `.tmp/`:
   ```text
   .tmp/teach-<slug>.md
   ```
   Track:
   - topic,
   - assumptions about the user's current understanding,
   - lesson outline,
   - questions asked,
   - answers and observed gaps,
   - final recap.

3. Gather context.
   - For repo topics, read the relevant code and docs directly.
   - For current or external topics, browse the web when freshness or exact
     sources matter, and cite sources in the final answer.
   - Do not rely on memory for facts likely to have changed.

   Stack mode (PR targets):
   - Resolve the full stack with the `gh` CLI: walk each PR's base branch
     downward until trunk (`gh pr view <n> --json baseRefName,headRefName,author,title,body,url`)
     and find children upward (`gh pr list --base <head-branch>`). Use
     `gt log` instead when the stack is checked out locally.
   - Collect each PR's title, body, author, linked issue, and diff. For large
     stacks, summarize per PR rather than holding every full diff at once.
   - Frame by author. If the user authored the stack (usually an agent they
     left running), teach it as "know this code as if you wrote it": the
     design decisions made, alternatives rejected, and anything surprising or
     risky — collect the risky items into a "worth double-checking" list. If
     someone else authored it, frame for review and collaboration readiness.
   - Before quizzing, write a study file at `.tmp/teach-<slug>-guide.md`: a
     plain-language TL;DR, the stack's architecture, per-PR sections ordered
     bottom-up (what, why, depends-on), a glossary, and "questions to hold in
     mind" (priming prompts, never quiz answers). Ask the user to read it and
     wait until they say they are ready.
   - Teach bottom-up: start at the base PR; upper PRs build on types and
     decisions the lower ones introduce.

4. Teach in small chunks.
   - Start with the mental model.
   - Add the minimum concrete detail needed to make the model useful.
   - Use examples from the user's repo or task when possible.
   - Avoid long lectures before checking understanding.

5. Check understanding through normal chat.
   - Ask one short question at a time.
   - Prefer applied questions over trivia.
   - Adapt the next chunk based on the answer.
   - Do not use modal or multiple-choice prompts unless the active mode and
     tooling explicitly support them.

6. Finish with a concise recap.
   Include:
   - the core idea,
   - the common mistake to avoid,
   - one practical next step or exercise,
   - the teaching note path.

## Hard Rules

- Do not pretend uncertainty is knowledge. Say what is known, inferred, or
  unknown.
- Do not ask multiple questions at once unless the user requested a quiz.
- Do not create files outside `.tmp/` for teaching notes.
- Do not browse less when the user explicitly asks for current information;
  verify and cite.
