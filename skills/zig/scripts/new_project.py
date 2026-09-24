#!/usr/bin/env python3
"""Scaffold a Zig 0.16 project from this skill's verified templates.

Usage:
  python3 scripts/new_project.py DEST [--name NAME] [--force]

Lays the flat files in assets/ out as a working project, renames the `tally` example
to NAME (module, binaries, C symbols, header), and writes a valid build.zig.zon
fingerprint for NAME, so `zig build test` passes immediately:

  DEST/build.zig, build.zig.zon, .gitignore, Dockerfile
  DEST/src/root.zig        library module (the reusable part)
  DEST/src/main.zig        CLI
  DEST/src/server.zig      HTTP service with /up (std.http.Server)
  DEST/src/c_api.zig       C ABI exports
  DEST/include/NAME.h      C header for the static library
  DEST/examples/use_NAME.c C program linked against the library (run by `zig build test`)
  DEST/config/deploy.yml   Kamal 2
  DEST/.github/workflows/ci.yml

Delete what you don't need (for a pure library: main.zig, server.zig, c_api.zig and their
build.zig blocks, Dockerfile, deploy.yml).

Exit codes: 0 created, 1 DEST exists and is not empty (pass --force), 2 bad input.
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
import zlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TEMPLATE_NAME = "tally"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
RESERVED = {"std", "builtin", "root", "test", "c", "zig", "main", "build", "error", "type", "anytype",
            "const", "var", "fn", "pub", "return", "try", "catch", "if", "else", "while", "for", "switch",
            "struct", "enum", "union", "opaque", "defer", "errdefer", "comptime", "inline", "export", "extern"}

# asset file -> destination path (NAME is substituted)
LAYOUT = {
    "build.zig": "build.zig",
    "build.zig.zon": "build.zig.zon",
    "gitignore": ".gitignore",
    "Dockerfile": "Dockerfile",
    "root.zig": "src/root.zig",
    "main.zig": "src/main.zig",
    "server.zig": "src/server.zig",
    "c_api.zig": "src/c_api.zig",
    "tally.h": "include/NAME.h",
    "use_tally.c": "examples/use_NAME.c",
    "deploy.yml": "config/deploy.yml",
    "github-ci.yml": ".github/workflows/ci.yml",
}


def fingerprint(name: str) -> str:
    """build.zig.zon fingerprint: high 32 bits = CRC-32 of the package name, low 32 bits = random id.

    Matches what `zig build` suggests; a fingerprint whose checksum does not match the name
    is rejected ("invalid fingerprint"), which is why renaming a package means a new one.
    """
    ident = 0
    while ident in (0, 0xFFFFFFFF):
        ident = secrets.randbits(32)
    return f"0x{(zlib.crc32(name.encode()) << 32) | ident:016x}"


def render(text: str, name: str) -> str:
    text = text.replace(TEMPLATE_NAME, name).replace(TEMPLATE_NAME.upper(), name.upper())
    return re.sub(r"\.fingerprint\s*=\s*0x[0-9a-fA-F]+", f".fingerprint = {fingerprint(name)}", text)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str]) -> int:
    p = Parser(prog="new_project.py", description=__doc__.split("\n\n")[0],
               formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="Example:\n  python3 scripts/new_project.py ~/code/wordy --name wordy\n"
                      "  cd ~/code/wordy && zig build test\n\nExit codes: 0 created, 1 DEST not empty, 2 bad input.")
    p.add_argument("dest", help="directory to create")
    p.add_argument("--name", help="package/module name: lowercase identifier (default: DEST's basename)")
    p.add_argument("--force", action="store_true", help="write into a non-empty DEST, overwriting files")
    args = p.parse_args(argv)

    dest = Path(args.dest).expanduser()
    name = args.name or dest.resolve().name.replace("-", "_")
    if not NAME_RE.match(name) or name in RESERVED:
        print(f"Error: name '{name}' must match [a-z][a-z0-9_]* (max 32 chars) and not be a Zig keyword "
              "or reserved module name. Pass --name.", file=sys.stderr)
        return 2
    missing = [a for a in LAYOUT if not (ASSETS / a).is_file()]
    if missing:
        print(f"Error: skill assets missing: {', '.join(missing)}", file=sys.stderr)
        return 2
    if dest.exists() and not dest.is_dir():
        print(f"Error: '{dest}' exists and is not a directory.", file=sys.stderr)
        return 2
    if dest.is_dir() and any(dest.iterdir()) and not args.force:
        print(f"Error: '{dest}' is not empty. Pass --force to write into it.", file=sys.stderr)
        return 1

    for asset, rel in LAYOUT.items():
        out = dest / rel.replace("NAME", name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render((ASSETS / asset).read_text(encoding="utf-8"), name), encoding="utf-8")
        print(f"created {out.relative_to(dest).as_posix()}")
    print(f"\nNext: cd {dest} && zig build test && zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSafe")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
