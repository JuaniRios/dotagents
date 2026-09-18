# Mirror personal skills plus the shared T0Trade/agent-skills skills into every
# harness's skill directory, and register the shared goal-loop Stop hook on
# Grok, Codex, and Agy. Clones ~/Github/agent-skills when it is missing and
# fast-forwards a clean main checkout; a network failure only prints a note.
#
# Usage:
#   nu ~/Github/dotagents/scripts/install-skills.nu
#   nu ~/Github/dotagents/scripts/install-skills.nu --dry-run
#
# Each harness gets a per-entry symlink to the owning skills/<name>. Stale
# links that point at either source (or leftover pre-unify skill trees) are
# removed. Duplicate names are an error: ownership must stay unambiguous.
# Codex's .system link to ~/.codex/system-skills is preserved.
# Claude's Stop hook stays in ~/.claude/settings.json (already pointed
# at hooks/goal-loop/check-goal.sh).

def skill-names [src: path]: nothing -> list<string> {
  ls $src
  | where type == dir
  | get name
  | where {|p| ($p | path join "SKILL.md" | path exists)}
  | each {|p| $p | path basename}
  | sort
}

def sync-shared-repo [repo: path, url: string, dry: bool] {
  $env.GIT_TERMINAL_PROMPT = "0"
  if not ($repo | path exists) {
    if $dry {
      print $"would clone ($url) into ($repo)"
      return
    }
    let r = (do { ^git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 clone --quiet $url $repo } | complete)
    if $r.exit_code != 0 {
      print $"note: could not clone ($url): ($r.stderr | str trim)"
    }
    return
  }
  let branch = (do { ^git -C $repo branch --show-current } | complete | get stdout | str trim)
  let dirty = (do { ^git -C $repo status --porcelain } | complete | get stdout | str trim)
  if $branch != "main" or $dirty != "" {
    print $"note: ($repo) is not a clean main checkout — not pulling"
    return
  }
  if $dry {
    print $"would fast-forward ($repo)"
    return
  }
  let r = (do { ^git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 -C $repo pull --quiet --ff-only } | complete)
  if $r.exit_code != 0 {
    print $"note: could not update ($repo): ($r.stderr | str trim)"
  }
}

def ensure-real-dir [dir: path] {
  if ($dir | path exists) {
    let info = (ls -D $dir | get 0)
    if $info.type == "symlink" {
      let target = (ls -lD $dir | get 0.target?)
      print $"replacing whole-dir symlink ($dir) -> ($target) with a real directory"
      rm $dir
      mkdir $dir
    }
  } else {
    mkdir $dir
  }
}

def link-one [src_skill: path, dest: path, dry: bool] {
  let want = ($src_skill | path expand)
  # `path exists` is false for a dangling symlink, so also ask `test -L`.
  if ($dest | path exists) or ((do { ^test -L $dest } | complete).exit_code == 0) {
    let info = (ls -D $dest | get 0)
    if $info.type == "symlink" {
      let have = (ls -lD $dest | get 0.target? | default "" | path expand)
      if $have == $want {
        return "ok"
      }
      if $dry {
        print $"would relink ($dest)"
        return "relink"
      }
      rm $dest
    } else {
      print $"skip ($dest): exists and is not a symlink"
      return "skip"
    }
  }
  if $dry {
    print $"would link ($dest) -> ($want)"
    return "link"
  }
  ^ln -s $want $dest
  "link"
}

def prune-stale [dest_root: path, live: list<string>, sources: list<path>, dry: bool] {
  if not ($dest_root | path exists) { return }
  let personal_src = ($env.HOME | path join "Github" "dotagents" "skills")
  let stale_prefixes = ($sources | append [
    ($personal_src | path dirname | path join "dotclaude" "skills")
    ($personal_src | path dirname | path join "dotcodex" "skills")
    ($personal_src | path dirname | path join "t0.devops" "skills")
  ])
  ls -l $dest_root
  | where type == symlink
  | each {|row|
      let name = ($row.name | path basename)
      if $name == ".system" { return }
      if $name in $live { return }
      let target = (try { $row.target | path expand } catch { "" })
      let ours = ($stale_prefixes | any {|p| $target | str starts-with $p})
      if $ours {
        if $dry {
          print $"would remove stale ($row.name)"
        } else {
          rm $row.name
          print $"removed stale ($name)"
        }
      }
    }
  | ignore
}

def hook-script []: nothing -> string {
  $env.HOME | path join "Github" "dotagents" "hooks" "goal-loop" "check-goal.sh"
}

def write-file [dest: path, content: string, dry: bool] {
  if ($dest | path exists) {
    let have = (open --raw $dest)
    if $have == $content {
      return "ok"
    }
  }
  if $dry {
    print $"would write ($dest)"
    return "write"
  }
  mkdir ($dest | path dirname)
  $content | save --force $dest
  print $"wrote ($dest)"
  "write"
}

