---
name: reclaim-disk
allowed-tools: Bash(find:*), Bash(du:*), Bash(rm:*), Bash(ls:*), Bash(test:*), Bash(awk:*), Bash(sort:*), Bash(dirname:*), Bash(basename:*), Bash(printf:*), Bash(echo:*), Bash(wc:*), Bash(cat:*), Bash(head:*), Bash(git:*), Bash(bun:*)
description: Reclaim SSD space by finding and (with per-category approval) deleting settled T3 Code worktrees, Rust target/ dirs, Foundry/cast caches, gitignored temp bloat, and other dev build artifacts. Uses T3's recorded worktree paths instead of assuming Codex, Claude, or Grok layouts. Strictly scoped to enumerated dev paths so macOS never prompts for file access. Nothing is deleted without explicit approval via selector prompts. Use /reclaim-disk, /reclaim-disk --dry-run, or /reclaim-disk <extra-root>.
argument-hint: [--dry-run] [--min-ignored <MB>] [extra-root ...]
disable-model-invocation: true
---

# Reclaim disk — prune build bloat with per-category approval

Find disk bloat across your dev directories and delete it **only after you
approve each category** in a selector prompt. Built for the "weeks of worktrees"
problem: settled T3 Code worktrees (regardless of whether Codex, Claude, Grok,
or another provider ran them), dozens of Rust `target/` dirs, Foundry RPC
caches, `node_modules`, and stray gitignored temp folders (`.tmp`, `.cache`,
logs, Claude/editor leftovers).

## Non-negotiable: stay scoped, never trigger macOS file-access prompts

macOS TCC prompts the terminal for permission the moment a command touches
`~/Desktop`, `~/Documents`, `~/Downloads`, iCloud Drive, or certain app data.
This command **only ever reads or deletes under an explicit allowlist of dev
paths**, so those prompts never appear.

- **NEVER** run `find` / `du` / `rm` rooted at `/`, `~`, `$HOME` (bare),
  `~/Desktop`, `~/Documents`, `~/Downloads`, or any iCloud path.
