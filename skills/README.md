# skills/

Agent-neutral skills. One `SKILL.md` per workflow.

Install links into every harness:

```nu
nu ~/Github/dotagents/scripts/install-skills.nu
```

Multi-model panels: read `panel-runtime.md`. Harnesses are
claude/codex/grok/agy; models are opus 5, fable 5, sol 5.6, grok 4.6,
flash 3.7. Do not fork a second catalogue.

New work goes here via the `new-skill` skill. Optional Claude/Grok
frontmatter (`allowed-tools`, `argument-hint`) is fine. Bodies stay
host-neutral. Runtime data belongs in `~/Github/dotagents/data/<name>/`.
