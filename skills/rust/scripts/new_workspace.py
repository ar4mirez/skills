#!/usr/bin/env python3
"""Scaffold a Cargo workspace (library + CLI + axum service) from this skill's assets.

Usage:
  python3 scripts/new_workspace.py DEST [--name NAME] [--without api|cli] [--force]

Creates DEST with the verified layout:
  Cargo.toml, rust-toolchain.toml, rustfmt.toml, clippy.toml, deny.toml, .gitignore
  crates/NAME-core   library: typed errors, newtypes, unit + property tests, doc-tests, a bench
  crates/NAME-cli    clap binary `NAME` with in-process and end-to-end tests
  crates/NAME-api    axum + sqlx (Postgres) service with migrations, config, graceful shutdown
  Dockerfile, .dockerignore, config/deploy.yml (Kamal 2), .github/workflows/ci.yml
Every occurrence of `acme` in the templates becomes NAME (default: DEST's directory name).
Runs `cargo fmt --all` afterwards when cargo is on PATH (renaming reorders imports).

`--without api` drops the service (and its Dockerfile/deploy files); `--without cli` drops the CLI.

Exit codes: 0 = created, 1 = DEST exists and is not empty (use --force), 2 = bad input.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

COMMON = {
    "workspace-Cargo.toml": "Cargo.toml",
    "rust-toolchain.toml": "rust-toolchain.toml",
    "rustfmt.toml": "rustfmt.toml",
    "clippy.toml": "clippy.toml",
    "deny.toml": "deny.toml",
    "gitignore": ".gitignore",
    "github-ci.yml": ".github/workflows/ci.yml",
    "core-Cargo.toml": "crates/{n}-core/Cargo.toml",
    "core-lib.rs": "crates/{n}-core/src/lib.rs",
    "core-error.rs": "crates/{n}-core/src/error.rs",
    "core-slug.rs": "crates/{n}-core/src/slug.rs",
    "core-code.rs": "crates/{n}-core/src/code.rs",
    "core-properties.rs": "crates/{n}-core/tests/properties.rs",
    "core-bench.rs": "crates/{n}-core/benches/codec.rs",
}
CLI = {
    "cli-Cargo.toml": "crates/{n}-cli/Cargo.toml",
    "cli-main.rs": "crates/{n}-cli/src/main.rs",
    "cli-test.rs": "crates/{n}-cli/tests/cli.rs",
}
API = {
    "api-Cargo.toml": "crates/{n}-api/Cargo.toml",
    "api-lib.rs": "crates/{n}-api/src/lib.rs",
    "api-config.rs": "crates/{n}-api/src/config.rs",
    "api-error.rs": "crates/{n}-api/src/error.rs",
    "api-links.rs": "crates/{n}-api/src/links.rs",
    "api-main.rs": "crates/{n}-api/src/main.rs",
    "api-test.rs": "crates/{n}-api/tests/api.rs",
    "api-migration.sql": "crates/{n}-api/migrations/20260901000000_create_links.sql",
    "Dockerfile": "Dockerfile",
    "dockerignore": ".dockerignore",
    "deploy.yml": "config/deploy.yml",
}


def rename(text: str, name: str) -> str:
    snake = name.replace("-", "_")
    title = "".join(part.capitalize() for part in name.split("-"))
    text = text.replace("acme_", f"{snake}_").replace("Acme", title)
    return re.sub(r"acme", name, text)


def strip_api_from_ci(text: str) -> str:
    """Without a service there is no database: drop the Postgres service and sqlx steps."""
    text = re.sub(r"    services:\n(?:      .*\n|        .*\n)+", "", text)
    text = re.sub(r"    env:\n      DATABASE_URL: .*\n", "", text)
    text = re.sub(r"  SQLX_OFFLINE: .*\n", "", text)
    return "".join(ln for ln in text.splitlines(keepends=True) if "sqlx" not in ln)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="new_workspace.py",
        description="Scaffold a Cargo workspace (library + CLI + axum service) from the skill's verified assets.",
        epilog="Exit codes: 0 created, 1 destination not empty (use --force), 2 bad input.",
    )
    parser.add_argument("dest", help="directory to create")
    parser.add_argument("--name", help="crate prefix and binary name, lowercase-hyphenated (default: DEST's name)")
    parser.add_argument("--without", action="append", choices=["api", "cli"], default=[], help="omit a crate")
    parser.add_argument("--force", action="store_true", help="write into a non-empty directory")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2

    dest = Path(args.dest).resolve()
    name = args.name or dest.name
    if not NAME_RE.match(name):
        print(f"error: name {name!r} must be lowercase letters, digits, and single hyphens, starting with a letter", file=sys.stderr)
        return 2
    if not ASSETS.is_dir():
        print(f"error: assets directory not found at {ASSETS}", file=sys.stderr)
        return 2
    if dest.exists() and any(dest.iterdir()) and not args.force:
        print(f"error: {dest} exists and is not empty (pass --force to write into it)", file=sys.stderr)
        return 1

    plan = dict(COMMON)
    if "cli" not in args.without:
        plan.update(CLI)
    if "api" not in args.without:
        plan.update(API)

    for src, target in plan.items():
        text = (ASSETS / src).read_text(encoding="utf-8")
        if src == "github-ci.yml" and "api" in args.without:
            text = strip_api_from_ci(text)
        out = dest / target.format(n=name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rename(text, name), encoding="utf-8")
        print(f"  created {out.relative_to(dest)}")

    # Renaming changes import order; let rustfmt restore canonical formatting.
    if shutil.which("cargo"):
        res = subprocess.run(["cargo", "fmt", "--all"], cwd=dest, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"warning: cargo fmt failed; run it yourself:\n{res.stderr}", file=sys.stderr)
    else:
        print("note: cargo not found; run `cargo fmt --all` once the toolchain is installed.")

    print(f"\nWorkspace {name!r} created in {dest}. Next:")
    print(f"  cd {dest}")
    if "api" not in args.without:
        print("  export DATABASE_URL=postgres://postgres@localhost:5432/" + name.replace("-", "_"))
        print("  cargo install sqlx-cli --locked --no-default-features --features rustls,postgres")
        print(f"  cargo sqlx database create && cargo sqlx migrate run --source crates/{name}-api/migrations")
        print("  cargo sqlx prepare --workspace     # writes .sqlx/ (commit it)")
    print("  cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
