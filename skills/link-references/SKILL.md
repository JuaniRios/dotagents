---
name: link-references
description: How to write any reply to Juan that names a Linear issue or project, a pull request, a commit, a branch, a GitHub issue, a release, a CI run, a Zulip thread or message, a Marvin review, a doc, or a file. Use whenever a reply, report, summary, plan, or status update mentions any of these, which is almost every work reply.
---

# Link every reference

Juan clicks through instead of searching. Every reference in a reply
that has a URL gets a link. A bare ID such as `RAI-4172`, `#117`, or
`b70fe2950` is a bug when a link can be built.

## How to link each kind

| Reference | Link |
| --- | --- |
| Linear issue | `[RAI-4172](https://linear.app/makeitrain/issue/RAI-4172)` |
| Linear project or milestone | the project URL from `linear` output |
| Pull request | Graphite link, per the `graphite` skill: `[#117](https://app.graphite.com/github/pr/<owner>/<repo>/117)` |
| Commit | `[b70fe29](https://github.com/<owner>/<repo>/commit/<sha>)` |
| GitHub issue | `https://github.com/<owner>/<repo>/issues/<n>` |
| Release or tag | `https://github.com/<owner>/<repo>/releases/tag/<tag>` |
| CI run | the run URL from `gh run view` |
| Zulip thread or message | the narrow URL, e.g. `https://raingroup.zulipchat.com/#narrow/channel/<id>-<name>/topic/<topic>/with/<msg>` |
| Local file | its absolute path, as `path:line` when a line matters |

## Rules

1. Link the first mention of each reference in a reply. Later mentions
   in the same short reply may stay bare.
2. Put the link on the ID or a short name, not on a whole sentence.
3. Never invent a URL. If the owner, repo, or ID is unknown, look it up
   (`gh`, `linear`, `git remote`). If it can't be found, leave the ID
   bare and don't guess.
4. Tools that need a raw URL, like `gh` and PR-linking tools, still get
   the GitHub URL. This skill covers only what Juan reads.
5. In lists of issues, every item gets its link.
