---
name: reclaim-disk
allowed-tools: Bash(find:*), Bash(du:*), Bash(df:*), Bash(lsblk:*), Bash(swapon:*), Bash(stat:*), Bash(rm:*), Bash(ls:*), Bash(test:*), Bash(awk:*), Bash(sort:*), Bash(dirname:*), Bash(basename:*), Bash(printf:*), Bash(echo:*), Bash(wc:*), Bash(cat:*), Bash(head:*), Bash(git:*), Bash(bun:*), Bash(python3:*), Bash(nix:*), Bash(nix-store:*), Bash(nix-env:*), Bash(pgrep:*), Bash(journalctl:*), Bash(docker:*)
description: Map where all disk space on the machine is used, system wide, then suggest what to delete and remove only the categories the user approves. Deletable categories cover every validated Rust target/ dir (in repos, T3 or other tool worktrees, and temp dirs), settled T3 Code worktrees, stale temp-dir leftovers, Foundry/Anvil temporary data, Nix store garbage, compiler and Nix user caches, node_modules, gitignored temp bloat, and other dev build artifacts. Space that is not safe for this skill to delete (swapfiles, Nix generations, container images, logs, tool data, unallocated disk) is explained with a suggested command or config change. On macOS the scan skips TCC-protected folders so no file-access prompt appears. Nothing is deleted without explicit approval via selector prompts. Use /reclaim-disk, /reclaim-disk --dry-run, or /reclaim-disk <extra-root>.
argument-hint: [--dry-run] [--min-ignored <MB>] [--min-map <GB>] [extra-root ...]
disable-model-invocation: true
---

# Reclaim disk — map all usage, suggest cleanups, delete with per-category approval

First show **where every gigabyte on the disk is**, system wide. Then suggest
what to delete, and delete it **only after the user approves each category** in
a selector prompt. The report must account for the whole used space of each
real filesystem, so "why can't you free more?" always has an answer on screen.

Deletable categories: every validated Rust `target/` (in repos, in T3 or other
tool worktrees such as `~/.codex*/worktrees`, and in temp dirs), settled T3
Code worktrees (regardless of whether Codex, Claude, Grok, or another provider
ran them), stale temp-dir leftovers, Foundry RPC and Anvil state caches, dead
Nix store paths, `sccache`, Nix user caches, `node_modules`, and stray
gitignored temp folders (`.tmp`, `.cache`, logs, Claude/editor leftovers).

Suggest-only items (never deleted by this skill): swapfiles, Nix system and
profile generations, container images, system logs, tool session data, large
unrecognized directories, and disk space not allocated to any partition.

## Scope: read system wide, delete narrowly

Reading and deleting have different scopes.

**Reading (Step 0b map and the candidate scans):**

- **Linux:** read the whole machine. Measure `/` and every other real
  filesystem with `du -x` so each one is counted once and pseudo filesystems
  (`/proc`, `/sys`, `/dev`, `/run`) are skipped. Without root, some system
  directories are unreadable; report them as "unreadable without root" rather
  than guessing.
- **macOS:** TCC prompts the terminal the moment a command touches `~/Desktop`,
  `~/Documents`, `~/Downloads`, iCloud Drive (`~/Library/Mobile Documents`), or
  protected app data. Read system wide **except** these paths, which must never
  be passed to `find`, `du`, `ls`, or `rm`: `~/Desktop`, `~/Documents`,
  `~/Downloads`, `~/Library/Mobile Documents`, `~/Library/Mail`,
  `~/Library/Messages`, `~/Library/Safari`, `~/Library/Containers`,
  `~/Library/Group Containers`, `~/Library/Application Support/AddressBook`,
  `~/Library/Application Support/CallHistoryDB`, `~/Pictures`, `~/Movies`,
  `~/Music`, and `/Volumes`. Measure `$HOME` and `~/Library` child by child so
  these are never entered. Report the bytes you could not measure as
  "protected / not scanned" (used space minus what was measured).
- Never use `sudo`, `mdfind`, or Spotlight.
- Always redirect scan stderr to `/dev/null` so a permission error never
  derails the run.

**Deleting:** only paths that pass `safe_rm` against `ALLOW_ROOTS`, plus the
two Nix/Git exceptions in the Hard rules. The dev roots are:

- `~/Github`
- `~/.foundry`
- `~/.svm`
- `~/.cargo`
- `~/.cache`
- `~/Library/Developer/Xcode/DerivedData`
- `~/Library/Caches`
- any extra root passed in the user's arguments (must be an existing absolute
  path under `$HOME`)

