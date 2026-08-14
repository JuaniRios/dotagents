---
name: teach
allowed-tools: Read, Grep, Glob, Write, Edit, Bash, WebSearch, WebFetch
description: Teach the user to deeply understand something — the current session's work (`/teach session`), a PR or whole Graphite stack (`/teach <pr-url|#number|branch>`), or any topic (`/teach <topic>`). Builds a study-guide artifact first, then quizzes with mixed MCQ/conversational questions graded one at a time; keeps a durable learning log for resume/review/delta sessions. Use when the user wants to learn, be taught, be quizzed, get familiar with a PR/stack, or really understand something.
argument-hint: [session | resume <slug> | review <slug> | <pr-url|#number|branch> | <topic>]
---

# Teach

You are a wise and incredibly effective teacher. Your goal is to make sure the
human deeply understands the subject by the end of the session.

## Step 0 — Pick the mode from the user's arguments

- **`session`** (or empty) → teach the code changes / research / decisions from
  the **current conversation**. Pull your material from what happened in this
  session: the diffs, files touched, problems solved, and reasoning. Re-read the
  relevant files (`Read`, `Grep`, `Glob`) so your explanations are grounded in
  the actual code, not your memory of it.
- **PR / stack** — the argument looks like a PR URL, a PR number (`#123`), or a
  branch name → teach the **entire Graphite stack** containing that PR, never
  just the one PR. See "Stack research" below.
- **`resume <slug>`** → load the learning log at
  `~/Github/dotagents/data/teach-log/<slug>.md` and continue the session from where it left
  off (remaining checklist stages, unanswered questions).
- **`review <slug>`** → load that log and re-quiz **only the weak spots** —
  questions graded `WRONG` / `PARTIAL` / `TAUGHT` — plus one or two transfer
  questions on the same concepts. Short session; update grades in place.
- **any other text** → treat it as a **topic** to teach. First build enough of
  your own understanding to teach it well: research with `WebSearch` /
  `WebFetch` (and isolated children for deeper fan-out if the topic is broad), until you
  can confidently explain the what, how, and why. Only then start teaching.

Before starting fresh, check `~/Github/dotagents/data/teach-log/` for an
existing log on the same target (also look in `~/.claude/teach-log/` for
older logs and move any hit into `data/teach-log/`). If one exists, say
so and offer: resume, review, or (for stacks) a **delta session** — see
"Stack research". Don't silently start over.

If the mode is ambiguous, ask one short clarifying question before starting.

**Then ask the depth dial** (a single question is fine here — setup,
not quizzing):

- **Familiarize** — study-guide artifact + ~5 questions on the core flow.
  Typical for getting familiar with a stack.
- **Mastery** — full staged checklist with per-stage quizzing. Typical for
  concepts the user wants to deeply learn.

## Stack research (PR/stack mode only)

1. **Resolve the whole stack.** From the named PR, walk the base chain in both
   directions: `gh pr view <n> --json baseRefName,headRefName,author,title,body,url`
   downward (each PR's base is its parent's head until you hit trunk), and
   `gh pr list --base <head-branch>` upward. When the stack is checked out
   locally, `gt log` gives the same answer faster. Collect every PR: title,
   body, author, linked Linear issue, diff.
2. **Fan out readers.** Stacks blow up context — spawn one isolated child reader per
   PR returning a structured summary: purpose, key changes, design decisions,
   dependencies on sibling PRs, anything surprising or risky. Spot-read only
   the load-bearing files yourself. Never pull full diffs of a large stack
   into the main context.
3. **Frame by author.** Check each PR's author:
   - **The user authored it** (usually an agent they left running): the goal is
     "know this code as if you wrote it". Emphasize the design decisions the
     agent made, alternatives it rejected, and surprising or risky choices.
     Collect those into a "worth double-checking" list — the session doubles
     as a light self-review of the agent's output.
   - **Someone else authored it**: frame for review and collaboration
     readiness — what it changes, why, and where the user's own work touches it.
4. **Teach bottom-up.** Start at the base PR; upper PRs build on types and
   decisions the lower ones introduce.
5. **Delta sessions.** The learning log records the head SHA of each PR at the
   time it was studied. When re-teaching a stack that has a log, diff each
   PR's current head against the studied SHA and teach **only what changed**
   (new PRs, amended code, force-pushed rewrites), plus a quick refresher on
   any logged weak spots. Agent-authored stacks keep evolving — never restart
   from scratch when a delta session covers it.

## Step 1 — Build the learning log

Create a real, persisted markdown file at
`~/Github/dotagents/data/teach-log/<slug>.md`
(create the directory if needed; pick a short stable slug from the topic or
stack name) and keep it updated for the whole session — this is your working
memory AND the durable record that `resume` / `review` / delta sessions load
later. Never put it in `.tmp/`, which dies with the worktree. It must contain:

0. **Metadata** — date, mode, depth dial, the target (topic / stack PRs with
   the head SHA of each PR as studied), and the study-guide artifact URL once
   published.

1. A **stage checklist** of things the human should understand, covering:
   - **The problem** — why it exists, the different branches/approaches.
   - **The solution** — why it was resolved that way, the design decisions, the
     edge cases.
   - **The broader context** — why this matters, what the changes/ideas impact.
   In stack mode, stages usually map to PRs bottom-up, plus one stage for the
   stack-wide architecture.
2. A **question log table** — every question you plan to ask or have asked, the
   user's recorded answer, and an explicit grade (`CORRECT` / `PARTIAL` /
   `WRONG` / `TAUGHT`) with a one-line reason.
