#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo_root/dotcodex/skills"
dst="$HOME/.codex/skills"

mkdir -p "$dst"

find "$dst" -mindepth 1 -maxdepth 1 ! -name ".system" -exec rm -rf {} +

for skill in "$src"/*; do
  [ -d "$skill" ] || continue
  cp -R "$skill" "$dst/$(basename "$skill")"
done

if [ ! -e "$dst/.system" ] && [ -d "$HOME/.codex/system-skills" ]; then
  ln -s "$HOME/.codex/system-skills" "$dst/.system"
fi

echo "Synced Codex skills from $src to $dst"