Candidates found elsewhere by the system-wide scan extend `ALLOW_ROOTS` only
by the exact rule each step gives: a validated Rust target's parent directory
(Step 1), an exact T3 worktree root (Step 0a), or the system temp directory for
temp leftovers (Step 6c). Never append `$HOME`, `/`, a tool's whole data dir
(`~/.codex*`, `~/.claude`, `~/.grok`, `~/.t3`), or `/nix`.

## Step 0 — Parse arguments and define guards

Parse the user's arguments:
- `--dry-run` present → build and print the full report, then **stop** (no
  prompts, no deletion).
- `--min-ignored <MB>` → size threshold for the "Other ignored / temp bloat"
  scan (Step 6b) and the temp-leftover scan (Step 6c). Default `50`.
- `--min-map <GB>` → smallest directory the disk map (Step 0b) drills into
  and prints. Default `1`.
- Any other token that is an existing absolute path under `$HOME` → add it to
  the scan roots **and** the deletion allowlist.

Define these helpers in the working shell and reuse them for every deletion.
The `safe_rm` guard is the last line of defense — every `rm -rf` goes through it.

```bash
HOME_REAL="$HOME"
MIN_IGNORED_MB=50   # overridden by --min-ignored
MIN_MAP_GB=1        # overridden by --min-map
ALLOW_ROOTS=(
  "$HOME_REAL/Github"
  "$HOME_REAL/.foundry"
  "$HOME_REAL/.svm"
  "$HOME_REAL/.cargo"
  "$HOME_REAL/.cache"
  "$HOME_REAL/Library/Developer/Xcode/DerivedData"
  "$HOME_REAL/Library/Caches"
)
# (append validated extra roots from the user's arguments here)

T3_BASES=("$HOME_REAL/.t3")
# If T3CODE_HOME is set, append it only when it is an existing absolute path
# under HOME_REAL. A `--base-dir` explicitly named by the user may be appended
# under the same rule. Each base's database is `$base/userdata/state.sqlite`.

# kilobytes of a path (0 if missing)
dsize() { du -sk "$1" 2>/dev/null | awk '{print $1}'; }

# human-readable from KB
human() { awk -v k="$1" 'BEGIN{ split("KB MB GB TB",u); i=1; while(k>=1024 && i<4){k/=1024;i++} printf "%.1f %s", k, u[i] }'; }

# the ONLY way anything gets deleted
safe_rm() {
  local t="$1"
  case "$t" in /*) ;; *) echo "REFUSE (not absolute): $t"; return 1;; esac
  case "$t" in *..*) echo "REFUSE (contains ..): $t"; return 1;; esac
  [ -e "$t" ] || { echo "skip (already gone): $t"; return 0; }
  local ok=0 r
  for r in "${ALLOW_ROOTS[@]}"; do
    case "$t" in "$r"/*) ok=1; break;; esac
  done
  [ "$ok" = 1 ] || { echo "REFUSE (outside allowlist): $t"; return 1; }
  for r in "${ALLOW_ROOTS[@]}"; do
    [ "$t" = "$r" ] && { echo "REFUSE (is a root): $t"; return 1; }
  done
  [ -d "$t/.git" ] && { echo "REFUSE (git repo root): $t"; return 1; }
  rm -rf -- "$t"
}
```

Do not add all of `~/.t3`, `~/.claude`, `~/.codex`, or `~/.grok` to
`ALLOW_ROOTS`. T3 is the authority for provider-independent thread/worktree
ownership. Only exact worktree paths returned by its database and validated in
Step 0a may be appended to `ALLOW_ROOTS`. This permits `safe_rm` to remove a
validated worktree's build-artifact descendants while its existing root guard
still refuses the worktree path itself. Whole T3 worktrees receive the separate
Git removal treatment in Step 6a.

Keep a running `seen` set of absolute paths already collected, so later scans
(especially Step 6b) never list the same path twice.

If a long scan is easier as a script, write it in the session scratchpad and run
it with Python 3 or `safe-ts` (read-only Deno; it has no file access, so pipe
data to it). Keep deletion in the shell `safe_rm` above.

## Step 0b — Map where all the space is (system wide, read-only)

Do this first, before any candidate scan. Its output is the top section of the
report.

1. **Capacity.** Print `df -h` for every real filesystem (skip `tmpfs`,
   `devtmpfs`, `overlay`, `squashfs`, `efivarfs`). On Linux also print
   `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS`; on macOS print
   `diskutil list`. Compare each disk's size with the sum of its partitions
   and report any unallocated space. If the user expects more capacity than
   the disk shows, say so plainly: the disk itself is smaller, or it was grown
   by the provider and the partition and filesystem were not.
