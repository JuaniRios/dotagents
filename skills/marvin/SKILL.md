---
name: marvin
description: Juan's map of Marvin, the team's always-on AI box (@rain-marvin in Zulip, GitHub, and Linear). Use when asked to change, fix, debug, extend, operate, or explain Marvin — its NixOS config, the Python bot, the model router, review checks, Linear flow, scheduled tasks, usage alerts, accounts, or the box itself. Also use when a question mentions marvin.taile5cf8a.ts.net, T0Trade/marvin, rain-marvin, marvin-worker, or the rain-marvin/reviewed, coderabbit/reviewed, or human/reviewed checks.
---

# Marvin

Marvin is the team's always-on AI engineer. It answers `@rain-marvin` in
Zulip, GitHub, and Linear by queueing each request and running a headless
agent CLI (Claude Code, Codex, Cursor Agent, Antigravity) for it. It holds no
model and no production credentials.

## Read the repo docs first

The repo is the source of truth. This skill is a map; do not trust it over
the code.

| What | Where |
| --- | --- |
| Repo | `T0Trade/marvin` (private), local clone `~/Github/marvin` |
| Operating and fresh-install runbook | `~/Github/marvin/README.md` |
| Architecture: units, request flow, router, accounts, integrations, security | `~/Github/marvin/docs/ARCHITECTURE.md` |

Before any change, pull the clone (`git -C ~/Github/marvin pull --ff-only`)
and read the part of `docs/ARCHITECTURE.md` that covers the change. Update the
README and `docs/ARCHITECTURE.md` in the same PR as any change they describe.

## Where it lives

- Host: `marvin.taile5cf8a.ts.net`, a Hetzner dedicated server
  (65.108.107.25; Ryzen 9 7950X3D, 128 GB, 2 × 1.9 TB NVMe in mdadm RAID1).
  NixOS, installed with nixos-anywhere on 2026-09-25. Formerly `reviewer`.
- Access: Tailscale SSH only. `ssh root@marvin.taile5cf8a.ts.net`, or
  `ssh marvin@…` for the user that runs every AI job. OpenSSH is off.
- Public surface: Tailscale Funnel on `:8443`, only `/github` and `/linear`
  (signed webhooks). T3 Code on `:443`, tailnet only.
- Tailnet policy: `rainlanguage/rain.devops`,
  `terraform/tailscale/policy.hujson`, machine tag `tag:rain-marvin`. Device
  tags are a console step, not Terraform.
- If Tailscale is down: Hetzner Robot rescue system.

**Never open a port or re-enable OpenSSH without asking Juan first.**

## Architecture in one screen

```
Zulip ── marvin-zulip (long-poll) ─┐
GitHub ┐                           ├─> jobs.sqlite ─> marvin-worker ─> marvin-run-j<job>-<n>
Linear ┴─ Funnel :8443 ─ marvin-hooks ┘   (queue)     (lanes + router)   (one systemd unit per attempt)
Timers (tasks, follow-ups) ────────┘                                      └─> replies, reviews, checks
gh-token broker (user marvin-app holds the App key) ──> 1-hour, one-repo tokens for the worker
```

- Nix layout: `hosts/marvin/` (disko, hardware, network, users, `rebuild`),
  `modules/marvin/default.nix` (every Marvin service, timer, model, person,
  org, task), `modules/rain-reviewer/` (the App whose credentials `rebuild`
  uses to pull; its review loop is disabled), `home/` (per-user tooling and
  agent CLIs), `bot/` (the Python app).
- Python app: `bot/marvin/`, standard library only, built by Nix into the
  `marvin` command. Tests in `bot/tests/` run in the Nix build.
- Users: `marvin` (AI jobs, no keys), `marvin-app` (only reader of
  `/var/lib/marvin-app/app.pem`), `reviewer` (rain-reviewer App key).
- Skills on the box come from `JuaniRios/dotagents` and `T0Trade/agent-skills`,
  pulled every 15 minutes by `marvin-skills-sync`, not by `rebuild`. A skill
  change reaches Marvin without a deploy.

## Identities and external settings

- GitHub App `rain-marvin`, App ID 5077017, owned by the `rain-marvin` user
  (devops@rainlang.xyz). Commits as `rain-marvin[bot]`.
- Zulip bot `rain-marvin-bot@raingroup.zulipchat.com`.
- Linear OAuth app `rain-marvin`.
- Model accounts are team accounts (leads@rainlang.xyz), never Juan's personal
  ones. Codex has one account, `codex-1`; do not re-add `codex-2`.
- Required checks, all posted by App 5077017 on ST0x repos:
  `rain-marvin/reviewed` (ruleset 24013665), `coderabbit/reviewed` and
  `human/reviewed` (ruleset 23778102). The Graphite App must stay on the
  default-branch bypass list, because its merge queue fast-forwards trunk.
- Off-box backup of secrets, state, and old ruleset JSON:
  `~/Github/.marvin-backup/`.

## Where to change what