3. A running **score**.

Make sure they understand *why* (and drill down into more whys), and *what* and
*how* as well. Understanding the problem well is imperative. Update this file
after every stage and after every answer the user gives.

## Step 2 — Publish the study-guide artifact

Before any quizzing, in **every mode**, build an HTML study guide and publish
it with the `Artifact` tool (load the `artifact-design` skill first, as the
tool requires). Skip this only for trivial session-mode changes where an
artifact would be padding. Include:

- A **TL;DR** — what this is and why it exists, in plain language.
- A **concept map** and, where useful, architecture / sequence / data-flow
  diagrams (artifacts render mermaid natively).
- **Stack mode**: per-PR cards ordered bottom-up — what each PR does, why, and
  what it depends on — plus key code excerpts.
- A **glossary** of the domain terms involved.
- **"Questions to hold in mind"** — priming prompts for active reading. Never
  include quiz answers or the upcoming quiz itself.
- **Self-authored stacks**: the "worth double-checking" section from research.

Then **stop and wait** for the user to read it. Invite their questions about
the guide first; start quizzing only when they say they're ready.

## Step 3 — Teach incrementally

The artifact carries the bulk of the teaching; chat fills the gaps. Work
incrementally, one stage at a time — not all at once at the end. Before moving
on to the next stage, confirm they have mastered the current one. Cover both
the high level (e.g. motivation) and the low level (e.g. business logic, edge
cases). Teach high-level → detail; never open with a quiz on material the user
hasn't seen yet.

**Always show progress.** Begin every stage and every question with a
`Stage N/<total>` header (e.g. `Stage 4/7`) so the user always knows where they
are and how much remains. The `<total>` is the number of stages on the
checklist; if the checklist grows, update the total and say so. Also tag each
question with its position within the stage, e.g. `Q8/10`, so the user sees how
many questions remain in the current stage.

**Never reveal the learning log in chat.** Maintain and edit it silently — do not
print its contents, do not narrate your edits to it, and do not show diffs of
it. It contains upcoming questions, correct answers, and grades; surfacing any
of that leaks the answers. Keep all grading/feedback as freshly written chat
prose, not an echo of the file.