2. **Top level.** For each real filesystem mount `M`, run
   `du -xk -d 1 "$M"` (on macOS measure the children of `/`, `$HOME`, and
   `~/Library` one by one, skipping the TCC list in Scope). Do not descend into
   another mount point.
3. **Drill down.** Recursively re-run `du -xk -d 1` on any directory at least
   `MIN_MAP_GB` in size, down to 5 levels below the mount, so each large
   consumer is named at the level where it can be acted on (for example
   `~/.codex-2/worktrees/<id>/st0x.liquidity/target`, not just `~/.codex-2`).
   Stop descending into `/nix/store` (report it as one line: live store size),
   and into `target/`, `node_modules/`, and `.git/` directories (report each
   as one line).
4. **Account for the rest.** For each filesystem, print used space from `df`,
   the sum measured, and the difference as one of: "unreadable without root",
   "protected / not scanned" (macOS), or "filesystem overhead / open deleted
   files". If the difference is over 5% of used space, flag it.
5. **Special files.** Report swapfiles and swap partitions with
   `swapon --show` (Linux) or `sysctl vm.swapusage` (macOS), including how much
   is in use. Report `journalctl --disk-usage` when it runs without root, and
   `docker system df` when Docker is installed and reachable.

Keep this map read-only. Every row gets one of these tags, used again in the
report:

- **deletable**: the path is a candidate in a category below;
- **suggest**: space the skill cannot safely delete, with the exact command or
  config change the user can apply (Step 6d);
- **keep**: system files, the live Nix store, source code, and user data.

## Step 0a — Discover and validate all T3 worktree roots

Do this before scanning build artifacts. Read each validated
`$T3_BASE/userdata/state.sqlite` with Bun's SQLite client in read-only mode.
If Bun is not installed, use Python 3's `sqlite3` module with a read-only URI
(`file:<db>?mode=ro`). Never use a client that can write.
Verify that the database contains `projection_threads` with `thread_id`,
`title`, `worktree_path`, `deleted_at`, `settled_override`, and `settled_at`,
plus `projection_projects.workspace_root`. If the database or schema is
missing, print `T3 worktree scans: skipped (unsupported/missing state DB)` and
continue with non-T3 categories.

Query every thread with a non-null `worktree_path`, including deleted threads,
and join its project `workspace_root`. Deduplicate by `worktree_path`. A path is
a validated T3 worktree root only when all of these hold:

- `worktree_path` and `workspace_root` are existing, distinct absolute paths
  under `$HOME_REAL` and contain no `..`;
- `git -C "$workspace_root" worktree list --porcelain` lists the exact path;
- `git -C "$worktree_path" rev-parse --show-toplevel` resolves to the exact
  path; and
- `.git` is a file pointing to linked-worktree metadata, never a directory.

For each validated path, record every linked thread's title, deletion status,
and settlement status. Append the exact path to `T3_WORKTREE_ROOTS` and
`ALLOW_ROOTS`; never append its parent or all of `~/.t3`. This early validation
is reusable by Steps 1 and 6a. It makes validated build-artifact descendants
eligible regardless of thread state, but it does **not** make the whole
worktree deletable; Step 6a requires every linked thread to be settled.

## Step 1 — Scan: Rust `target/` directories, anywhere the user can write

Find every `target/` build dir in the user's writable space, pruning so the
search does not descend into `target/`, `node_modules/`, `.git/`, `/nix`, or
the TCC list on macOS. Scan `$HOME`, the validated T3 worktree roots, the
system temp directory (`/tmp` on Linux; `/private/tmp` and `$TMPDIR` on
macOS), and extra roots. On macOS, scan `$HOME` child by child so no TCC path
is entered.

Confirm each is a real Cargo target so we never touch a source folder that
happens to be named `target`:

- inside the dev roots or a validated T3 worktree: `CACHEDIR.TAG`, or a sibling
  `Cargo.toml`;
- anywhere else (tool worktrees such as `~/.codex*/worktrees`, temp checkouts,
  and other home directories): `CACHEDIR.TAG` **and** a sibling `Cargo.toml`,
  and the target is owned by the current user. Skip anything under
  `~/.cargo/registry`, `~/.cargo/git`, and `~/.rustup`.

```bash
for root in "$HOME_REAL" <tmp-dirs> <extra-roots> <validated-T3-worktree-roots>; do
  find "$root" \( -path /nix -o -name node_modules -o -name .git \
         -o -path "$HOME_REAL/.cargo/registry" -o -path "$HOME_REAL/.cargo/git" \
         -o -path "$HOME_REAL/.rustup" \) -prune -o \
       -type d -name target -prune -print 2>/dev/null
done | sort -u   # then apply the validation rules above to each path
```