def install-hooks [dry: bool] {
  let script = (hook-script)
  if not ($script | path exists) {
    print $"note: missing ($script) — skip hook install"
    return
  }

  # Grok: dedicated file, safe to overwrite.
  let grok = ($env.HOME | path join ".grok" "hooks" "goal-loop.json")
  let grok_json = ({
    hooks: {
      Stop: [
        {
          hooks: [
            { type: "command", command: $script, timeout: 30 }
          ]
        }
      ]
    }
  } | to json)
  write-file $grok $grok_json $dry

  # Codex: write hooks.json if missing or already ours; otherwise warn.
  # ~/.codex-2 is the second ChatGPT account (ccxx / default `codex`).
  let codex_json = ({
    description: "Shared goal-loop Stop hook from ~/Github/dotagents."
    hooks: {
      Stop: [
        {
          hooks: [
            {
              type: "command"
              command: $script
              timeout: 30
              statusMessage: "Checking goal loop"
            }
          ]
        }
      ]
    }
  } | to json)
  for home_name in [".codex" ".codex-2"] {
    let codex = ($env.HOME | path join $home_name "hooks.json")
    if ($codex | path exists) and not ((open --raw $codex) | str contains "goal-loop/check-goal.sh") {
      print $"note: ($codex) exists without the goal-loop hook — add Stop -> ($script) by hand, then /hooks to trust it"
    } else {
      let result = (write-file $codex $codex_json $dry)
      if (not $dry) and ($result == "write") {
        print $"note: Codex must trust the hook once — run /hooks in a ($home_name) session"
      }
    }
  }

  # Agy: global customization root. Dedicated top-level key.
  let agy = ($env.HOME | path join ".gemini" "config" "hooks.json")
  let agy_json = ({
    "goal-loop": {
      Stop: [
        { type: "command", command: $script, timeout: 30 }
      ]
    }
  } | to json)
  if ($agy | path exists) and not ((open --raw $agy) | str contains "goal-loop/check-goal.sh") {
    print $"note: ($agy) exists without the goal-loop hook — merge the goal-loop Stop entry by hand"
  } else {
    write-file $agy $agy_json $dry
  }
}

def main [--dry-run] {
  let personal_src = ($env.HOME | path join "Github" "dotagents" "skills")
  let shared_repo = ($env.HOME | path join "Github" "agent-skills")
  sync-shared-repo $shared_repo "https://github.com/T0Trade/agent-skills.git" $dry_run
  let shared_src = ($shared_repo | path join "skills")
  if not ($personal_src | path exists) {
    error make {msg: $"missing ($personal_src)"}
  }
  let personal_names = (skill-names $personal_src)
  let shared_names = if ($shared_src | path exists) {
    skill-names $shared_src
  } else {
    print $"note: missing optional shared skill source ($shared_src)"
    []
  }
  let conflicts = ($personal_names | where {|name| $name in $shared_names})
  if not ($conflicts | is-empty) {
    error make {msg: $"duplicate skill names in dotagents and agent-skills: ($conflicts | str join ', ')"}
  }
  let names = ($personal_names | append $shared_names | sort)
  let sources = [$personal_src $shared_src]
  let dests = [
    ($env.HOME | path join ".claude" "skills")
    ($env.HOME | path join ".codex" "skills")
    ($env.HOME | path join ".codex-2" "skills")
    ($env.HOME | path join ".grok" "skills")
    ($env.HOME | path join ".gemini" "config" "skills")
    ($env.HOME | path join ".gemini" "antigravity-cli" "skills")
  ]

  for dest in $dests {
    ensure-real-dir $dest
    for name in $personal_names {
      let src_skill = ($personal_src | path join $name)
      let dest_skill = ($dest | path join $name)
      link-one $src_skill $dest_skill $dry_run
    }
    for name in $shared_names {
      let src_skill = ($shared_src | path join $name)
      let dest_skill = ($dest | path join $name)
      link-one $src_skill $dest_skill $dry_run
    }
    prune-stale $dest $names $sources $dry_run
  }

  # Codex ships system skills next to user skills. The second account
  # (CODEX_HOME=~/.codex-2) reuses the copy under ~/.codex.
  let system_src = ($env.HOME | path join ".codex" "system-skills")
  for home_name in [".codex" ".codex-2"] {
    let system_dst = ($env.HOME | path join $home_name "skills" ".system")
    if ($system_src | path exists) and not ($system_dst | path exists) {
      if $dry_run {
        print $"would link ($system_dst) -> ($system_src)"
      } else {
        ^ln -s $system_src $system_dst
      }
    }
  }

  # Grok also walks the source tree via [skills].paths.
  let grok_cfg = ($env.HOME | path join ".grok" "config.toml")
  if ($grok_cfg | path exists) {
    let text = (open --raw $grok_cfg)
    if not ($text | str contains "Github/dotagents/skills") {
      print $"note: add to ($grok_cfg):\n[skills]\npaths = [\"~/Github/dotagents/skills\"]"
    }
  }

  install-hooks $dry_run

  print $"($names | length) skills: ($personal_names | length) personal + ($shared_names | length) agent-skills -> ($dests | length) harness dirs"
}
