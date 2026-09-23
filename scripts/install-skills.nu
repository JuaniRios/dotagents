# Mirror personal skills, private JuaniRios/dotagents-private skills, and the
# shared T0Trade/agent-skills skills into every harness's skill directory,
# register the shared goal-loop Stop hook on Grok, Codex, and Agy, and link
# instructions/AGENTS.md as each harness's global instruction file. Clones
# ~/Github/agent-skills and ~/Github/dotagents-private when missing and
# fast-forwards clean main checkouts; a network failure only prints a note.
#
# Usage:
#   nu ~/Github/dotagents/scripts/install-skills.nu
#   nu ~/Github/dotagents/scripts/install-skills.nu --dry-run
#
# Each harness gets a per-entry symlink to the owning skills/<name>. Stale
# links that point at any source (or leftover pre-unify skill trees) are
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
  let private_repo = ($env.HOME | path join "Github" "dotagents-private")
  sync-shared-repo $shared_repo "https://github.com/T0Trade/agent-skills.git" $dry_run
  sync-shared-repo $private_repo "https://github.com/JuaniRios/dotagents-private.git" $dry_run
  let shared_src = ($shared_repo | path join "skills")
  let private_src = ($private_repo | path join "skills")
  if not ($personal_src | path exists) {
    error make {msg: $"missing ($personal_src)"}
  }
  let optional_names = {|src|
    if ($src | path exists) {
      skill-names $src
    } else {
      print $"note: missing optional skill source ($src)"
      []
    }
  }
  let trees = [
    {label: "dotagents", src: $personal_src, names: (skill-names $personal_src)}
    {label: "agent-skills", src: $shared_src, names: (do $optional_names $shared_src)}
    {label: "dotagents-private", src: $private_src, names: (do $optional_names $private_src)}
  ]
  let conflicts = ($trees | get names | flatten | uniq --repeated)
  if not ($conflicts | is-empty) {
    error make {msg: $"duplicate skill names across ($trees | get label | str join ', '): ($conflicts | str join ', ')"}
  }
  let names = ($trees | get names | flatten | sort)
  let sources = ($trees | get src)
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
    for tree in $trees {
      for name in $tree.names {
        link-one ($tree.src | path join $name) ($dest | path join $name) $dry_run
      }
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

  # Global instruction files, so every session loads the graphite skill from
  # ~/Github/agent-skills. Claude expands the @ import; other harnesses read the
  # pointer. Codex reads AGENTS.override.md when that file exists, so target
  # whichever file each home actually loads. An existing real file is left alone
  # (link-one prints a skip note).
  let instructions = ($env.HOME | path join "Github" "dotagents" "instructions" "AGENTS.md")
  let codex_instructions = {|home|
    if (($home | path join "AGENTS.override.md") | path exists) {
      $home | path join "AGENTS.override.md"
    } else {
      $home | path join "AGENTS.md"
    }
  }
  let instruction_dests = ([
    ($env.HOME | path join ".claude" "CLAUDE.md")
    (do $codex_instructions ($env.HOME | path join ".codex"))
    (do $codex_instructions ($env.HOME | path join ".codex-2"))
    ($env.HOME | path join ".gemini" "GEMINI.md")
  ] | where {|dest| ($dest | path dirname | path exists)})
  for dest in $instruction_dests {
    link-one $instructions $dest $dry_run | ignore
  }

  install-hooks $dry_run

  let counts = ($trees | each {|t| $"($t.names | length) ($t.label)"} | str join " + ")
  print $"($names | length) skills: ($counts) -> ($dests | length) harness dirs"
}