This covers main repos, ordinary worktrees, exact database-backed T3
worktrees, other tools' worktrees, and temp checkouts. For a validated target
outside every existing `ALLOW_ROOTS` entry, append its **parent directory** to
`ALLOW_ROOTS`, so `safe_rm` can delete the target while its root guard still
refuses the parent. Before deleting it, repeat the validation and check that no
running process has its working directory inside the target (`/proc/*/cwd` on
Linux, `lsof -d cwd` on macOS).

Record each path and its `dsize`. Put **every** validated target in one
**"Rust target/ dirs"** approval category. T3 thread state does not filter,
split, suppress, or protect a `target/`: active, unsettled, settled, and deleted
threads all follow the same target cleanup rule. Removal preserves source and
Git state but forces the next build to recompile.

List every target path and size. For T3 targets, also show the linked thread
title(s) and state for context, not as an eligibility condition. Before
deleting an approved T3 target, repeat Step 0a's database and Git validation,
confirm the candidate remains strictly beneath the exact worktree root, and
repeat the `CACHEDIR.TAG`/sibling-`Cargo.toml` check. Refuse it if any path
validation changed. Do not refuse it merely because a thread is active,
unsettled, or deleted. The deletion itself goes through `safe_rm`.

## Step 2 — Scan: Foundry / cast / solc

- `~/.foundry/cache` — RPC + block cache (`cast`/`forge` fork cache). Usually the
  single biggest offender. Include the whole dir.
- Direct child directories named `anvil-state-*` beneath
  `~/.foundry/anvil/tmp` — temporary Anvil state snapshots. List each child and
  its modification time and size; never offer unknown siblings. Group these as
  **"Anvil temporary states"** and warn that deletion removes the ability to
  reload those local-chain snapshots. If `pgrep -x anvil` reports a running
  Anvil process, skip this category and print
  `Anvil temporary states: skipped (Anvil is running)`.
- `~/.svm` — installed solc compiler binaries (re-downloaded on demand).
- Per-project Foundry artifacts: a dir with a sibling `foundry.toml` →
  its `out/` and `cache/`. **Never** touch `broadcast/` (deployment records).

```bash
test -d "$HOME_REAL/.foundry/cache" && echo "$HOME_REAL/.foundry/cache"
test -d "$HOME_REAL/.foundry/anvil/tmp" && \
  find "$HOME_REAL/.foundry/anvil/tmp" -mindepth 1 -maxdepth 1 \
       -type d -name 'anvil-state-*' -print 2>/dev/null
test -d "$HOME_REAL/.svm" && echo "$HOME_REAL/.svm"
for root in "$HOME_REAL/Github" <extra-roots>; do
  find "$root" -type d -name node_modules -prune -o \
       -type f -name foundry.toml -print 2>/dev/null
done | while read -r cfg; do
  p="$(dirname "$cfg")"
  test -d "$p/out"   && echo "$p/out"
  test -d "$p/cache" && echo "$p/cache"
done
```

## Step 3 — Scan: global developer caches

Regenerated automatically on next build/fetch:
- `~/.cargo/registry/cache`
- `~/.cargo/registry/src`
- `~/.cargo/git/checkouts`
- `~/.cargo/git/db`

Leave `~/.cargo/registry/index` and `~/.cargo/bin` alone.

Also collect these as separate approval categories:

- `~/.cache/sccache` → **"Compiler cache (sccache)"**;
- `~/.cache/nix` → **"Nix user cache"**.

Both are regenerated on demand. Do not broaden either category to all of
`~/.cache`.

## Step 3a — Scan: dead Nix store paths

If both `nix-store` and `nix path-info` are available, list unreferenced store
paths read-only with:

```bash
nix-store --gc --print-dead 2>/dev/null
```

Pipe that exact list to `nix path-info --stdin --size` and sum the NAR sizes.
Record the count and label the size explicitly as a NAR-size estimate because
actual filesystem bytes freed can differ. Present one category named
**"Dead Nix store paths"**. Never scan `/nix` with `find` or `du`, never offer
live store paths, and never delete store paths with `rm` or `safe_rm`.

Approval of this category authorizes one canonical garbage collection:

```bash
nix-store --gc
```

Immediately before running it, re-list dead paths and report the refreshed
count and NAR-size estimate. If the command needs privileges or fails, report
the diagnostic; never retry with `sudo`. This category is the second exception
to `safe_rm`, after Git-managed whole T3 worktree removal.

## Step 4 — Scan: JS / web build bloat

Top-level only (prune so nested `node_modules` is counted once, not re-listed):

```bash
for root in "$HOME_REAL/Github" <extra-roots>; do
  find "$root" -type d -name node_modules -prune -print 2>/dev/null
done
```