| Change | Edit |
| --- | --- |
| Teammates (Zulip, Linear, GitHub ids) | `people` in `modules/marvin/default.nix` |
| GitHub orgs Marvin works in | `orgs` in `modules/marvin/default.nix`, and install the App there |
| Models, aliases, priority | `models` and `priority` in `modules/marvin/default.nix`; CLI command lines in `bot/marvin/router.py` |
| Scheduled agent task | a block under `tasks` in `modules/marvin/default.nix` (schedule, prompt, Zulip target) |
| Lanes and concurrency | `LANES` and `LANE_THREADS` in `bot/marvin/jobqueue.py` |
| Zulip behavior, instant commands | `bot/marvin/zulip.py` |
| Webhook filters, Linear OAuth install | `bot/marvin/hooks.py` |
| Review prompts, severity, verdict, check runs | `bot/marvin/review.py` |
| `coderabbit/reviewed`, `human/reviewed` | `bot/marvin/coderabbit_gate.py`, `bot/marvin/human_gate.py` |
| Linear plan, go, implement flow | `bot/marvin/linear_flow.py`, `bot/marvin/linear.py` |
| Account rotation, parking, Codex resets | `bot/marvin/accounts.py` |
| Follow-ups, team memory | `bot/marvin/followups.py`, `bot/marvin/memory.py` |
| Usage alerts | `modules/marvin/usage-alerts.yml`, `bot/marvin/usage.py` |
| Storage reclaim | `bot/marvin/gc.py` |
| Agent CLIs and tooling for `marvin` | `home/marvin.nix`, `home/agent-clis.nix`, `home/rust.nix` |
| Disks, kernel, network | `hosts/marvin/` (hardware-specific; keep `linuxPackages_latest`, the RAID needs a kernel newer than 6.18) |

## Make a change

This repo uses Graphite like every other T0Trade repository: follow the
`graphite` skill. A ruleset ("no main push", 24190376) blocks direct pushes
to `main`, so every change goes through a PR.

1. `cd ~/Github/marvin && gt sync`, then `gt checkout main`.
2. Edit. Keep the docs in step.
3. For bot changes, run the tests without a pipe, and check the exit code:

   ```sh
   cd ~/Github/marvin/bot && python3 -m unittest discover -s tests > /tmp/marvin-tests.log 2>&1; echo $?
   ```

   Piping through `tail` hid failures twice, and a broken PR got merged. Read
   the log when the exit code is not 0.
4. Stage, `gt create <branch> -m "<message>"`, `gt submit --no-interactive`,
   then `gt merge`. Show Juan the Graphite link
   (`https://app.graphite.com/github/pr/T0Trade/marvin/<number>`).
5. Deploy happens on merge. The `pull_request` webhook makes `marvin-hooks`
   touch `/run/marvin-deploy/trigger`, and the root `marvin-deploy` unit runs
   `rebuild`; a failure pages `#general > marvin / failures`. Watch it:

   ```sh
   ssh root@marvin.taile5cf8a.ts.net journalctl -u marvin-deploy -f
   ```

   A config change restarts the services that read `/etc/marvin/config.json`;
   agent runs live in their own units and survive it. Run `rebuild` by hand
   only for a direct push to `main` (no `push` webhook), a change to the
   deploy mechanism itself, or `--show-trace` on a Nix error. The switch may
   restart tailscaled and drop the SSH session; the switch still finishes.
6. Verify (below), and report what changed on the live box.

Never edit the box by hand, except for secrets and agent logins, which are
outside Git. The README's "Fresh install" section lists each secret file and
where it comes from.

## Inspect and verify

As `marvin`:

```sh
ssh marvin@marvin.taile5cf8a.ts.net 'marvin models; marvin jobs --all | head'
ssh marvin@marvin.taile5cf8a.ts.net 'marvin job <id or text> --log 40'
ssh marvin@marvin.taile5cf8a.ts.net 'marvin accounts'
```

As root:

```sh
ssh root@marvin.taile5cf8a.ts.net 'systemctl --failed; tailscale funnel status'
ssh root@marvin.taile5cf8a.ts.net 'journalctl -u marvin-worker -u marvin-zulip -u marvin-hooks -n 100 --no-pager'
```

- Run transcripts: `~marvin/.local/state/marvin/runs/<job>/<n>.log`.
- State: `~marvin/.local/state/marvin/` (`jobs.sqlite`, `memory.json`,
  `accounts.json`, `zulip-engaged.json`).
- Prometheus and Alertmanager on loopback only:
  `ssh -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 root@marvin.taile5cf8a.ts.net`.
- Alerts post to Zulip `#general > marvin / failures` and
  `#devops general > marvin / usage`.
- End to end: DM rain-marvin in Zulip (the reply names the model), or comment
  `@rain-marvin review` on a PR in a covered org.

## Hard rules

1. Read the code and `docs/ARCHITECTURE.md` before changing anything; the
   repo wins over this skill.
2. Every box change goes through the flake and a merged PR, then `rebuild`.
3. Do not open ports, enable OpenSSH, or widen Funnel without asking Juan.
4. Do not put personal accounts or production credentials on the box.
5. Do not change GitHub rulesets or bypass lists without asking Juan, and back
   up the current JSON to `~/Github/.marvin-backup/` first.
6. Confirm the merge-triggered deploy finished (`marvin-deploy`) before reporting a change as live.
7. If this skill disagrees with the repo, fix this skill.
