#!/usr/bin/env bash
# Scaffold a new skill from template/ and register it in the plugin marketplace.
# Usage: scripts/new-skill.sh <skill-name> "<one-line plugin description>"
set -euo pipefail

name="${1:-}"
summary="${2:-}"
root="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$name" || -z "$summary" ]]; then
  echo "Usage: scripts/new-skill.sh <skill-name> \"<one-line description>\"" >&2
  exit 2
fi
if ! [[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || (( ${#name} > 64 )); then
  echo "Error: '$name' must be 1-64 chars of lowercase a-z, 0-9 and single hyphens." >&2
  exit 2
fi
dest="$root/skills/$name"
if [[ -e "$dest" ]]; then
  echo "Error: $dest already exists." >&2
  exit 1
fi

mkdir -p "$dest"
cp -R "$root/template/." "$dest/"
mv "$dest/SKILL.md.tmpl" "$dest/SKILL.md"
sed -i.bak "s/^name: skill-name$/name: $name/; s/\"skill_name\": \"skill-name\"/\"skill_name\": \"$name\"/" \
  "$dest/SKILL.md" "$dest/evals/evals.json"
rm -f "$dest/SKILL.md.bak" "$dest/evals/evals.json.bak"

python3 - "$root/.claude-plugin/marketplace.json" "$name" "$summary" <<'PY'
import json, sys
path, name, summary = sys.argv[1:]
data = json.load(open(path))
if not any(p["name"] == name for p in data["plugins"]):
    data["plugins"].append({"name": name, "description": summary, "source": "./",
                            "strict": False, "skills": [f"./skills/{name}"]})
    data["plugins"].sort(key=lambda p: p["name"])
json.dump(data, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY

echo "Created skills/$name and registered it in .claude-plugin/marketplace.json"
echo "Next: edit skills/$name/SKILL.md, then run: make validate"