Also collect, when they sit beside a `package.json`: `.next`, `.turbo`,
`.svelte-kit`, `coverage`, `dist`, `build`. These are presented for approval
like everything else — never auto-deleted.

## Step 5 — Scan: Hardhat

Dirs with a sibling `hardhat.config.{js,ts,cjs}` → their `artifacts/`, `cache/`,
and `typechain-types/`.

## Step 6 — Scan: Xcode DerivedData

If `~/Library/Developer/Xcode/DerivedData` exists and is non-empty, include its
contents as one candidate. Skip silently if absent.

## Step 6a — Settled T3 Code worktrees

T3 records the exact worktree path on the thread, so never guess locations from
Codex, Claude, Grok, or other provider session directories. Read each validated
`$T3_BASE/userdata/state.sqlite` with Bun's SQLite client in read-only mode.
Never mutate the database and never infer "settled" from provider process state,
archival, deletion, age, or an idle session. A whole-worktree candidate must
satisfy all of:

- `worktree_path IS NOT NULL`;
- every thread linked to the same `worktree_path`, including deleted threads,
  has `settled_override = 'settled'` and `settled_at IS NOT NULL` (one
  unsettled thread protects the shared worktree);
- `worktree_path` and its project's `workspace_root` are existing, distinct
  absolute paths under `$HOME_REAL` and contain no `..`;
- the worktree path is not the current directory or an ancestor of it;
- `git -C "$workspace_root" worktree list --porcelain` lists that exact path,
  and `git -C "$worktree_path" rev-parse --show-toplevel` resolves to that exact
  path (a legitimate linked worktree may live beneath the main repo);
- its `.git` is a file pointing to linked-worktree metadata. Never accept a
  normal repository root, even if corrupt T3 state names it.

First verify that the database contains `projection_threads` with
`settled_override`, `settled_at`, `deleted_at`, and `worktree_path`, plus
`projection_projects.workspace_root`. If the database or expected schema is
missing, print `T3 settled worktrees: skipped (unsupported/missing state DB)` and
continue with the other scans. A read-only query can return JSON lines with
`thread_id`, `title`, `deleted_at`, `worktree_path`, `workspace_root`,
`settled_at`, and the count of all non-settled links; deduplicate by
`worktree_path` before filesystem checks. A deleted thread is eligible only
when it is explicitly settled; deletion alone never counts as settlement.

For each validated candidate, record its total `dsize` (the whole worktree,
which already includes any nested Rust `target/`, `node_modules`, or other build
folders). Keep every descendant `target/` in the Rust-target category so the
user can clean build output while retaining the settled worktree. Mark the
overlap in the report and compute `Total reclaimable` from the union of paths,
not by naively summing overlapping category sizes. Add other descendants to
`seen` so later categories do not double count them. Inspect its state with:

```bash
git -C "$worktree_path" status --porcelain --untracked-files=normal
```

Group empty output into **"Settled T3 worktrees (clean)"**. Group non-empty
output separately into **"Settled T3 worktrees (dirty/untracked)"**, and show a
clear warning plus each thread title, path, branch/status summary, settled time,
and size. Dirty/untracked worktrees are recoverable only from Git or other
backups after deletion, so they must never be hidden inside the clean category.

Delete an approved candidate with Git, not raw `rm`:

```bash
git -C "$workspace_root" worktree remove --force -- "$worktree_path"
git -C "$workspace_root" worktree prune
```

Before running it, repeat every validation above against the saved
`(state_db, thread_id(s), workspace_root, worktree_path)` tuple and re-query the
database to prove every linked thread, including deleted threads, is still
explicitly settled.
If anything changed, refuse that candidate. `--force` is intentional only after
the clean or dirty category was explicitly approved; it removes the entire
worktree including its `target/` folder. Do not delete its Git branch, T3 thread,
conversation history, provider session/cache data, or database row. Do not run
`safe_rm` afterward: if Git fails or leaves the directory present, report the
refusal/failure and leave it intact.

T3 Code itself currently offers a narrower cleanup: deleting a thread in the UI
can prompt **"Delete the worktree too?"** when no other thread uses it. Marking a
thread settled does not remove its worktree, and the `t3` CLI has no settled
worktree cleanup subcommand. Mention this distinction when reporting T3 results.

## Step 6b — Ignored / temp bloat inside repos

For each git work tree under the scan roots, ask git itself what's ignored —
this catches `.tmp`, `tmp/`, `.cache`, `.turbo`, log dirs, Claude/editor temp
dirs, and anything else your `.gitignore` hides that isn't a named category.

Enumerate work trees (matches normal repos *and* worktrees, whose `.git` is a
file, not a dir):

