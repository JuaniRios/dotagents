---
name: worktree
allowed-tools: Bash(wt:*), Bash(git:*), Bash(gt:*), Bash(nix:*), Bash(sqlx:*), Bash(jq:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(tr:*), Bash(test:*), Bash(wc:*), Bash(printf:*), Bash(command:*), Bash(dirname:*), Bash(echo:*), Bash(direnv:*), Read
description: Create, list, or remove branch-backed worktrees with Worktrunk (`wt`). Worktrees use the configured path inside the primary repo at .worktrees/<branch>, start from current remote trunk, and receive project setup (submodules, direnv, sqlx, Graphite). Use /worktree to create, /worktree remove <name> to delete, or /worktree list.
argument-hint: [remove <name> | list]
---

# Worktree — Worktrunk-managed parallel copies

Use Worktrunk (`wt`) as the authority for creating, listing, and removing git
worktrees. The user configuration sets:

```toml
worktree-path = "{{ repo_path }}/.worktrees/{{ branch | sanitize }}"
```

Therefore every linked checkout belongs under the primary repository's
`.worktrees/` directory. Do not duplicate Worktrunk's path calculation or use
`git worktree add/remove` directly.

## Layout

```
~/Github/st0x.liquidity/             # main repo
  .worktrees/                        # git-excluded worktree container
    curious-banana/                  # a worktree
    bold-octopus/                    # another worktree
```

## Mode detection

Parse the user's arguments:

- **Empty** or missing: create a new worktree.
- **`remove <name>`**: remove the named worktree through `wt`.
- **`list`**: list worktrees through `wt`.

## Step 1 — Verify Worktrunk and resolve the primary repo

```bash
command -v wt >/dev/null || { echo "Worktrunk (wt) is not installed"; exit 1; }
git_common_dir=$(git rev-parse --path-format=absolute --git-common-dir)
repo_root=$(dirname "$git_common_dir")
trunk=$(git -C "$repo_root" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
if [ -z "$trunk" ]; then
  if git -C "$repo_root" show-ref --verify --quiet refs/heads/main; then
    trunk="main"
  elif git -C "$repo_root" show-ref --verify --quiet refs/heads/master; then
    trunk="master"
  else
    echo "Cannot determine trunk branch"; exit 1
  fi
fi
git -C "$repo_root" fetch origin
```

Resolve the main repo through the common Git directory so invoking this skill
from an existing linked worktree still asks Worktrunk to operate on the
primary checkout.

## Step 2 — Generate a memorable name

Worktrunk is branch-oriented, so the memorable adjective-noun is both the
branch name and the configured `.worktrees/<name>` leaf.

```bash
adjectives="swift bold calm cool crisp deft dry eager fair fast fond free glad gold green keen kind lean lush mild neat pale pure raw red rich ripe safe sharp shy slim soft tall tame thin vast warm wide wild wise"
nouns="apple arrow badge beach bell bloom bolt bread brook brush cedar charm claw cliff cloud coral crane creek crown daisy delta dingo drift eagle ember fawn ferry flame frost gecko grove heron hound iris jade jewel kayak kite lemon lily lotus maple marsh melon moth opal otter pansy pearl plume quail raven reef robin sage seal shell snail spark squid stone storm thorn tiger trout tulip viper waltz whale wheat wren yak"

adj_arr=($adjectives)
noun_arr=($nouns)
name="${adj_arr[$((RANDOM % ${#adj_arr[@]}))]}-${noun_arr[$((RANDOM % ${#noun_arr[@]}))]}"
```

If `refs/heads/$name` already exists, regenerate once.

## Step 3 — Create through Worktrunk

```bash
if ! git -C "$repo_root" check-ignore --quiet .worktrees; then
  printf '\n.worktrees/\n' >> "$git_common_dir/info/exclude"
fi
result=$(wt -y -C "$repo_root" switch --create "$name" \
  --base "origin/$trunk" --no-cd --format=json)
wt_path=$(printf '%s' "$result" | jq -r '.path')
test -n "$wt_path" && test "$wt_path" != "null"
```

Verify Worktrunk honored the configured location before continuing:

```bash
case "$wt_path" in
  "$repo_root"/.worktrees/*) ;;
  *) echo "Worktrunk returned unexpected path: $wt_path"; exit 1 ;;
esac
```

The repository-local exclude prevents the in-repo worktree container from
appearing as an untracked directory without modifying tracked `.gitignore`.

Print the name and path clearly:

```
Worktree created: <name>
  Path: <wt_path>
  Branch: <name>
  Based on: origin/<trunk> (<short sha>)
```

## Step 4 — Initialize submodules (if any)

Check if the repo has submodules:

```bash
test -f "$repo_root/.gitmodules"
```

If yes, initialize them in the worktree using `--reference` to avoid
re-downloading objects from the network. The main repo already has all
submodule objects locally — reference them:

```bash
cd "$wt_path"
git submodule update --init --recursive --reference "$repo_root"
```

The `--reference` flag tells git to borrow objects from the main repo's
submodule clones, making this near-instant instead of fetching from the
network.

After submodule init, print how many submodules were initialized:

```bash
count=$(git submodule status --recursive | wc -l | tr -d ' ')
echo "Submodules initialized: $count (via --reference, no network fetch)"
```

Then `cd` back or use absolute paths for any remaining work.

## Step 4b — Allow direnv

If the worktree contains a `.envrc` file, run `direnv allow` so the
environment is ready when the user enters the directory:

```bash
test -f "$wt_path/.envrc" && direnv allow "$wt_path"
```

Print confirmation if direnv was allowed:

```
direnv: allowed <wt_path>/.envrc
```

## Step 4c — Project setup (deterministic checks)

Run these checks from `$wt_path`. Each check is independent — run all
that apply, in order.

### Solidity artifacts

If the repo has a nix flake with `prep-sol-artifacts`, compile them:

```bash
cd "$wt_path"
if nix flake show 2>/dev/null | grep -q prep-sol-artifacts; then
  echo "Setup: compiling Solidity artifacts..."
  nix run .#prep-sol-artifacts
  echo "Setup: Solidity artifacts ready"
fi
```

This is **not optional** — the build will fail without these artifacts.

### sqlx database

If the repo uses sqlx (has a `.sqlx/` directory or `sqlx` in any
`Cargo.toml`), reset the database so sqlx macros can compile:

```bash
cd "$wt_path"
if [ -d ".sqlx" ] || grep -rq 'sqlx' Cargo.toml crates/*/Cargo.toml 2>/dev/null; then
  echo "Setup: initializing sqlx database..."
  sqlx db reset -y
  echo "Setup: database ready"
fi
```

## Step 4d — Initialize Graphite

Initialize Graphite in the new worktree so `gt` commands work immediately:

```bash
cd "$wt_path"
gt init --trunk "$trunk" --no-interactive
```

Print confirmation:

```
Graphite: initialized (trunk: <trunk>)
```

## Step 5 — Remove through Worktrunk

When the user's arguments starts with `remove`:

1. Extract the worktree branch name or path.
2. Resolve `repo_root` through the common Git directory as in step 1.
3. Run foreground removal so completion is known before reporting success:

   ```bash
   wt -y -C "$repo_root" remove --foreground "<name-or-path>"
   ```

4. Do not add `--force` or `--force-delete` unless the user explicitly asks to
   discard dirty or unmerged work. Worktrunk safely deletes the branch only
   when its changes are already integrated.
5. Print confirmation:

   ```
   Worktree '<name>' removed through Worktrunk.
   ```

## Step 6 — List through Worktrunk

When the user's arguments is `list`:

```bash
git_common_dir=$(git rev-parse --path-format=absolute --git-common-dir)
repo_root=$(dirname "$git_common_dir")
wt -C "$repo_root" list
```

Do not substitute `git worktree list`; Worktrunk's view includes branch,
status, integration state, and the configured path.

## Final output

After creating a worktree, print a ready-to-use summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Worktree ready: <name>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Path:       <wt_path>
  Branch:     <name>
  Based on:   origin/<trunk> (<short sha>)
  Submodules: <count> initialized  (only if .gitmodules exists)
  Setup:      <commands run, or "none needed">
  Graphite:   initialized (trunk: <trunk>)

To open in a new terminal:
  cd <wt_path>

To remove later:
  /worktree remove <name>
```

## Hard rules

1. Use `wt` for create, list, and remove. Never call `git worktree add/remove`
   from this skill.
2. Worktrees are branch-backed and start at the latest `origin/<trunk>`.
3. Require Worktrunk's returned path to be inside the primary repo's
   `.worktrees/` directory.
4. Never force removal or branch deletion without explicit user approval.
5. Always use `--reference` for submodule init to avoid network fetches.
