#!/usr/bin/env python3
"""Scaffold a C++23 / CMake / vcpkg project from this skill's verified assets.

Usage:
  python3 scripts/new_project.py NAME [--dir DEST] [--no-service] [--force]

Creates DEST/NAME (default DEST: .) with the layout below, renaming the example
namespace/targets/options from `acme` to NAME:

  CMakeLists.txt  CMakePresets.json  vcpkg.json  .clang-format  .clang-tidy
  cmake/ProjectOptions.cmake
  libs/wordcount/{CMakeLists.txt, include/NAME/wordcount/*.hpp, src/wordcount.cpp}
  apps/wc/{CMakeLists.txt, main.cpp}
  apps/wc-server/{CMakeLists.txt, main.cpp}      (omitted with --no-service)
  tests/  fuzz/  bench/
  .github/workflows/ci.yml  Dockerfile  .dockerignore  config/deploy.yml (service only)

NAME must be a lowercase C++ identifier: [a-z][a-z0-9]*(_[a-z0-9]+)*.
Exit codes: 0 = created, 1 = destination exists (use --force), 2 = bad input.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# asset file -> destination (NAME is substituted into paths)
LAYOUT = {
    "root-CMakeLists.txt": "CMakeLists.txt",
    "CMakePresets.json": "CMakePresets.json",
    "vcpkg.json": "vcpkg.json",
    "clang-format.yaml": ".clang-format",
    "clang-tidy.yaml": ".clang-tidy",
    "ProjectOptions.cmake": "cmake/ProjectOptions.cmake",
    "lib-CMakeLists.txt": "libs/wordcount/CMakeLists.txt",
    "wordcount.hpp": "libs/wordcount/include/{name}/wordcount/wordcount.hpp",
    "thread_pool.hpp": "libs/wordcount/include/{name}/wordcount/thread_pool.hpp",
    "wordcount.cpp": "libs/wordcount/src/wordcount.cpp",
    "cli-CMakeLists.txt": "apps/wc/CMakeLists.txt",
    "cli-main.cpp": "apps/wc/main.cpp",
    "tests-CMakeLists.txt": "tests/CMakeLists.txt",
    "wordcount_test.cpp": "tests/wordcount_test.cpp",
    "thread_pool_test.cpp": "tests/thread_pool_test.cpp",
    "fuzz-CMakeLists.txt": "fuzz/CMakeLists.txt",
    "wordcount_fuzz.cpp": "fuzz/wordcount_fuzz.cpp",
    "bench-CMakeLists.txt": "bench/CMakeLists.txt",
    "wordcount_bench.cpp": "bench/wordcount_bench.cpp",
    "github-ci.yml": ".github/workflows/ci.yml",
    "Dockerfile": "Dockerfile",
    "dockerignore": ".dockerignore",
}
SERVICE = {
    "service-CMakeLists.txt": "apps/wc-server/CMakeLists.txt",
    "service-main.cpp": "apps/wc-server/main.cpp",
    "deploy.yml": "config/deploy.yml",
}


def rename(text: str, name: str) -> str:
    text = text.replace("acme-wc", name.replace("_", "-") + "-wc")
    text = text.replace("ACME_", name.upper() + "_")
    text = re.sub(r"\bacme(?=[_:/.\s\"'>)-]|Targets|Config|$)", name, text, flags=re.M)
    return text


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="new_project.py",
        description="Scaffold a C++23/CMake/vcpkg project (library + CLI + optional HTTP service + tests).",
        epilog="Example:\n  python3 scripts/new_project.py inventory --dir ~/code",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="project name, a lowercase C++ identifier (e.g. inventory)")
    parser.add_argument("--dir", default=".", help="parent directory (default: .)")
    parser.add_argument("--no-service", action="store_true", help="omit the HTTP service, its Kamal config, and cpp-httplib")
    parser.add_argument("--force", action="store_true", help="write into an existing directory")
    args = parser.parse_args(argv)

    if not NAME_RE.match(args.name):
        print(f"new_project.py: invalid name '{args.name}' (want [a-z][a-z0-9]*(_[a-z0-9]+)*)", file=sys.stderr)
        return 2
    parent = Path(args.dir).expanduser()
    if not parent.is_dir():
        print(f"new_project.py: not a directory: {args.dir}", file=sys.stderr)
        return 2
    dest = parent / args.name
    if dest.exists() and not args.force:
        print(f"new_project.py: {dest} exists (use --force to overwrite)", file=sys.stderr)
        return 1

    layout = dict(LAYOUT)
    if not args.no_service:
        layout.update(SERVICE)
    for asset, target in layout.items():
        src = ASSETS / asset
        if not src.exists():
            print(f"new_project.py: missing asset {asset}", file=sys.stderr)
            return 2
        text = rename(src.read_text(), args.name)
        if args.no_service:
            text = strip_service(asset, text)
        out = dest / target.format(name=args.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"created {out}")
    print(f"\nnext: cd {dest} && cmake --workflow --preset asan   (needs VCPKG_ROOT, Ninja, CMake 3.28+)")
    return 0


def strip_service(asset: str, text: str) -> str:
    """Remove the service and its HTTP dependency when --no-service is used."""
    if asset == "root-CMakeLists.txt":
        text = re.sub(r"option\([A-Z_]+_BUILD_SERVER [^\n]*\n", "", text)
        text = re.sub(r"if\([A-Z_]+_BUILD_SERVER\)\n  add_subdirectory\(apps/wc-server\)\nendif\(\)\n", "", text)
    elif asset == "vcpkg.json":
        text = re.sub(r'\s*\{\s*"name": "cpp-httplib",\s*"default-features": false\s*\},', "", text)
    elif asset == "Dockerfile":
        text = text.replace("wc-server", "wc").replace("_wc_server", "_wc")
        text = re.sub(r"ENV PORT=8080\nEXPOSE 8080\n", "", text)
    return text


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