```bash
for root in "$HOME_REAL/Github" <extra-roots>; do
  find "$root" -maxdepth 4 -name .git -not -path '*/node_modules/*' 2>/dev/null
done | while read -r g; do dirname "$g"; done | sort -u
```

For each work tree, list ignored entries with fully-ignored dirs collapsed to a
single path:

```bash
git -C "$wt" ls-files --others --ignored --exclude-standard --directory 2>/dev/null
```

Keep an entry only if **all** hold:
- its size ≥ `MIN_IGNORED_MB` (default 50 MB; `--min-ignored <MB>` overrides);
- its absolute path isn't already in the `seen` set (dedup);
- its basename isn't an already-handled category (`target`, `node_modules`,
  `out`, `cache`, `artifacts`, `typechain-types`);
- it does **not** match a sensitive pattern — never offered at any size:
  `.env`, `.env.*`, `*.key`, `*.pem`, `id_rsa*`, `*.keystore`, `*secret*`,
  `.netrc`, `credentials*`.

Group survivors into one category **"Other ignored / temp bloat"**, listing each
path + size (e.g. `.tmp/`, `.cache/`, `logs/`). Git-ignored = regenerable, but
still requires approval like everything else.

## Step 6c — Stale temp-dir leftovers

Review checkouts, validation copies, and scratch dirs pile up in the system
temp directory, which on many Linux machines sits on the root disk and is not
cleared on reboot. List the direct children of `/tmp` (Linux) or
`/private/tmp` and `$TMPDIR` (macOS). Keep an entry only if **all** hold:

- it is owned by the current user (`[ -O "$path" ]`);
- its size is ≥ `MIN_IGNORED_MB`, after subtracting any Rust target beneath it
  that Step 1 already listed (list that target under Rust targets, not here);
- it was last modified more than 24 hours ago;
- no running process has its working directory inside it (`/proc/*/cwd` on
  Linux, `lsof -d cwd` on macOS);
- it is not an agent's live session or scratch directory (for example the
  current `claude-<uid>` tree), a socket directory, or a `systemd-private-*`
  or `.X11-unix`-style system entry;
- it does not match a sensitive pattern from Step 6b.

Group survivors into **"Stale temp leftovers"** and list each path, size, and
age. For deletion, append the temp directory itself to `ALLOW_ROOTS`; the root
guard in `safe_rm` still refuses the temp directory. Immediately before each
deletion, repeat the owner and working-directory checks.

## Step 6d — Suggest-only items (never deleted by this skill)

Some large consumers are not safe for this skill to delete, or come back unless
configuration changes. Build a **Suggestions** list from the disk map with the
size, the reason, and the exact action for the user. Do not offer these in the
selector and do not run the commands yourself. Common cases:

- **Swapfile or swap partition** mostly unused, especially next to zram: on
  NixOS, shrink or remove the `swapDevices` entry and rebuild, then delete the
  old file. Deleting it by hand while it is active, or without the config
  change, breaks swap or brings it back.
- **Temp dir on the root disk that is never cleared:** on NixOS, suggest
  `boot.tmp.cleanOnBoot = true` (or `boot.tmp.useTmpfs = true` if RAM allows).
- **Nix generations** holding store paths live: list them with
  `nix-env --list-generations` for the user profile and home-manager, and
  `nix-env -p /nix/var/nix/profiles/system --list-generations` for the system.
  Suggest `nix-collect-garbage --delete-older-than 14d` for the user, and the
  same command with `sudo` for the system profile, run by the user.
- **Container images and volumes:** `docker system df`; suggest
  `docker system prune` (and `--volumes` only after they check the volumes).
- **System logs:** `journalctl --disk-usage`; suggest
  `sudo journalctl --vacuum-size=1G`.
- **Tool data** (`~/.codex*`, `~/.claude`, `~/.t3`, `~/.gemini`, `~/.grok`,
  editor data): name the largest subfolders (sessions, archived sessions,
  packages, databases), and point to the tool's own cleanup. Tool worktrees are
  handled only through their `target/` dirs (Step 1) or the T3 rules
  (Step 6a); never delete a tool worktree itself here.
- **Unallocated disk space or a disk smaller than expected:** from Step 0b.
- **Large unrecognized directories** (≥ `MIN_MAP_GB`, not matched by any
  category): list them with their owner and a best guess of what they are,
  clearly labelled as a guess. The user can ask for one to be removed; treat
  that as a new, explicit, per-path approval that still goes through
  `safe_rm` with that exact parent appended to `ALLOW_ROOTS`, and never for a
  path outside `$HOME` or the temp directory.

## Step 7 — Build categories and print the report

The report has three parts, in this order.

