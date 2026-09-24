#!/usr/bin/env bash
# Symlink every skill in this repo into an agent's skills directory for local
# development, so edits here are live without reinstalling.
# Usage: scripts/link-local.sh [target-dir]   (default: ~/.claude/skills)
#        scripts/link-local.sh --unlink [target-dir]
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
unlink=false
if [[ "${1:-}" == "--unlink" ]]; then unlink=true; shift; fi
target="${1:-$HOME/.claude/skills}"
mkdir -p "$target"

for dir in "$root"/skills/*/; do
  name="$(basename "$dir")"
  link="$target/$name"
  if $unlink; then
    if [[ -L "$link" ]]; then rm "$link"; echo "unlinked $link"; fi
    continue
  fi
  if [[ -e "$link" && ! -L "$link" ]]; then
    echo "skip: $link exists and is not a symlink (remove it first)" >&2
    continue
  fi
  ln -sfn "${dir%/}" "$link"
  echo "linked $link -> ${dir%/}"
done
