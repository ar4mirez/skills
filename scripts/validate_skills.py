#!/usr/bin/env python3
"""Validate every skill in this repository against the Agent Skills spec
(https://agentskills.io/specification) plus this repo's conventions.

Usage:
  python3 scripts/validate_skills.py              # validate all skills under skills/
  python3 scripts/validate_skills.py skills/foo   # validate specific skill dirs
  python3 scripts/validate_skills.py --strict     # treat warnings as errors

Exit codes: 0 = valid, 1 = errors found, 2 = bad invocation.

Standard library only, so it runs in CI and on any machine with Python 3.9+.
For the canonical reference check, also run `skills-ref validate <dir>`
(see README.md > Development).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000  # spec recommendation; estimated as words * 1.3
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
PATH_RE = re.compile(r"`((?:references|assets|scripts|evals)/[^`\s]+)`")


class Report:
    def __init__(self, skill: str):
        self.skill = skill
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 4 :].lstrip("\n")


def parse_frontmatter(raw: str, rep: Report) -> dict:
    """Parse the YAML subset the spec uses: scalars, quoted scalars, folded/literal
    block scalars (> and |), and one level of nested string maps (metadata)."""
    data: dict = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line.startswith((" ", "\t")):
            rep.error(f"frontmatter: unexpected indentation on line {i + 1}: {line!r}")
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            rep.error(f"frontmatter: cannot parse line {i + 1}: {line!r}")
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        i += 1
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joiner = " " if value.startswith(">") else "\n"
            data[key] = joiner.join(b for b in block if b).strip()
        elif value == "":
            nested: dict = {}
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                sub = lines[i].strip()
                i += 1
                if not sub:
                    continue
                sm = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", sub)
                if not sm:
                    rep.error(f"frontmatter: cannot parse nested line under '{key}': {sub!r}")
                    continue
                sval = sm.group(2).strip()
                if not (sval.startswith(("'", '"'))) and re.fullmatch(r"-?\d+(\.\d+)?|true|false|null", sval):
                    rep.warn(f"frontmatter: {key}.{sm.group(1)} = {sval} is not quoted; "
                             "spec requires string values (quote it)")
                nested[sm.group(1)] = sval.strip("'\"")
            data[key] = nested
        else:
            data[key] = value.strip("'\"") if value[:1] in "'\"" else value
    return data


def check_skill(skill_dir: Path, listed_in_marketplace: set[str] | None) -> Report:
    rep = Report(skill_dir.name)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        rep.error("missing SKILL.md")
        return rep

    text = skill_md.read_text(encoding="utf-8")
    raw, body = split_frontmatter(text)
    if raw is None:
        rep.error("SKILL.md must start with YAML frontmatter delimited by '---' lines")
        return rep
    fm = parse_frontmatter(raw, rep)

    for key in fm:
        if key not in ALLOWED_KEYS:
            rep.error(f"frontmatter: unknown field '{key}' (allowed: {', '.join(sorted(ALLOWED_KEYS))})")

    name = fm.get("name")
    if not name:
        rep.error("frontmatter: 'name' is required")
    else:
        if len(name) > 64:
            rep.error(f"name: {len(name)} chars (max 64)")
        if not NAME_RE.match(name):
            rep.error(f"name: '{name}' must be lowercase a-z, 0-9 and single hyphens, "
                      "not starting/ending with a hyphen")
        if name != skill_dir.name:
            rep.error(f"name: '{name}' must match its directory name '{skill_dir.name}'")

    desc = fm.get("description")
    if not desc:
        rep.error("frontmatter: 'description' is required and must be non-empty")
    else:
        if len(desc) > 1024:
            rep.error(f"description: {len(desc)} chars (max 1024)")
        if not re.search(r"\b(use (this|when)|when the user|use it when)\b", desc, re.I):
            rep.warn("description: say *when* to use the skill (e.g. 'Use when ...') so agents trigger it")

    comp = fm.get("compatibility")
    if comp is not None and not (1 <= len(comp) <= 500):
        rep.error(f"compatibility: must be 1-500 chars (got {len(comp)})")

    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        rep.error("metadata: must be a map of string keys to string values")

    if not fm.get("license"):
        rep.warn("frontmatter: add a 'license' field so the skill is portable on its own")

    body_lines = body.count("\n") + 1
    if body_lines > MAX_BODY_LINES:
        rep.warn(f"SKILL.md body is {body_lines} lines (spec recommends < {MAX_BODY_LINES}); "
                 "move detail into references/")
    est_tokens = int(len(body.split()) * 1.3)
    if est_tokens > MAX_BODY_TOKENS:
        rep.warn(f"SKILL.md body is ~{est_tokens} tokens (spec recommends < {MAX_BODY_TOKENS})")

    # Every relative file SKILL.md points at must exist, and stay one level deep.
    refs = set(LINK_RE.findall(body)) | set(PATH_RE.findall(body))
    for ref in sorted(refs):
        if re.match(r"^[a-z]+://", ref) or ref.startswith("mailto:"):
            continue
        target = (skill_dir / ref).resolve()
        if not target.exists():
            rep.error(f"SKILL.md references '{ref}' but it does not exist")
        elif skill_dir.resolve() not in target.parents and target != skill_dir.resolve():
            rep.error(f"SKILL.md references '{ref}' outside the skill directory (breaks portability)")
        if ref.count("/") > 1:
            rep.warn(f"'{ref}' is nested more than one level deep; spec recommends one level")

    # Orphans: bundled files nobody tells the agent about are dead weight.
    for sub in ("references", "assets", "scripts"):
        d = skill_dir / sub
        if d.is_dir():
            for f in sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
                rel = f.relative_to(skill_dir).as_posix()
                if rel not in body:
                    rep.warn(f"'{rel}' is never mentioned in SKILL.md; the agent won't know when to load it")

    for script in (skill_dir / "scripts").glob("*") if (skill_dir / "scripts").is_dir() else []:
        if script.suffix == ".py" and script.is_file():
            src = script.read_text(encoding="utf-8")
            if "argparse" not in src and "--help" not in src:
                rep.warn(f"{script.name}: scripts should document usage via --help")

    evals = skill_dir / "evals" / "evals.json"
    if evals.is_file():
        try:
            data = json.loads(evals.read_text(encoding="utf-8"))
            if data.get("skill_name") != skill_dir.name:
                rep.error(f"evals/evals.json: skill_name '{data.get('skill_name')}' != '{skill_dir.name}'")
            for case in data.get("evals", []):
                for key in ("id", "prompt", "expected_output"):
                    if key not in case:
                        rep.error(f"evals/evals.json: case {case.get('id', '?')} is missing '{key}'")
                for f in case.get("files", []):
                    if not (skill_dir / f).exists():
                        rep.error(f"evals/evals.json: case {case.get('id')} references missing file '{f}'")
        except json.JSONDecodeError as exc:
            rep.error(f"evals/evals.json: invalid JSON ({exc})")
    else:
        rep.warn("no evals/evals.json; add test cases (see AGENTS.md > Evaluate)")

    if listed_in_marketplace is not None and skill_dir.name not in listed_in_marketplace:
        rep.error("not listed in .claude-plugin/marketplace.json (add a plugin entry for it)")

    return rep


def marketplace_skills() -> set[str] | None:
    if not MARKETPLACE.is_file():
        return None
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    names = set()
    for plugin in data.get("plugins", []):
        for s in plugin.get("skills", []):
            names.add(Path(s).name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="skill directories (default: every dir in skills/)")
    parser.add_argument("--strict", action="store_true", help="fail on warnings too")
    args = parser.parse_args()

    dirs = [Path(p).resolve() for p in args.paths] or sorted(
        p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not dirs:
        print("No skills found under skills/.", file=sys.stderr)
        return 2

    listed = marketplace_skills()
    failed = False
    for d in dirs:
        rep = check_skill(d, listed)
        status = "FAIL" if rep.errors or (args.strict and rep.warnings) else "ok"
        print(f"[{status}] {rep.skill}")
        for e in rep.errors:
            print(f"   error: {e}")
        for w in rep.warnings:
            print(f"   warn:  {w}")
        failed |= status == "FAIL"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
