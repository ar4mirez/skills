#!/usr/bin/env python3
"""Scaffold the verified uv workspace from this skill's assets under a new name.

Usage:
  python3 scripts/new_project.py DEST [--name NAME] [--without cli] [--without api]

Creates DEST/ with:
  pyproject.toml (workspace root: ruff, mypy strict, pytest, coverage), .python-version,
  packages/NAME-core (typed library), packages/NAME-cli (typer CLI),
  packages/NAME-api (FastAPI + SQLAlchemy + Alembic + procrastinate), CI and release
  workflows, and, with the API, Dockerfile, config/deploy.yml, and a Kamal pre-deploy hook.

NAME defaults to DEST's directory name. It must be 2-30 characters of a-z and 0-9, starting
with a letter; it becomes the distribution prefix (NAME-core) and module prefix (NAME_core).
After scaffolding: cd DEST && uv lock && uv sync, then run the gate listed in SKILL.md.

Exit codes: 0 = created, 1 = DEST exists and is not empty, 2 = bad input.
"""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAME_RE = re.compile(r"[a-z][a-z0-9]{1,29}")

ROOT_FILES = {
    "root-pyproject.toml": "pyproject.toml",
    "python-version": ".python-version",
    "gitignore": ".gitignore",
    "github-ci.yml": ".github/workflows/ci.yml",
    "github-release.yml": ".github/workflows/release.yml",
}
CORE = {
    "core-pyproject.toml": "packages/acme-core/pyproject.toml",
    "core-init.py": "packages/acme-core/src/acme_core/__init__.py",
    "core-errors.py": "packages/acme-core/src/acme_core/errors.py",
    "core-links.py": "packages/acme-core/src/acme_core/links.py",
    "core-test_links.py": "packages/acme-core/tests/test_links.py",
}
CLI = {
    "cli-pyproject.toml": "packages/acme-cli/pyproject.toml",
    "cli-main.py": "packages/acme-cli/src/acme_cli/main.py",
    "cli-dunder-main.py": "packages/acme-cli/src/acme_cli/__main__.py",
    "cli-test_cli.py": "packages/acme-cli/tests/test_cli.py",
}
API = {
    "api-pyproject.toml": "packages/acme-api/pyproject.toml",
    "api-dunder-main.py": "packages/acme-api/src/acme_api/__main__.py",
    "api-app.py": "packages/acme-api/src/acme_api/app.py",
    "api-config.py": "packages/acme-api/src/acme_api/config.py",
    "api-db.py": "packages/acme-api/src/acme_api/db.py",
    "api-jobs.py": "packages/acme-api/src/acme_api/jobs.py",
    "api-logs.py": "packages/acme-api/src/acme_api/logs.py",
    "api-routes.py": "packages/acme-api/src/acme_api/routes.py",
    "api-store.py": "packages/acme-api/src/acme_api/store.py",
    "api-migrations-env.py": "packages/acme-api/src/acme_api/migrations/env.py",
    "api-script.py.mako": "packages/acme-api/src/acme_api/migrations/script.py.mako",
    "api-0001_create_links.py": "packages/acme-api/src/acme_api/migrations/versions/0001_create_links.py",
    "api-conftest.py": "packages/acme-api/tests/conftest.py",
    "api-test_api.py": "packages/acme-api/tests/test_api.py",
    "api-test_units.py": "packages/acme-api/tests/test_units.py",
    "Dockerfile": "Dockerfile",
    "dockerignore": ".dockerignore",
    "deploy.yml": "config/deploy.yml",
    "kamal-pre-deploy": ".kamal/hooks/pre-deploy",
}
PACKAGE_DOCS = {
    "core": "Domain rules: codes, URLs, and slugs. Pure Python, typed, no I/O.",
    "cli": "The `acme` command-line tool.",
    "api": "FastAPI + SQLAlchemy + Postgres service, with procrastinate background jobs.",
}


def rename(text: str, name: str) -> str:
    return text.replace("acme", name).replace("Acme", name.capitalize())


def drop_member(root_toml: str, member: str) -> str:
    """Remove a workspace member from the root pyproject (dev group, sources, coverage)."""
    root_toml = re.sub(rf'\n\s*"acme-{member}",', "", root_toml)
    root_toml = re.sub(rf"\nacme-{member} = \{{ workspace = true \}}", "", root_toml)
    return root_toml.replace(f', "acme_{member}"', "")


def drop_api_tooling(root_toml: str, ci: str) -> tuple[str, str]:
    """Without the API there's no pydantic (mypy plugin), no httpx, and no Postgres in CI."""
    root_toml = re.sub(r'\n\s*"httpx>=[^"]*",', "", root_toml)
    root_toml = root_toml.replace('plugins = ["pydantic.mypy"]\n', "")
    root_toml = re.sub(r"\n\[tool\.pydantic-mypy\]\n(?:[^\[\n].*\n)*", "\n", root_toml)
    ci = re.sub(r"    services:\n(?:      .*\n)+", "", ci)
    ci = re.sub(r"      TEST_DATABASE_URL: .*\n", "", ci)
    return root_toml, ci


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="new_project.py",
        description="Scaffold a uv workspace (core library, typer CLI, FastAPI service) from the skill's verified templates.",
        epilog="Exit codes: 0 = created, 1 = DEST not empty, 2 = bad input.",
    )
    parser.add_argument("dest", help="directory to create")
    parser.add_argument("--name", help="project name (default: DEST's basename)")
    parser.add_argument(
        "--without", action="append", choices=["cli", "api"], default=[], help="leave out a member (repeatable)"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2

    dest = Path(args.dest)
    name = args.name or dest.resolve().name
    if not NAME_RE.fullmatch(name):
        print(
            f"error: name {name!r} must be 2-30 chars of a-z0-9 starting with a letter (pass --name)", file=sys.stderr
        )
        return 2
    if not ASSETS.is_dir():
        print(f"error: assets directory not found at {ASSETS}", file=sys.stderr)
        return 2
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        print(f"error: {dest} exists and is not empty", file=sys.stderr)
        return 1

    plan = {**ROOT_FILES, **CORE}
    members = ["core"]
    if "cli" not in args.without:
        plan |= CLI
        members.append("cli")
    if "api" not in args.without:
        plan |= API
        members.append("api")

    sources = {asset: (ASSETS / asset).read_text(encoding="utf-8") for asset in plan}
    for member in ("cli", "api"):
        if member not in members:
            sources["root-pyproject.toml"] = drop_member(sources["root-pyproject.toml"], member)
    if "api" not in members:
        sources["root-pyproject.toml"], sources["github-ci.yml"] = drop_api_tooling(
            sources["root-pyproject.toml"], sources["github-ci.yml"]
        )
    files = {rename(target, name): rename(sources[asset], name) for asset, target in plan.items()}

    for member in members:
        pkg = f"packages/{name}-{member}"
        files[f"{pkg}/README.md"] = f"# {name}-{member}\n\n{rename(PACKAGE_DOCS[member], name)}\n"
        files[f"{pkg}/src/{name}_{member}/py.typed"] = ""
        if member != "core":
            files[f"{pkg}/src/{name}_{member}/__init__.py"] = f'"""{name}-{member}."""\n'

    for rel, content in sorted(files.items()):
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    hook = dest / ".kamal/hooks/pre-deploy"
    if hook.exists():
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"created {dest} ({', '.join(f'{name}-{m}' for m in members)})")
    print(f"next: cd {dest} && uv lock && uv sync && uv run ruff check && uv run mypy && uv run pytest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