**Part 1 — Where the space is.** The Step 0b map: disk and partition sizes,
then for each filesystem the used/free totals and the tree of large
directories, each tagged `deletable`, `suggest`, or `keep`, and the
unaccounted remainder with its reason. For example:

```
Disk sda 500 GB → sda1 /boot 0.5 GB, sda2 / 499.5 GB (no unallocated space)
/  491 GB total, 383 GB used, 84 GB free
  120.0 GB  /home/juan/Github                          (see below)
   67.3 GB    …/st0x.liquidity/.worktrees/calm-heron/target   deletable
   52.0 GB  /home/juan/.codex-2
   47.0 GB    …/worktrees/12a1…/st0x.liquidity/target         deletable
   41.0 GB  /swapfile (0 B in use)                             suggest
   36.0 GB  /tmp
   32.0 GB    /tmp/st0x-issuance-review-xwfTPv/target         deletable
   19.0 GB  /nix/store (live)                                  keep
    2.1 GB  /var                                               keep
    0.4 GB  unaccounted (unreadable without root)
```

**Part 2 — Deletable categories.** Group every collected path into categories.
For each category compute the total size (sum of `dsize`) and item count. Sort
categories by size descending:

```
Reclaim-disk scan — nothing deleted yet
──────────────────────────────────────────────────────────────
  9.2 GB   Rust target/ dirs            (14 dirs)
  3.4 GB   node_modules                 (5 repos)
  3.1 GB   Foundry RPC/block cache      (~/.foundry/cache)
  2.8 GB   Anvil temporary states       (3 snapshots)
  2.6 GB   Settled T3 worktrees (clean) (6 worktrees)
  1.4 GB   Settled T3 worktrees (dirty) (2 worktrees; review carefully)
  2.0 GB   solc binaries                (~/.svm)
  1.1 GB   cargo registry/git caches    (4 dirs)
  0.9 GB   Dead Nix store paths         (210 paths; NAR-size estimate)
  0.7 GB   Compiler cache (sccache)      (~/.cache/sccache)
  0.5 GB   Nix user cache                (~/.cache/nix)
  0.8 GB   Other ignored / temp bloat   (.tmp, .cache in 3 repos)
  0.6 GB   Hardhat artifacts/cache      (2 repos)
  0.5 GB   Stale temp leftovers         (4 dirs in /tmp)
──────────────────────────────────────────────────────────────
  Total reclaimable: 24.7 GB
```

For categories with many items (e.g. 14 target dirs, or the ignored/temp
bucket), also print the individual paths + sizes below the table so the user can
see exactly what's in each bucket. Always print every settled T3 worktree with
its thread title and settled time, even when there is only one. If a listed
whole worktree contains a listed target, annotate the overlap and count those
bytes only once in `Total reclaimable`.

**Part 3 — Suggestions.** The Step 6d list, largest first, each with size,
reason, and the exact command or config change. End with one line that
compares used space to the total of Part 2 plus Part 3, so the user can see
how much of the disk is space they must keep (system, live Nix store, source,
and personal data).

If `--dry-run` was passed, **stop here.**

## Step 8 — Approve via grouped selector prompts

Ask the user (`multiSelect: true`) with **categories as the options**:

- Each option label = `"<category> — <human size>"`; description = item count +
  a few example paths.
- A selector question takes **2–4 options**, so chunk categories into questions
  of ≤4 options each; you may put up to 4 questions in a single
  question, and make additional calls if there are more than 16
  categories.
- If only **one** category exists, present it as a single-select question with
  options `"Delete (<size>)"` and `"Skip"`.
- Selected = approved for deletion. Unselected = kept.

Never collapse this into a single "delete everything" confirmation — the user
must tick each category they want gone.

## Step 9 — Delete approved categories and report

For every ordinary path in each approved category, call `safe_rm "$path"`
after the per-step revalidation (Step 1 for targets outside the dev roots,
Step 6c for temp leftovers). For
settled T3 worktrees only, use the revalidated Git removal procedure in Step
6a. If both a whole worktree and one of its target descendants were approved,
remove the whole worktree first, treat the disappeared target as subsumed, and
tally its bytes only once. If the whole worktree was kept but targets were
approved, delete every validated target beneath it. For dead Nix store paths
only, use the refreshed canonical GC procedure in Step 3a. Tally the KB freed
(sum of the pre-deletion sizes of paths actually removed); report Nix GC's own
freed-byte total rather than the NAR estimate when the command provides it.
Print:

```
Reclaimed 16.5 GB
  Deleted: Rust target/ (14), node_modules (5), Foundry cache, Other ignored (3)
  Kept:    solc binaries, cargo caches, Hardhat artifacts
  Refused: 0
```

