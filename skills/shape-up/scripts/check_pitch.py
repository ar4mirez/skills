#!/usr/bin/env python3
"""Check a Shape Up pitch (Markdown) for the five ingredients and common smells.

Usage:
  python3 scripts/check_pitch.py PITCH.md [--max-weeks 6] [--json]
  cat PITCH.md | python3 scripts/check_pitch.py -

Checks (errors fail with exit code 1; warnings are advice):
  errors   missing/empty Problem, Appetite, Solution, Rabbit holes, No-gos section;
           appetite without a time budget; appetite longer than one cycle;
           unfilled <placeholders> from the template
  warnings appetite phrased as an estimate (hours, points); solution-first problem;
           grab-bag signals (2.0, redesign, refactor); wireframe-level detail;
           open questions pushed to the team (TBD, "designer will figure out");
           rabbit holes listed without a decision; thin sections

Headings are matched case-insensitively: "Problem", "Appetite", "Solution",
"Rabbit hole(s)", and "No-go(s)" / "No gos" / "Out of bounds" / "Non-goals".
Exit codes: 0 = no errors, 1 = errors found, 2 = bad invocation / unreadable file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

INGREDIENTS = {
    "problem": re.compile(r"\bproblem\b", re.I),
    "appetite": re.compile(r"\bappetite\b", re.I),
    "solution": re.compile(r"\bsolution\b", re.I),
    "rabbit_holes": re.compile(r"rabbit[\s-]?holes?", re.I),
    "no_gos": re.compile(r"\bno[\s-]?go(e?s)?\b|out of bounds|non[\s-]?goals?", re.I),
}
LABELS = {
    "problem": "Problem",
    "appetite": "Appetite",
    "solution": "Solution",
    "rabbit_holes": "Rabbit holes",
    "no_gos": "No-gos",
}
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
DURATION_RE = re.compile(
    r"\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
    r"[\s-]*(days?|weeks?|wks?|cycles?|months?|weeker)\b", re.I)
BATCH_RE = re.compile(r"\b(small|big)[\s-]batch\b", re.I)
ESTIMATE_RE = re.compile(r"story[\s-]?points?|\bpoints?\b|\bhours?\b|\bestimat\w*|t-?shirt|velocity", re.I)
SOLUTION_FIRST_RE = re.compile(
    r"^\s*(we\s+(should|need to|want to|will|must)\s+)?(add|build|create|implement|introduce|make|support)\b", re.I)
GRAB_BAG_RE = re.compile(r"\b\d+\.0\b|\bredesign\w*|\brevamp\w*|\boverhaul\w*|\brefactor\w*|\brewrite\b", re.I)
DETAIL_RE = re.compile(
    r"#[0-9a-f]{3}(?:[0-9a-f]{3})?\b|\b\d+\s?px\b|font-size|pixel[\s-]perfect|\brgba?\(|"
    r"\bwireframes?\b|high[\s-]fidelity|\bhi-?fi\b|\bmock-?ups?\b", re.I)
OPEN_Q_RE = re.compile(
    r"\bTBD\b|\bTODO\b|\?\?+|to be decided|figure (it|this|that) out( later)?|"
    r"(designer|team|engineers?|devs?) (will|can) (figure|decide|work) (it |this |that )?out", re.I)
HEDGE_RE = re.compile(r"\b(might|may|could|possibly|unclear|unknown|risk)\b", re.I)
DECISION_RE = re.compile(
    r"patch|decid|decision|instead|→|->|we will|we'll|won't|will not|verified|confirmed|"
    r"out of bounds|no-go|keep|leave|use |by |only|never|always|cut", re.I)
PLACEHOLDER_RE = re.compile(r"<[^<>\n]{2,}>")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def split_sections(text: str) -> tuple[str, list[dict]]:
    """Return (title, sections); each section's body includes its subsections."""
    lines = text.splitlines()
    heads = []
    in_code = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        m = None if in_code else HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    title = next((h[2] for h in heads if h[1] == 1), "")
    sections = []
    for idx, (i, level, name) in enumerate(heads):
        end = len(lines)
        for j, lvl, _ in heads[idx + 1:]:
            if lvl <= level:
                end = j
                break
        sections.append({"name": name, "level": level, "body": "\n".join(lines[i + 1:end]).strip()})
    return title, sections


def words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", s))


def content_lines(body: str) -> list[str]:
    out = []
    for ln in body.splitlines():
        t = ln.strip()
        if not t or t.startswith(("#", ">", "```")):
            continue
        t = re.sub(r"^[-*+]\s+|^\d+\.\s+|^\[[ xX]\]\s+", "", t).strip()
        if t:
            out.append(t)
    return out


def to_weeks(amount: str, unit: str) -> float:
    n = float(NUM_WORDS.get(amount.lower(), amount)) if not amount.replace(".", "").isdigit() else float(amount)
    unit = unit.lower()
    if unit.startswith("day"):
        return n / 5
    if unit.startswith("cycle"):
        return n * 6
    if unit.startswith("month"):
        return n * 4.3
    return n