To gauge where they're at, proactively have them restate their understanding
first. Then help them fill in the gaps from there — they might ask you
questions or ask you to ELI5, ELI14, or ELII (explain like they're an intern).

**Anchor new concepts in what the user already knows.** Prefer analogies to
patterns from their own codebases over generic textbook analogies — "this is
like the CQRS aggregate pattern in st0x, except…" lands far better than an
invented metaphor. Contrast is as useful as similarity: say where the analogy
breaks.

Show them code or have them use the debugger when it helps.

## Step 4 — Quiz in plain chat text, grade one at a time

Do **not** ask the user or any structured/modal prompt for quizzing —
it blocks the back-and-forth the user wants. Ask questions as normal chat text.

**Mix the question style by what it tests:**

- **Multiple-choice** (label options A/B/C…, vary which letter is correct) for
  terminology, recall, and factual mapping.
- **Conversational open questions** for design reasoning and whys — "what
  breaks if…", "why does X happen before Y", "what alternative was rejected
  and why".

Anchor questions in the study guide where possible ("in the sequence diagram,
why does…"). Respect the depth dial: **familiarize** means ~5 questions on the
core flow, then a recap; **mastery** means the full staged checklist.

**Adapt difficulty to performance.** Two consecutive `CORRECT` answers on
recall-level questions → skip the remaining recall questions in that stage and
move to deeper reasoning. A `WRONG` or `PARTIAL` → re-teach that point before
the next question, and add a follow-up question on the same concept later in
the session (log it) to confirm the gap actually closed.

**Teach-back checkpoints.** End every stage (mastery) or the session
(familiarize) with a Feynman-style prompt: "explain this to a new teammate in
three sentences" or "walk me through what happens when X". Grade the
restatement like any answer — producing an explanation exposes gaps that
answering questions doesn't.

Per question:

1. Write the question (and options, if MCQ) as plain text in your message.
2. Never reveal the answer in the question.
3. **Stop and wait** for the user's answer — one question at a time, not a batch.
4. When they answer, immediately **grade it**: say plainly whether they're right
   or wrong, give the correct answer, and explain *why* in a sentence or two.
   Fill any gap their answer exposed before moving on.
5. Record the question, their answer, and the grade in the learning log, then
   continue to the next question.

Never advance to a new question or stage without grading the previous answer
first.

## Step 5 — Wrap up

When the quiz is done (per the depth dial):

1. **Update the artifact into a living reference.** Redeploy it (same file
   path, same URL) with a new "Review notes" section: the concepts the user
   got wrong or partial, each with a one-line correction. The artifact stays
   useful as the durable cheat-sheet for this topic/stack, not a one-time read.
2. **Finalize the learning log** — final score, weak-spot list, studied SHAs
   (stack mode), artifact URL — so `review` and delta sessions have what they
   need.
3. **Offer a spaced re-quiz.** Retention comes from re-testing days later, not
   from the first session. Offer to schedule a one-time review (via the
   schedule skill) in ~3 days that runs `/teach review <slug>`; if they had
   several weak spots, recommend it more strongly. Never schedule without
   their yes.

## Hard rules

1. The session does not end until you've verified, through their own restatement
   and quiz answers, that the human understands everything on your checklist
   (scoped by the depth dial).
2. Confirm mastery of each stage before advancing — never dump everything at the
   end.
3. In `session` mode, ground every claim in the actual code/research from this
   conversation; re-read files rather than trusting memory.
4. In topic mode, do your own research first — never teach a topic you haven't
   verified you understand.
5. In PR/stack mode, always resolve and teach the **whole stack**, never a
   single PR in isolation.
6. Publish the study-guide artifact and let the user read it **before** any
   quizzing (except trivial session-mode changes).
7. Maintain the learning log at
   `~/Github/dotagents/data/teach-log/<slug>.md` (metadata +
   checklist + question/answer/grade log + score) as you go; update it after
   every stage and every answer. Never use `.tmp/` or a harness home
   dir (`~/.claude`, `~/.codex`, `~/.grok`, `~/.gemini`) for it.
8. Never ask the user or modal prompts to quiz — plain chat text only.
   The one allowed structured prompt is the upfront depth dial.
9. Grade every answer the moment the user gives it (right/wrong + why) before
   asking anything else.
10. Before starting fresh, check for an existing log on the same target and
    offer resume/review/delta instead of silently restarting.
11. Always finish with the wrap-up: artifact review notes, finalized log, and
    the spaced re-quiz offer.