If `safe_rm` refused any path, list it and why. Then show `df -h` for the
affected filesystems, and repeat the Part 3 suggestions that are still open.

## Hard rules

1. **Nothing is deleted without explicit approval.** The scan/report (Steps 0b–7)
   is always read-only. Deletion happens only in Step 9, only for categories the
   user ticked in Step 8.
2. **Every ordinary deletion goes through `safe_rm`** — absolute path, no `..`,
   under the allowlist, not a root, not a git repo root. The only exceptions are
   a T3 database-backed linked worktree removed through `git worktree remove`
   after Step 6a's validations, and dead Nix store paths removed through
   `nix-store --gc` after Step 3a's refreshed scan. Never use raw `rm` for
   either exception.
3. **Read wide, delete narrow.** Reading may cover the whole machine (Scope),
   but deletion only happens through `safe_rm` against `ALLOW_ROOTS`, extended
   only by the exact rules in Steps 0a, 1, 6c, and 6d. On macOS, never pass a
   TCC-protected path to any command. No `sudo`, no `mdfind`.
4. **Never delete source or records:** repo roots, `.git`, `Cargo.toml`,
   `~/.cargo/bin`, `~/.cargo/registry/index`, Foundry `broadcast/`.
5. **All validated targets are state-independent.** A `target` dir is offered
   regardless of T3 thread state, but only if it has `CACHEDIR.TAG` or a sibling
   `Cargo.toml` (both, and owned by the user, outside the dev roots and T3
   worktrees). Settlement gates whole-worktree removal, never target cleanup.
6. **Never offer or delete sensitive ignored files** regardless of size:
   `.env`, `.env.*`, `*.key`, `*.pem`, `id_rsa*`, `*.keystore`, `*secret*`,
   `.netrc`, `credentials*`. Git-ignored ≠ disposable.
7. `--dry-run` must never delete anything.
8. **Settled T3 worktrees are database-backed, not guessed.** Never scan
   provider session directories for them, never treat deleted/archived/idle/old
   as settled, never remove a worktree unless every linked thread is explicitly
   settled, and never delete the associated branch or T3 history. Never delete
   a normal repository root; only an exact Git-linked T3 worktree qualifies.
9. **T3 build artifacts are database-backed too.** Scan them only beneath an
   exact worktree path validated through both T3 state and Git. Delete every
   approved validated target regardless of thread state. Deleting a
   build-artifact descendant never authorizes deletion of the worktree root,
   source files, branch, thread, or provider history.
10. **Nix store cleanup uses Nix.** Never `find` or `rm` inside `/nix`, and
    measure it only as one total; never delete live store paths; never use
    `sudo`. Only run `nix-store --gc` after the user selects the dead-store
    category.
11. **Suggestions are not deletions.** Never run a Step 6d command yourself,
    never edit system configuration from this skill, and never delete a
    swapfile, log, container image, or Nix generation.

## Failure modes

- **A scan command errors on a permission boundary:** stderr is sent to
  `/dev/null`; the path is reported as unreadable. If you ever see a macOS
  access prompt, a scan entered a TCC-protected path — stop and fix the skip
  list.
- **The disk is completely full and the agent shell cannot start** (for example
  `ENOSPC` creating its temp dir): nothing can run. Tell the user to free a
  little space themselves (`df -h`, then a regenerable cache or old `/tmp`
  entry), then run the skill again.
- **`du` is slow on huge trees:** acceptable. Run the map in the background if
  needed, but do not skip it.
- **A candidate disappears between scan and delete** (concurrent build):
  `safe_rm` prints `skip (already gone)` and continues.
- **Any thread linked to a whole-worktree candidate becomes unsettled between
  scan and approval:** the mandatory re-query refuses whole-worktree removal.
  This state change does not protect validated `target/` descendants.
- **A T3 worktree build-artifact path fails revalidation:** refuse that path and
  leave it intact. Never fall back to scanning or deleting its parent.
- **Git refuses a settled T3 worktree removal:** report the exact path and Git
  diagnostic; do not fall back to `rm -rf`. The worktree and metadata stay for
  manual inspection.
- **Anvil starts after the scan:** repeat `pgrep -x anvil` immediately before
  deletion. If it is now running, refuse all Anvil-state candidates.
- **Nix GC permissions or daemon policy refuse collection:** report the exact
  diagnostic and keep the category. Never retry with `sudo` or raw deletion.
- **`git ls-files --ignored` run outside a repo:** returns nothing on stderr →
  that work tree is skipped. Worktrees are handled because their `.git` is a
  file and `dirname` still resolves the work-tree root.
- **Nothing reclaimable found:** print the empty report and exit without any
  selector prompt.
