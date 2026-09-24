#!/usr/bin/env python3
"""Scaffold a C23 + CMake project from this skill's tested assets.

Usage:
  python3 scripts/new_project.py NAME DIR [--kind lib|cli|service] [--force]

  NAME    C identifier used for the library, headers, and symbol prefix
          (lowercase: [a-z][a-z0-9_]*, max 32 chars), e.g. "ringbuf".
  DIR     target directory; must be empty or absent unless --force.
  --kind  lib      library + tests + fuzz target
          cli      lib + a command-line tool           (default)
          service  cli + an HTTP service, Dockerfile, and Kamal deploy.yml

Every "kvstore" in the templates becomes NAME ("KVSTORE" becomes NAME.upper()).
Then: cd DIR && clang-format -i $(git ls-files '*.[ch]') && cmake --workflow --preset ci

Exit codes: 0 = created, 1 = target not empty (without --force), 2 = bad input.
Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
RESERVED = {"kvstore", "test", "main", "arena", "http", "fuzz", "int", "char", "void", "static"}

# (asset, destination template, kinds that include it)
ALL = ("lib", "cli", "service")
FILES = [
    ("CMakeLists.txt", "CMakeLists.txt", ALL),
    ("CMakePresets.json", "CMakePresets.json", ALL),
    (".clang-format", ".clang-format", ALL),
    (".clang-tidy", ".clang-tidy", ALL),
    ("github-ci.yml", ".github/workflows/ci.yml", ALL),
    ("zig-toolchain.cmake", "cmake/zig-toolchain.cmake", ALL),
    ("kvstore.h", "include/{name}/{name}.h", ALL),
    ("kvstore.c", "src/{name}.c", ALL),
    ("arena.h", "src/arena.h", ALL),
    ("arena.c", "src/arena.c", ALL),
    ("test.h", "tests/test.h", ALL),
    ("test_kvstore.c", "tests/test_{name}.c", ALL),
    ("fuzz_parse.c", "fuzz/fuzz_parse.c", ALL),
    ("cli.c", "app/cli.c", ("cli", "service")),
    ("http_handler.h", "app/http_handler.h", ("service",)),
    ("http_handler.c", "app/http_handler.c", ("service",)),
    ("server.c", "app/server.c", ("service",)),
    ("test_http.c", "tests/test_http.c", ("service",)),
    ("Dockerfile", "Dockerfile", ("service",)),
    ("deploy.yml", "config/deploy.yml", ("service",)),
]
BLOCK_RE = re.compile(r"^[ \t]*# >>> (\w+)\n(.*?)^[ \t]*# <<< \1\n", re.S | re.M)
GITIGNORE = "build/\n.cache/\ncompile_commands.json\n"


def fail(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    print(f"new_project: {msg}", file=sys.stderr)
    sys.exit(code)


def strip_blocks(text: str, kind: str) -> str:
    """Keep '# >>> cli' blocks for cli/service, '# >>> service' blocks for service."""
    keep = {"lib": set(), "cli": {"cli"}, "service": {"cli", "service"}}[kind]
    return BLOCK_RE.sub(lambda m: m.group(2) if m.group(1) in keep else "", text)


def render(text: str, name: str) -> str:
    return text.replace("KVSTORE", name.upper()).replace("kvstore", name)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold a C23 + CMake project (library, CLI, or service) from tested templates.",
        epilog="Exit codes: 0 created, 1 target not empty, 2 bad input.")
    ap.add_argument("name")
    ap.add_argument("dir")
    ap.add_argument("--kind", choices=ALL, default="cli")
    ap.add_argument("--force", action="store_true", help="write into a non-empty directory")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2

    if not NAME_RE.match(args.name) or args.name in RESERVED:
        fail(f"invalid NAME {args.name!r}: use lowercase [a-z][a-z0-9_]*, max 32 chars, "
             f"not one of {sorted(RESERVED)}")
    if not ASSETS.is_dir():
        fail(f"assets directory not found at {ASSETS}")
    target = Path(args.dir)
    if target.exists() and not target.is_dir():
        fail(f"{target} exists and is not a directory")
    if target.is_dir() and any(target.iterdir()) and not args.force:
        fail(f"{target} is not empty (use --force to write anyway)", 1)

    written = []
    for asset, dest, kinds in FILES:
        if args.kind not in kinds:
            continue
        src = ASSETS / asset
        text = src.read_text(encoding="utf-8")
        if asset == "CMakeLists.txt":
            text = strip_blocks(text, args.kind)
        out = target / dest.format(name=args.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(text, args.name), encoding="utf-8")
        written.append(out.relative_to(target).as_posix())
    (target / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    written.append(".gitignore")

    print(f"created {args.kind} project '{args.name}' in {target}:")
    for w in sorted(written):
        print(f"  {w}")
    print("next: clang-format -i the sources (renaming shifts line lengths), then\n"
          "      cmake --workflow --preset ci    # configure + build + test under ASan/UBSan")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