- **NEVER** use `sudo`, `mdfind`, or Spotlight.
- Only scan and delete under these roots (the allowlist):
  - `~/Github`
  - `~/.foundry`
  - `~/.svm`
  - `~/.cargo`
  - `~/.cache`
  - exact T3 Code worktree paths read from a validated T3 state database (never
    a provider's session/cache directory and never an inferred path)
  - `~/Library/Developer/Xcode/DerivedData`
  - `~/Library/Caches`
  - any extra root passed in the user's arguments (must be an existing absolute path under `$HOME`)
- Always redirect scan stderr to `/dev/null` so a stray permission error never
  derails the run.

## Step 0 — Parse arguments and define guards

Parse the user's arguments:
- `--dry-run` present → build and print the full report, then **stop** (no
  prompts, no deletion).
- `--min-ignored <MB>` → size threshold for the "Other ignored / temp bloat"
  scan (Step 6b). Default `50`.
- Any other token that is an existing absolute path under `$HOME` → add it to
  the scan roots **and** the deletion allowlist.

Define these helpers in the working shell and reuse them for every deletion.
The `safe_rm` guard is the last line of defense — every `rm -rf` goes through it.

```bash
HOME_REAL="$HOME"
MIN_IGNORED_MB=50   # overridden by --min-ignored
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
ownership: only exact paths returned by its database may receive the separate
T3 worktree deletion treatment in Step 6a.

Keep a running `seen` set of absolute paths already collected, so later scans
(especially Step 6b) never list the same path twice.

## Step 1 — Scan: Rust `target/` directories

Find every `target/` build dir under the scan roots, pruning so the search does
not descend into `target/`, `node_modules/`, or `.git/`. Confirm each is a real
Cargo target (has `CACHEDIR.TAG`, or a sibling `Cargo.toml`) so we never touch a
source folder that happens to be named `target`.

```bash
for root in "$HOME_REAL/Github" <extra-roots>; do
  find "$root" -type d \( -name node_modules -o -name .git \) -prune -o \
       -type d -name target -prune -print 2>/dev/null
done | while read -r d; do
  if [ -f "$d/CACHEDIR.TAG" ] || [ -f "$(dirname "$d")/Cargo.toml" ]; then
    echo "$d"
  fi
done
```

This covers main repos and every `*-worktrees/<name>/target`. Record each path
and its `dsize`.

## Step 2 — Scan: Foundry / cast / solc

- `~/.foundry/cache` — RPC + block cache (`cast`/`forge` fork cache). Usually the
  single biggest offender. Include the whole dir.
- `~/.svm` — installed solc compiler binaries (re-downloaded on demand).
- Per-project Foundry artifacts: a dir with a sibling `foundry.toml` →
  its `out/` and `cache/`. **Never** touch `broadcast/` (deployment records).

```bash
test -d "$HOME_REAL/.foundry/cache" && echo "$HOME_REAL/.foundry/cache"
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

## Step 3 — Scan: global cargo caches

Regenerated automatically on next build/fetch:
- `~/.cargo/registry/cache`
- `~/.cargo/registry/src`
- `~/.cargo/git/checkouts`
- `~/.cargo/git/db`

Leave `~/.cargo/registry/index` and `~/.cargo/bin` alone.

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
archival, age, or an idle session. A settled candidate must satisfy all of:

- `projection_threads.settled_override = 'settled'` and `settled_at IS NOT NULL`;
- `deleted_at IS NULL` and `worktree_path IS NOT NULL`;
- every other non-deleted thread linked to the same `worktree_path` is also
  explicitly settled (one active/unsettled thread protects the shared worktree);
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
`thread_id`, `title`, `worktree_path`, `workspace_root`, `settled_at`, and the
count of non-deleted non-settled links; deduplicate by `worktree_path` before
filesystem checks.

For each validated candidate, record its total `dsize` (the whole worktree,
which already includes any nested Rust `target/`, `node_modules`, or other build
folders) and add all descendants to `seen` so later categories do not double
count them. Inspect its state with:

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
database to prove every non-deleted linked thread is still explicitly settled.
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

## Step 7 — Build categories and print the report

Group every collected path into categories. For each category compute the
total size (sum of `dsize`) and item count. Sort categories by size descending.
Print a report:

```
Reclaim-disk scan (scoped to <N> roots) — nothing deleted yet
──────────────────────────────────────────────────────────────
  9.2 GB   Rust target/ dirs            (14 dirs)
  3.4 GB   node_modules                 (5 repos)
  3.1 GB   Foundry RPC/block cache      (~/.foundry/cache)
  2.6 GB   Settled T3 worktrees (clean) (6 worktrees)
  1.4 GB   Settled T3 worktrees (dirty) (2 worktrees; review carefully)
  2.0 GB   solc binaries                (~/.svm)
  1.1 GB   cargo registry/git caches    (4 dirs)
  0.8 GB   Other ignored / temp bloat   (.tmp, .cache in 3 repos)
  0.6 GB   Hardhat artifacts/cache      (2 repos)
──────────────────────────────────────────────────────────────
  Total reclaimable: 24.2 GB
```

For categories with many items (e.g. 14 target dirs, or the ignored/temp
bucket), also print the individual paths + sizes below the table so the user can
see exactly what's in each bucket. Always print every settled T3 worktree with
its thread title and settled time, even when there is only one.

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

For every ordinary path in each approved category, call `safe_rm "$path"`. For
settled T3 worktrees only, use the revalidated Git removal procedure in Step 6a.
Tally the KB freed (sum of the pre-deletion sizes of paths actually removed).
Print:

```
Reclaimed 16.5 GB
  Deleted: Rust target/ (14), node_modules (5), Foundry cache, Other ignored (3)
  Kept:    solc binaries, cargo caches, Hardhat artifacts
  Refused: 0
```

If `safe_rm` refused any path, list it and why.

## Hard rules

1. **Nothing is deleted without explicit approval.** The scan/report (Steps 1–7)
   is always read-only. Deletion happens only in Step 9, only for categories the
   user ticked in Step 8.
2. **Every ordinary deletion goes through `safe_rm`** — absolute path, no `..`,
   under the allowlist, not a root, not a git repo root. The sole exception is a
   T3 database-backed linked worktree, removed through `git worktree remove`
   only after Step 6a's scan-time and deletion-time validations both pass.
3. **Stay inside the allowlist.** Never scan or delete under `~/Desktop`,
   `~/Documents`, `~/Downloads`, iCloud, bare `~`, or `/`. No `sudo`, no
   `mdfind`. This is what keeps macOS from prompting for file access.
4. **Never delete source or records:** repo roots, `.git`, `Cargo.toml`,
   `~/.cargo/bin`, `~/.cargo/registry/index`, Foundry `broadcast/`.
5. A `target` dir is deletable only if it has `CACHEDIR.TAG` or a sibling
   `Cargo.toml`.
6. **Never offer or delete sensitive ignored files** regardless of size:
   `.env`, `.env.*`, `*.key`, `*.pem`, `id_rsa*`, `*.keystore`, `*secret*`,
   `.netrc`, `credentials*`. Git-ignored ≠ disposable.
7. `--dry-run` must never delete anything.
8. **Settled T3 worktrees are database-backed, not guessed.** Never scan
   provider session directories for them, never treat archived/idle/old as
   settled, never remove a worktree shared with a non-settled thread, and never
   delete the associated branch or T3 history.

## Failure modes

- **A scan command errors on a permission boundary:** stderr is sent to
  `/dev/null`; the path is simply skipped. If you ever see a macOS access
  prompt, a scan root escaped the allowlist — stop and fix the root list.
- **`du` is slow on huge trees:** acceptable; it runs once per candidate. Do not
  switch to a whole-`$HOME` scan to "speed it up."
- **A candidate disappears between scan and delete** (concurrent build):
  `safe_rm` prints `skip (already gone)` and continues.
- **A settled T3 thread changes state between scan and approval:** the mandatory
  re-query refuses removal. Re-scan before offering it again.
- **Git refuses a settled T3 worktree removal:** report the exact path and Git
  diagnostic; do not fall back to `rm -rf`. The worktree and metadata stay for
  manual inspection.
- **`git ls-files --ignored` run outside a repo:** returns nothing on stderr →
  that work tree is skipped. Worktrees are handled because their `.git` is a
  file and `dirname` still resolves the work-tree root.
- **Nothing reclaimable found:** print the empty report and exit without any
  selector prompt.
