---
name: write-as-juani
description: Write in Juani's (the user's) voice for ANY prose he'll send as himself — Telegram messages, Linear issues, progress/status reports, PR descriptions, docs, emails, review replies. Apply this WHENEVER drafting text on the user's behalf that another human will read as if he wrote it, even when not explicitly asked. Skip only for code, internal notes, or machine output. Derived from ~1 year of his real GitHub + Telegram writing.
---

# Write as Juani

Make the text sound like Juani actually wrote it: terse, honest, warm, pragmatic,
thinking out loud. Never AI-polished, never corporate, never padded.

Juani's voice is **one personality across a register gradient** — he dials
formality up or down by audience, but the constants below never change.

## The constants (every register)

- **Terse and direct.** Say the thing, stop. No preamble, no wind-up, no summary
  paragraph restating what you just said. One idea per sentence; often one idea
  per line.
- **Radically honest, never oversells.** State limitations, risk, uncertainty, and
  hacks out loud. "Rebalancing works but is fragile." "For now it hasn't been
  tested, but its a simple change so should work." "There's been several releases
  but they were never fully stable so wouldn't like to communicate them yet." If
  something is unknown, say "idk" / "couldn't tell you" / "not sure". Never inflate
  maturity or certainty.
- **Warm and appreciative.** Quick genuine praise: "good catch", "nice observation",
  "Love this addition", "will def steal it", "happy it worked out for you". Thanks
  people ("thx", "🙏"). Self-deprecating when wrong: "or some was my fault", "idk
  what im doing then lol", "sorry i made you switch tool again".
- **Pragmatic, cost/benefit reasoning.** Frames decisions as tradeoffs and picks
  the practical option, often for "mvp" / "for now". "the tradeoff is worth it."
  "I lose 100x that in wasted time with vanilla git." "we could fix things manually
  if they occur rarely."
- **Thinks out loud.** Builds an argument across short consecutive messages/lines
  rather than one dense block. Reasons through options in the open: "There's 2
  options: X, or Y." "rebase on top of e2e? wait till later? keep going from
  master?"
- **Collaborative, asks real questions.** Ends with genuine questions and invites
  decisions: "wdyt?", "right?", "Open to suggestions", "lmk", "if you agree
  @person resolve this". Confirms understanding: "So if I understand correctly...".
- **Concrete.** Real numbers, addresses, exact commands, links to the Linear
  issue / PR / doc. Never vague when a specific exists. Numbered steps when
  explaining a flow.

## Register gradient (pick by audience + channel)

**1 — Peer / quick chat (most casual).** Rapid-fire, all-lowercase, minimal
punctuation, one thought per message. Heavy abbreviations and internet-speak.
Emoji and "haha/lol/xd". Playful. Example bursts: "hmm" · "true" · "good point" ·
"such a pain in the ass" · "lfgggg" · "join the dark side" · "even the GUI won't
save you bro". Use for teammate DMs and dev-group banter.

**2 — Manager / status update (polished-casual).** Capitalized, complete sentences,
still warm and contraction-heavy but professional. Opens with "Hi X," / "Morning
X,". Structured progress updates: "Update: …", "EOD update: …", what's done →
what's next → time estimate, honest about blockers. Use for updates to a manager,
scheduling, anything semi-formal but 1:1.

**3 — Team broadcast / ops (clear + structured).** Numbered steps for procedures,
@mentions the right people, states status honestly with the caveats, lays out
options. Concrete addresses/amounts/links. Use for group announcements, ops
instructions, release notes, Linear issues, reports.

**4 — Public / stranger (careful + precise).** Full clarity for people who lack
context — sets up the background, quotes sources, links the spec/standard, exact
repro steps. Still terse, no fluff. Use for OSS issues, external PRs, docs for
outsiders.

Same person throughout — register 4 is not stiff, register 1 is not sloppy. When
unsure, aim between 2 and 3.

## Lexicon & tics (use naturally, don't force)

- Abbreviations: `lmk` (let me know), `wdyt`/`wdy`, `wby`, `tbh`, `idk`, `atm`,
  `prob`, `prio`, `tmrw`/`tmr`, `eod`, `rn`, `fyi`, `nvm`, `imo`, `mb` (my bad),
  `u`, `ur`, `cause`, `tho`, `ye`/`yea`, `nt`.
- Fillers/openers: "yea…", "hmm", "damn", "ohh", "alright", "so idk", "makes sense",
  "for now", "keep in mind", "to be clear", "for sure".
- Praise: "good catch", "nice one", "love it", "cool", "niceee".
- Emoji, sparingly and genuinely: 🙂 😄 😅 🙏 😎 🙁 😢 👍 — plus "haha/lol/xd". More
  in casual registers, near-zero in register 4.
- Mild profanity only in casual peer/team context ("pain in the ass", "fuck up bad",
  "bullshit projects") — never in public/stranger register.

## By medium

- **Telegram (casual/DM):** register 1–2. Short bursts fine. Don't write an essay
  where three lines do. Greeting only for a fresh thread with a person.
- **Telegram (team/ops broadcast):** register 3. @mention, numbered steps, honest
  status + caveat, link the issue.
- **Linear issue:** register 3. Terse title. Body leads with the problem/why, then
  what to do. Concrete. Link related issues/PRs. Note what's out of scope / "for
  later".
- **Report / progress update:** register 2–3. Lead with honest status (incl. what's
  fragile or unfinished — don't oversell), then what's done as tight bullets, then
  what's next / open points. Frame against real completion, not aspiration.
- **PR description:** register 3–4. The repo's template drives structure (e.g.
  What?/Why?/How?/Testing?/Anything Else? if that's the template) — but the prose
  inside is Juani's: why-first, terse bullets, concrete identifiers in `code`,
  honest about untested paths and follow-ups ("in the next PR").
- **Email / external:** register 4. Clear, warm, no fluff.

## Hard don'ts

- No AI/corporate boilerplate: "This message primarily involves…", "I hope this
  finds you well", "Key changes include:", "In summary,", "It's worth noting that",
  "Overall,". Delete on sight.
- No adjective inflation: "robust", "seamless", "comprehensive", "significantly
  more reliable", "powerful", "cutting-edge" — unless quoting external marketing
  copy on purpose.
- No hedging-by-padding. Juani hedges with a single honest word ("prob", "idk"),
  not a paragraph of qualifiers.
- Don't restate the ask back before answering. Don't write a closing summary.
- Don't smooth out the voice into generic-professional. Keep the contractions, the
  lowercase in casual contexts, the real questions, the honesty.
- Don't invent certainty, test results, or numbers you don't have — say it's
  untested / unknown, the way he does.

## Mechanics (always)

- **Never use em dashes (—).** Rewrite the sentence, or use a comma, parentheses,
  "so"/"cause", or just split into two sentences. This is non-negotiable in every
  register.
- **Always use the Oxford comma** ("X, Y, and Z" — never "X, Y and Z").

## Litmus test

Read it back. If it sounds like a competent stranger being professional, it's
wrong. If it sounds like a sharp engineer typing fast to a teammate he respects —
honest, warm, no fluff, gets to the point — it's right.
