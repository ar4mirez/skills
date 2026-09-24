#!/usr/bin/env python3
"""Render a Shape Up hill chart from scope positions and flag scopes that need attention.

Usage:
  python3 scripts/hill_chart.py SNAPSHOT.json [--previous OLDER.json ...]
                                [--format text|markdown|svg] [--output FILE]
                                [--week N] [--weeks 6] [--tolerance 3]

Snapshot JSON:
  {"project": "Drafts", "date": "2026-10-09", "cycle_week": 2, "cycle_weeks": 6,
   "scopes": [{"name": "Locate", "position": 62, "note": "optional"}]}

Positions: 0 = not started, 1-49 = uphill (figuring it out), 50 = top of the hill
(now we know what to do), 51-99 = downhill (executing), 100 = done.

Flags:
  stuck       uphill/downhill scope that hasn't moved since the previous snapshot
              (a raised hand: ask what unknown is holding it, or split the scope)
  backslide   position went down (the uphill work was done in someone's head, not
              their hands, or a new unknown turned up)
  late-uphill scope still uphill in the final third of the cycle (hammer scope,
              patch the hole, or let the circuit breaker fire)
  discovered  scope that's new since the previous snapshot (normal early on)
  dropped     scope missing since the previous snapshot (split, merged, or cut?)

Exit codes: 0 = rendered (flags are advisory), 2 = invalid input.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

MARKERS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
COLORS = ["#2563eb", "#16a34a", "#ea580c", "#9333ea", "#0891b2", "#ca8a04", "#db2777", "#4f46e5"]


class InputError(Exception):
    pass


def load(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read '{path}': {exc.strerror}")
    except json.JSONDecodeError as exc:
        raise InputError(f"'{path}' is not valid JSON: {exc}")
    scopes = data.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise InputError(f"'{path}' needs a non-empty \"scopes\" list of {{\"name\", \"position\"}} objects")
    seen = set()
    for s in scopes:
        name, pos = s.get("name"), s.get("position")
        if not isinstance(name, str) or not name.strip():
            raise InputError(f"'{path}': every scope needs a non-empty \"name\"")
        if name in seen:
            raise InputError(f"'{path}': duplicate scope name '{name}'")
        seen.add(name)
        if not isinstance(pos, (int, float)) or not 0 <= pos <= 100:
            raise InputError(f"'{path}': scope '{name}' position must be a number from 0 to 100 (got {pos!r})")
    return data


def phase(pos: float) -> str:
    if pos <= 0:
        return "not started"
    if pos < 50:
        return "uphill"
    if pos == 50:
        return "top of hill"
    if pos < 100:
        return "downhill"
    return "done"


def analyze(current: dict, previous: list[dict], week: int | None, weeks: int, tol: float) -> list[dict]:
    flags = []
    prev = previous[-1] if previous else None
    prev_pos = {s["name"]: s["position"] for s in prev["scopes"]} if prev else {}
    since = prev.get("date", "the previous snapshot") if prev else None

    # A scope is "stuck" if it has sat within tolerance across every supplied snapshot.
    history = {s["name"]: [p["position"] for snap in previous for p in snap["scopes"] if p["name"] == s["name"]]
               for s in current["scopes"]}

    for s in current["scopes"]:
        name, pos = s["name"], s["position"]
        if prev is not None and name not in prev_pos:
            late = week is not None and week > 2
            flags.append({"scope": name, "flag": "discovered",
                          "message": f"'{name}' is new since {since}. " + (
                              f"Discovering a scope in week {week} can signal a hole in the shaping; "
                              "check it's a must-have before taking it on." if late else
                              "Discovering scopes is normal in weeks 1-2.")})
        elif prev is not None:
            delta = pos - prev_pos[name]
            if delta < -tol:
                flags.append({"scope": name, "flag": "backslide",
                              "message": f"'{name}' slid back {abs(delta):g} (to {pos:g}). Was the uphill work done "
                                         "in someone's head instead of with their hands? Name the new unknown."})
            elif 0 < pos < 100 and all(abs(pos - h) <= tol for h in history[name]):
                n = len(history[name])
                span = f"across {n + 1} snapshots" if n > 1 else f"since {since}"
                flags.append({"scope": name, "flag": "stuck",
                              "message": f"'{name}' hasn't moved {span} (at {pos:g}, {phase(pos)}). A dot that "
                                         "doesn't move is a raised hand: ask what unknown is holding it, or split "
                                         "the scope if its parts move at different speeds."})
        if week is not None and week >= math.ceil(weeks * 2 / 3) and pos < 50:
            flags.append({"scope": name, "flag": "late-uphill",
                          "message": f"'{name}' is still {phase(pos)} in week {week} of {weeks}. Hammer it down, "
                                     "patch the hole, or cut it. Uphill work at the deadline means no extension."})

    if prev is not None:
        current_names = {s["name"] for s in current["scopes"]}
        for name in prev_pos:
            if name not in current_names:
                flags.append({"scope": name, "flag": "dropped",
                              "message": f"'{name}' is gone since {since}. Was it split, merged, finished, or cut?"})
    return flags


def render_text(data: dict, width: int = 61, height: int = 9) -> str:
    grid = [[" "] * width for _ in range(height + 2)]
    curve_row = []
    for x in range(width):
        y = math.sin(math.pi * x / (width - 1))
        r = height - int(round(y * (height - 1)))
        curve_row.append(r)
        grid[r][x] = "·"
    top = width // 2
    grid[height + 1] = list("start".ljust(top - 2) + "top" + "done".rjust(width - top - 1))[:width]
    for i, s in enumerate(data["scopes"]):
        x = int(round(s["position"] / 100 * (width - 1)))
        r = curve_row[x] - 1
        while r > 0 and grid[r][x] not in (" ", "·"):
            r -= 1
        grid[max(r, 0)][x] = MARKERS[i % len(MARKERS)]
    lines = ["".join(row).rstrip() for row in grid]
    lines.insert(0, "  figuring it out  ↗".ljust(top) + "↘  getting it done")
    return "\n".join(lines)


def legend_rows(data: dict, previous: list[dict]) -> list[tuple]:
    prev_pos = {s["name"]: s["position"] for s in previous[-1]["scopes"]} if previous else {}
    rows = []
    for i, s in enumerate(data["scopes"]):
        d = s["position"] - prev_pos[s["name"]] if s["name"] in prev_pos else None
        rows.append((MARKERS[i % len(MARKERS)], s["name"], s["position"], phase(s["position"]),
                     "new" if previous and d is None else ("" if d is None else f"{d:+g}"), s.get("note", "")))
    return rows


def header(data: dict, week: int | None, weeks: int) -> str:
    parts = [data.get("project", "Hill chart")]
    if data.get("date"):
        parts.append(data["date"])
    if week is not None:
        parts.append(f"week {week} of {weeks}")
    return " · ".join(parts)


def render_svg(data: dict, flags: list[dict]) -> str:
    scopes = data["scopes"]
    w, pad = 640, 40
    top_margin, amp = 70, 130
    base = top_margin + amp
    legend_top = base + 50
    h = legend_top + 22 * len(scopes) + 16

    def pt(pos: float) -> tuple[float, float]:
        x = pad + pos / 100 * (w - 2 * pad)
        return x, base - math.sin(math.pi * pos / 100) * amp

    path = " ".join(("M" if i == 0 else "L") + f"{pt(i)[0]:.1f},{pt(i)[1]:.1f}" for i in range(0, 101))
    flagged = {f["scope"] for f in flags if f["flag"] in ("stuck", "backslide", "late-uphill")}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="system-ui, sans-serif">',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
           f'<text x="{pad}" y="30" font-size="15" font-weight="600" fill="#111827">'
           f'{_esc(data.get("project", "Hill chart"))}'
           f'<tspan fill="#6b7280" font-weight="400"> {_esc(data.get("date", ""))}</tspan></text>',
           f'<path d="{path}" fill="none" stroke="#9ca3af" stroke-width="2"/>',
           f'<line x1="{w / 2}" y1="{base - amp - 6}" x2="{w / 2}" y2="{base + 8}" stroke="#d1d5db" '
           f'stroke-dasharray="4 4"/>',
           f'<text x="{w / 4}" y="{base + 26}" font-size="12" fill="#6b7280" text-anchor="middle">'
           'Figuring things out</text>',
           f'<text x="{3 * w / 4}" y="{base + 26}" font-size="12" fill="#6b7280" text-anchor="middle">'
           'Making it happen</text>']
    stacked: dict[int, int] = {}
    for i, s in enumerate(scopes):
        x, y = pt(s["position"])
        k = stacked.get(round(s["position"] / 3), 0)  # lift dots that would overlap
        stacked[round(s["position"] / 3)] = k + 1
        y -= k * 20
        color = COLORS[i % len(COLORS)]
        ring = (' stroke="#111827" stroke-width="2" stroke-dasharray="3 2"' if s["name"] in flagged
                else ' stroke="#ffffff" stroke-width="2"')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{color}"{ring}/>')
        out.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" font-size="11" font-weight="700" fill="#ffffff" '
                   f'text-anchor="middle">{MARKERS[i % len(MARKERS)]}</text>')
        ly = legend_top + 22 * i
        out.append(f'<circle cx="{pad + 8}" cy="{ly - 4}" r="7" fill="{color}"/>')
        out.append(f'<text x="{pad + 8}" y="{ly - 0.5}" font-size="9" font-weight="700" fill="#ffffff" '
                   f'text-anchor="middle">{MARKERS[i % len(MARKERS)]}</text>')
        tag = "  ⚑ needs attention" if s["name"] in flagged else ""
        out.append(f'<text x="{pad + 24}" y="{ly}" font-size="13" fill="#111827">{_esc(s["name"])}'
                   f'<tspan fill="#6b7280"> · {s["position"]:g} · {phase(s["position"])}{tag}</tspan></text>')
    out.append("</svg>")
    return "\n".join(out)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a Shape Up hill chart and flag stuck, backsliding, or late-uphill scopes.",
        epilog="Examples:\n"
               "  python3 scripts/hill_chart.py assets/hill-snapshot.json\n"
               "  python3 scripts/hill_chart.py week3.json --previous week2.json --format markdown\n"
               "  python3 scripts/hill_chart.py week5.json --previous week4.json --format svg -o hill.svg",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", help="current snapshot JSON")
    parser.add_argument("--previous", action="append", default=[], metavar="FILE",
                        help="earlier snapshot(s), oldest first; repeat to pass several")
    parser.add_argument("--format", choices=["text", "markdown", "svg"], default="text")
    parser.add_argument("-o", "--output", help="write the chart to FILE instead of stdout")
    parser.add_argument("--week", type=int, help="current cycle week (overrides snapshot cycle_week)")
    parser.add_argument("--weeks", type=int, help="cycle length in weeks (default: snapshot cycle_weeks or 6)")
    parser.add_argument("--tolerance", type=float, default=3,
                        help="movement at or below this counts as 'not moved' (default: 3)")
    args = parser.parse_args()

    try:
        current = load(args.snapshot)
        previous = [load(p) for p in args.previous]
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    weeks = args.weeks or int(current.get("cycle_weeks", 6))
    week = args.week if args.week is not None else current.get("cycle_week")
    flags = analyze(current, previous, week, weeks, args.tolerance)

    if args.format == "svg":
        body = render_svg(current, flags)
    else:
        chart = render_text(current)
        rows = legend_rows(current, previous)
        if args.format == "markdown":
            lines = [f"### Hill chart: {header(current, week, weeks)}", "", "```", chart, "```", "",
                     "| # | Scope | Position | Phase | Δ | Note |", "|---|---|---|---|---|---|"]
            lines += [f"| {m} | {n} | {p:g} | {ph} | {d} | {note} |" for m, n, p, ph, d, note in rows]
            if flags:
                lines += ["", "**Needs attention**", ""] + [f"- **{f['flag']}**: {f['message']}" for f in flags]
        else:
            lines = [header(current, week, weeks), "", chart, ""]
            lines += [f"  {m}  {n:<24} {p:>5g}  {ph:<12} {d:>4}  {note}" for m, n, p, ph, d, note in rows]
            if flags:
                lines += ["", "Needs attention:"] + [f"  [{f['flag']}] {f['message']}" for f in flags]
        body = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(body + "\n", encoding="utf-8")
        print(f"Wrote {args.format} hill chart to {args.output}" + (f" ({len(flags)} flag(s))" if flags else ""))
        for f in flags:
            print(f"  [{f['flag']}] {f['message']}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
