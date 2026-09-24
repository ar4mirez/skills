# Toolchain, versions, and project layout

Versions were verified on 2026-09-24 against python.org
(https://www.python.org/downloads/), the What's New pages
(https://docs.python.org/3.14/whatsnew/3.14.html,
https://docs.python.org/3.15/whatsnew/3.15.html), the uv docs
(https://docs.astral.sh/uv/), and PyPI. In an existing repo, `uv.lock` and
`.python-version` win; for new code, take the latest patch of these.

## Contents
- Current versions
- Python release status and what's new (3.13 to 3.15)
- uv: the one tool
- pyproject.toml essentials
- Layout: library, CLI, service, workspace
- Workspaces: when, and the gotchas
- Asset-to-path map
- Migrating a legacy project

## Current versions

| Component | Version | Notes |
|---|---|---|
| CPython | **3.14.7** (2026-08-05) | Bugfix branch until 2030-10. 3.15.0 is in RC (GA planned 2026-10-01) |
| uv / uv_build | **0.12.18** | Python installs, venvs, lock, sync, build, publish, tools, audit (preview) |
| ruff | 0.16.8 | Linter + formatter (replaces flake8, isort, black, pyupgrade, bandit subset) |
| mypy | **2.3.1** | Default type checker (`strict = true` + pydantic plugin) |
| pyright / ty | 1.1.414 / 0.0.84 | pyright for editors; ty is beta (0.0.x, breaking changes between any versions) |
| pytest | **9.1.1** | Native `[tool.pytest]` TOML config and `strict = true` since 9.0 |
| coverage | 7.16.1 | `branch = true`; `patch = ["subprocess"]` measures child processes |
| hypothesis | 6.168.1 | Property-based tests |
| FastAPI / pydantic / pydantic-settings | 0.141.1 / 2.13.5 / 2.15.0 | |
| uvicorn | 0.53.0 | `--workers` supervises processes itself; reads `WEB_CONCURRENCY` |
| SQLAlchemy / Alembic | **2.0.54** / 1.20.0 | 2.1.0 was released 2026-09-24 (see Gotchas); Alembic reads `[tool.alembic]` from pyproject |
| psycopg | 3.3.6 | `psycopg[binary,pool]` wheels bundle libpq |
| procrastinate | 3.10.0 | Postgres-backed jobs; Python 3.10+, Postgres 13+ |
| typer | 0.27.2 | Vendors its own Click (`typer._click`); no separate click dependency |
| structlog / Litestar | 26.1.0 / 2.24.0 | Alternatives, not defaults |
| pip-audit | 2.10.1 | Fallback when `uv audit` (preview) isn't acceptable |
| py-spy / scalene / memray / pyinstrument | 0.4.2 / 2.3.0 / 1.20.0 / 5.1.3 | py-spy 0.4.2 added 3.14 support |

## Python release status and what's new

Status table (python.org, 2026-09): 3.15 pre-release, 3.14 and 3.13 bugfix,
3.12 to 3.10 security-only (3.10 ends 2026-10), 3.9 end-of-life. **Target
3.14** for new code: `requires-python = ">=3.14"` for apps. Libraries support
the oldest non-EOL version they can test (usually `>=3.11` or `>=3.12`).

**3.14 (Oct 2025), the one that matters:**
- **PEP 649/749 deferred annotations.** Annotations are evaluated lazily, so
  forward references need no quotes and `from __future__ import annotations`
  is unnecessary. Inspect them with `annotationlib.get_annotations(obj,
  format=Format.FORWARDREF)`; don't read `__annotations__` directly.
- **PEP 750 template strings.** `t"..."` builds a
  `string.templatelib.Template` (static parts + `Interpolation`s), not a `str`.
  Libraries can escape interpolations (SQL, HTML, shell). Adopt when your
  library accepts templates; don't hand-roll a template engine around them.
- **PEP 758:** `except A, B:` without parentheses (only without `as`). ruff
  format rewrites to it when `target-version = "py314"`, which makes the file
  a syntax error on 3.13 and older.
- **PEP 765:** `return`/`break`/`continue` leaving a `finally` block is a
  `SyntaxWarning`.
- **PEP 779:** the free-threaded build is officially supported (still not the
  default). See `references/concurrency.md`.
- **PEP 734:** `concurrent.interpreters` and
  `concurrent.futures.InterpreterPoolExecutor` (subinterpreters in the stdlib).
- **PEP 784:** `compression.zstd`. **PEP 768:** `sys.remote_exec` and
  `python -m pdb -p PID`. `python -m asyncio ps PID` / `pstree PID` inspect
  running tasks.
- `pathlib.Path.copy()/move()`, `Path.info`; `map(strict=True)`;
  multiprocessing's default start method on Linux is now **forkserver**.
- `asyncio.get_event_loop()` raises `RuntimeError` when there's no current
  loop; asyncio policy APIs are deprecated. Use `asyncio.run()` and
  `asyncio.get_running_loop()`.
- The incremental GC shipped in 3.14.0 was reverted in 3.14.5 (memory
  pressure). Don't cite it as a 3.14 feature.

**3.13:** the improved REPL, experimental free-threaded and JIT builds,
`copy.replace()`, `warnings.deprecated` (PEP 702), and removal of the "dead
batteries" (`cgi`, `crypt`, `telnetlib`, and others; PEP 594).

**3.15 (RC now; GA planned 2026-10-01), plan for it, don't target it yet:**
`lazy import` (PEP 810), `frozendict` (PEP 814), a `sentinel` builtin (PEP
661), `[*x for x in xs]` unpacking in comprehensions (PEP 798), **UTF-8 as the
default I/O encoding** (PEP 686), the `profiling` package with a sampling
profiler (PEP 799; `profile` is deprecated), and frame pointers on by default.
Code that opens text files without `encoding=` changes behavior on Windows.

## uv: the one tool

uv replaces pyenv, virtualenv, pip, pip-tools, pipx, poetry, twine, and build.
One binary, one lockfile.

| Task | Command |
|---|---|
| Pin Python | `uv python pin 3.14` (writes `.python-version`; uv downloads it if missing) |
| New app / lib / packaged app | `uv init app`, `uv init --lib name`, `uv init --package name` |
| Add deps | `uv add fastapi`, `uv add --dev pytest`, `uv add --group lint ruff` |
| Lock / sync | `uv lock`, `uv sync` (`--locked` asserts the lock is current; `--frozen` doesn't check) |
| Run | `uv run pytest` (syncs first), `uv run --package acme-api alembic ...` |
| One-off tools | `uvx ruff@0.16.8 check` / `uv tool install ruff` |
| Scripts | PEP 723 inline metadata: `uv add --script tool.py httpx`, `uv run tool.py` |
| Upgrade | `uv lock --upgrade` or `--upgrade-package sqlalchemy` |
| Version bump | `uv version --bump minor` |
| Build / publish | `uv build --no-sources`, `uv publish` (trusted publishing in CI) |
| Vulnerabilities | `uv audit --locked` (preview: add `--preview-features audit-command`; exits 1 on findings) |
| requirements.txt | `uv export --format requirements-txt` only for tools that demand it |

Commit `pyproject.toml`, `uv.lock`, and `.python-version`. Never commit
`.venv/`. Set `[tool.uv] required-version = ">=0.12"` so old uv versions fail
clearly; the setup-uv GitHub Action reads it.

## pyproject.toml essentials

- PEP 621 `[project]`: `name`, `version`, `requires-python`, `dependencies`
  with **lower bounds only** (`>=`); the lock pins exact versions. Add an upper
  bound only for a known break, with a comment and a date (the template caps
  SQLAlchemy `<2.1` this way).
- `license = "MIT"` (a PEP 639 SPDX expression, not a table).
- `[build-system] requires = ["uv_build>=0.12.18,<0.13"]`, the uv default,
  pure-Python only. Use `hatchling` for compiled extensions or custom build
  hooks (`maturin` for Rust extensions).
- `[dependency-groups] dev = [...]` (PEP 735) for tools; `uv sync` installs
  `dev` by default, and `--no-dev` / `UV_NO_DEV=1` leaves it out.
- `[project.scripts] acme = "acme_cli.main:app"` for console entry points.
- Tool config lives in the same file: `[tool.ruff]`, `[tool.mypy]`,
  `[tool.pytest]`, `[tool.coverage.*]`, `[tool.alembic]`.

## Layout: library, CLI, service, workspace

Always the **src layout** (`src/<pkg>/`): tests then import the installed
package, not the working directory, so packaging mistakes (a missing file, a
wrong module name) fail in CI instead of for users. Tests live in a top-level
`tests/` next to `src/`, not inside the package.

**(a) Library**, `uv init --lib acme-core`:
```
acme-core/
  pyproject.toml  README.md  uv.lock  .python-version
  src/acme_core/__init__.py   # the public API: re-exports + __all__
  src/acme_core/py.typed      # PEP 561: ship your type hints
  src/acme_core/errors.py  links.py
  tests/test_links.py
```

**(b) CLI**, `uv init --package acme-cli`: same shape plus
`[project.scripts]`, a `main.py` with the typer app, and `__main__.py` so
`python -m acme_cli` works. Logic lives in a library module, not in commands.

**(c) Service**: package per domain once it grows (`links/`, `accounts/`,
each with `routes.py`, `store.py`, `models.py`), plus shared `config.py`,
`db.py`, `logs.py`, `app.py` (the factory) and `__main__.py` (serve, migrate,
worker). Migrations ship *inside* the package so the wheel carries them.

**(d) Multi-package**: a uv workspace (below), `packages/<name>/` each with
its own src layout and tests, one root `uv.lock` and one `.venv`.

Package naming: modules are named for what they provide (`links`, `store`,
`config`); never `utils`, `helpers`, `common`, or `misc`. The distribution
name uses hyphens (`acme-core`), the import name underscores (`acme_core`).

## Workspaces: when, and the gotchas

Use a workspace when several packages are developed together and at least one
is consumed separately (a library you publish, a CLI you ship apart from the
service). One package with subpackages is simpler otherwise. The workspace
root can be **virtual** (no `[project]`) and hold only the member list, the
dev group, and tool config.

```toml
[tool.uv.workspace]
members = ["packages/*"]
[tool.uv.sources]
acme-core = { workspace = true }   # members depend on each other by name
```

- Members declare `acme-core = { workspace = true }` in their own
  `[tool.uv.sources]` too; build with `uv build --no-sources` to prove the
  wheel's metadata works without the workspace.
- ruff can't infer `target-version` from a virtual root; set
  `target-version = "py314"` and `src = ["packages/*/src"]` (first-party
  detection for isort), or ruff reports F821 on PEP 649 forward references and
  mis-sorts imports.
- pytest with several `tests/` directories needs
  `--import-mode=importlib`, or identically named test files collide.
- Docker: install dependencies with `uv sync --frozen --no-install-workspace
  --package <svc>` from only the root `pyproject.toml` + `uv.lock`, then copy
  the source and `uv sync --locked --no-editable --package <svc>`.

## Asset-to-path map

`scripts/new_project.py DEST` performs this mapping (and renames `acme`):

| Asset | Path |
|---|---|
| `root-pyproject.toml`, `python-version`, `gitignore` | `pyproject.toml`, `.python-version`, `.gitignore` |
| `github-ci.yml`, `github-release.yml` | `.github/workflows/ci.yml`, `release.yml` |
| `core-*.py`, `core-pyproject.toml` | `packages/acme-core/{pyproject.toml, src/acme_core/, tests/}` |
| `cli-*.py`, `cli-pyproject.toml` | `packages/acme-cli/...` (`cli-dunder-main.py` is `__main__.py`) |
| `api-*.py`, `api-script.py.mako`, `api-pyproject.toml` | `packages/acme-api/...`; `api-migrations-env.py` and `api-0001_create_links.py` go under `src/acme_api/migrations/` |
| `Dockerfile`, `dockerignore`, `deploy.yml`, `kamal-pre-deploy` | `Dockerfile`, `.dockerignore`, `config/deploy.yml`, `.kamal/hooks/pre-deploy` |

## Migrating a legacy project

1. `uv init --bare` (or write `[project]` by hand) and move metadata out of
   `setup.py`/`setup.cfg`. Delete `setup.py` unless it runs custom build code.
2. `uv add -r requirements.txt` imports the requirements; then delete
   the file (export it only if a platform needs it).
3. Move code under `src/`, add `py.typed`, run `uv lock`, and commit the lock.
4. Add ruff (fix the easy rules first), then mypy strict per package with
   `[[tool.mypy.overrides]]` exceptions that shrink over time.
