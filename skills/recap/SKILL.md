---
name: recap
description: >
  Give Juan a short TL;DR of the current session: what was done, what is
  left, and what questions are open. Use when the user says recap, tldr,
  lost context, catch me up, where are we, or what's left.
---

# /recap

Write the recap in the chat, for Juan, not for another agent (that is the
`handoff` skill). Build it from this session only: tool results, commits,
PRs, and messages. Do not invent progress, and do not re-run work to fill gaps.

Three sections, in this order, each a short bullet list:

1. **What I did**: the outcomes, not the steps. Name each commit, PR,
   file, and id, linked as the `link-references` skill says.
2. **What's left**: numbered, in the order to do it. Mark which items need
   Juan and which need someone else.
3. **My questions**: numbered, each answerable in a few words. Include every
   question still unanswered from earlier in the session.

Rules:
- Keep it readable in about 30 seconds. Drop dead ends unless they changed
  a conclusion.
- Correct earlier claims that turned out wrong, and say so.
- State live facts with their time (for example "503 at 12:40"), and
  don't present them as current unless they were checked again.
- Background work still running: say it is running. Never guess its result.
- If the user's arguments name a focus, recap only that.