def check(text: str, max_weeks: float) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    title, sections = split_sections(text)

    found: dict[str, dict] = {}
    for sec in sections:
        for key, rx in INGREDIENTS.items():
            if key not in found and rx.search(sec["name"]):
                found[key] = sec
                break

    for key, label in LABELS.items():
        sec = found.get(key)
        if not sec:
            errors.append(f"Missing '{label}' section. Every pitch needs all five ingredients: "
                          "Problem, Appetite, Solution, Rabbit holes, No-gos.")
            continue
        if not content_lines(sec["body"]):
            errors.append(f"'{label}' section is empty.")

    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    if placeholders:
        shown = ", ".join(placeholders[:5]) + (" ..." if len(placeholders) > 5 else "")
        errors.append(f"Unfilled template placeholders: {shown}")

    prob = found.get("problem", {}).get("body", "")
    if prob:
        if words(prob) < 25:
            warnings.append(f"Problem is thin ({words(prob)} words). Tell one specific story that shows "
                            "the status quo failing, plus the baseline (what people do today).")
        first = content_lines(prob)[0] if content_lines(prob) else ""
        if SOLUTION_FIRST_RE.search(first):
            warnings.append("Problem opens with a solution ('add/build/implement ...'). State what's going "
                            "wrong for someone first, or there's no test for judging the solution.")

    app = found.get("appetite", {}).get("body", "")
    appetite_weeks = None
    if app:
        durations = DURATION_RE.findall(app)
        batch = BATCH_RE.search(app)
        if not durations and not batch:
            errors.append("Appetite doesn't state a time budget. Say e.g. 'Small batch: 2 weeks' or "
                          "'Big batch: 6 weeks', with the team size.")
        if durations:
            appetite_weeks = max(to_weeks(a, u) for a, u in durations)
            if appetite_weeks > max_weeks:
                errors.append(f"Appetite is about {appetite_weeks:g} weeks, which is more than one cycle "
                              f"({max_weeks:g} weeks). Narrow the problem, or carve off a meaningful piece "
                              "that fits one cycle, and bet only on that.")
        elif batch and batch.group(1).lower() == "big":
            appetite_weeks = 6.0
        if ESTIMATE_RE.search(app):
            warnings.append("Appetite reads like an estimate (hours, points, 'estimate'). An appetite is a "
                            "budget chosen up front that constrains the design, not a forecast.")
        if not re.search(r"designer|programmer|developer|engineer|team|person|people", app, re.I):
            warnings.append("Appetite doesn't mention the team size (e.g. 1 designer + 2 programmers).")

    sol = found.get("solution", {}).get("body", "")
    if sol:
        if words(sol) < 25:
            warnings.append("Solution is thin. Present the elements (a breadboard or fat-marker description) "
                            "so readers without context can 'get it'.")
        detail = sorted({m.group(0).lower() for m in DETAIL_RE.finditer(sol)})
        if detail:
            warnings.append(f"Solution has wireframe-level detail ({', '.join(detail)}). Stay at the level of "
                            "elements, and add a latitude note for designers where you sketched layout.")

    for key in ("solution", "rabbit_holes"):
        body = found.get(key, {}).get("body", "")
        hits = sorted({m.group(0) for m in OPEN_Q_RE.finditer(body)})
        if hits:
            warnings.append(f"{LABELS[key]} leaves open questions for the team ({', '.join(hits)}). "
                            "Resolve them while shaping, or declare them out of bounds.")

    rh = found.get("rabbit_holes", {}).get("body", "")
    for line in content_lines(rh):
        if HEDGE_RE.search(line) and not DECISION_RE.search(line):
            warnings.append(f"Rabbit hole listed without a decision: '{line[:80]}'. Patch it (dictate the "
                            "approach), cut it, or declare it out of bounds.")

    nogo = found.get("no_gos", {}).get("body", "")
    if found.get("no_gos") and content_lines(nogo) and all(
            re.search(r"\b(none|n/a|nothing)\b", ln, re.I) for ln in content_lines(nogo)):
        warnings.append("No-gos says 'none'. Nearly every pitch excludes something to fit the appetite, "
                        "so name what you're deliberately not doing.")

    scan = f"{title}\n{prob}"
    gb = sorted({m.group(0) for m in GRAB_BAG_RE.finditer(scan)})
    if gb:
        warnings.append(f"Grab-bag signal ({', '.join(gb)}). Make sure one specific problem drives the "
                        "project, or split it into separately shaped projects.")

    return {
        "title": title,
        "ingredients_found": {LABELS[k]: (k in found) for k in LABELS},
        "appetite_weeks": appetite_weeks,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check a Shape Up pitch for the five ingredients and common smells.",
        epilog="Examples:\n  python3 scripts/check_pitch.py pitches/autopay.md\n"
               "  python3 scripts/check_pitch.py pitch.md --json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pitch", help="path to the pitch Markdown file, or '-' for stdin")
    parser.add_argument("--max-weeks", type=float, default=6.0,
                        help="cycle length in weeks; longer appetites are errors (default: 6)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    try:
        text = sys.stdin.read() if args.pitch == "-" else open(args.pitch, encoding="utf-8").read()
    except OSError as exc:
        print(f"Error: cannot read '{args.pitch}': {exc.strerror}. Pass a Markdown file path or '-'.",
              file=sys.stderr)
        return 2

    result = check(text, args.max_weeks)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Title: {result['title'] or '(untitled)'}")
        print("Ingredients: " + ", ".join(
            f"{k} {'✓' if v else '✗'}" for k, v in result["ingredients_found"].items()))
        if result["appetite_weeks"] is not None:
            print(f"Appetite: ~{result['appetite_weeks']:g} weeks")
        for e in result["errors"]:
            print(f"ERROR: {e}")
        for w in result["warnings"]:
            print(f"WARN:  {w}")
        print("Result: " + ("OK, ready for the betting table" if result["ok"] and not result["warnings"]
                            else "OK with warnings; address or justify each" if result["ok"]
                            else f"{len(result['errors'])} error(s); not ready to bet on"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
