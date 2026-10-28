---
name: worktree
allowed-tools: Bash(git:*), Bash(gt:*), Bash(nix:*), Bash(sqlx:*), Bash(jq:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(tr:*), Bash(test:*), Bash(wc:*), Bash(printf:*), Bash(command:*), Bash(dirname:*), Bash(echo:*), Bash(direnv:*), Read
description: Create, list, or remove branch-backed worktrees with native `git worktree`. Worktrees live inside the primary repo at .worktrees/<branch>, start from current remote trunk, and receive project setup (submodules, direnv, sqlx, Graphite). Use /worktree to create, /worktree remove <name> to delete, or /worktree list.
argument-hint: [remove <name> | list]
---

# Worktree — native git worktrees

Use native `git worktree` to create, list, and remove worktrees. Do not use
Worktrunk (`wt`) or lazygit: `wt` is not installed on every host, and lazygit
is an interactive TUI with no scriptable worktree command.

Every linked checkout belongs under the primary repository's `.worktrees/`
directory, at `.worktrees/<branch>` with `/` in the branch replaced by `-`.

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
- **`remove <name>`**: remove the named worktree.
- **`list`**: list worktrees.

## Step 1 — Resolve the primary repo

```bash
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
from an existing linked worktree still creates the worktree under the
primary checkout.

## Step 2 — Generate a memorable name

The memorable adjective-noun is both the branch name and the
`.worktrees/<name>` leaf. If the user named a branch, use it instead.

```bash
adjectives="swift bold calm cool crisp deft dry eager fair fast fond free glad gold green keen kind lean lush mild neat pale pure raw red rich ripe safe sharp shy slim soft tall tame thin vast warm wide wild wise"
nouns="apple arrow badge beach bell bloom bolt bread brook brush cedar charm claw cliff cloud coral crane creek crown daisy delta dingo drift eagle ember fawn ferry flame frost gecko grove heron hound iris jade jewel kayak kite lemon lily lotus maple marsh melon moth opal otter pansy pearl plume quail raven reef robin sage seal shell snail spark squid stone storm thorn tiger trout tulip viper waltz whale wheat wren yak"

adj_arr=($adjectives)
noun_arr=($nouns)
name="${adj_arr[$((RANDOM % ${#adj_arr[@]}))]}-${noun_arr[$((RANDOM % ${#noun_arr[@]}))]}"
```

If `refs/heads/$name` already exists, regenerate once.

## Step 3 — Create with git worktree

```bash
if ! git -C "$repo_root" check-ignore --quiet .worktrees; then
  printf '\n.worktrees/\n' >> "$git_common_dir/info/exclude"
fi
wt_path="$repo_root/.worktrees/$(printf '%s' "$name" | tr '/' '-')"
git -C "$repo_root" worktree add -b "$name" "$wt_path" "origin/$trunk"
```

To check out a branch that already exists on the remote instead of creating
one, use `git -C "$repo_root" worktree add --track -b "$name" "$wt_path"
"origin/$name"`.

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

## Step 5 — Remove

When the user's arguments starts with `remove`:

1. Extract the worktree branch name or path.
2. Resolve `repo_root` through the common Git directory as in step 1.
3. Remove the worktree, then delete the branch only if it is merged:

   ```bash
   git -C "$repo_root" worktree remove "$wt_path"
   git -C "$repo_root" branch -d "$name" \
     || echo "Branch '$name' kept: it has unmerged commits"
   ```

4. Do not add `--force` to `worktree remove`, or use `branch -D`, unless the
   user explicitly asks to discard dirty or unmerged work.
5. Print confirmation:

   ```
   Worktree '<name>' removed.
   ```

## Step 6 — List

When the user's arguments is `list`:

```bash
git_common_dir=$(git rev-parse --path-format=absolute --git-common-dir)
repo_root=$(dirname "$git_common_dir")
git -C "$repo_root" worktree list
```

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

1. Use native `git worktree` for create, list, and remove. Never use `wt` or
   lazygit.
2. Worktrees are branch-backed and start at the latest `origin/<trunk>`.
3. Create every worktree inside the primary repo's `.worktrees/` directory.
4. Never force removal or branch deletion without explicit user approval.
5. Always use `--reference` for submodule init to avoid network fetches.
