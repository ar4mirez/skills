# Quality gate and security

Sources: ruff rules (https://docs.astral.sh/ruff/rules/), mypy
(https://mypy.readthedocs.io/en/stable/config_file.html), ty
(https://github.com/astral-sh/ty), uv audit (https://astral.sh/blog/uv-audit),
pip-audit (https://pypi.org/project/pip-audit/), the OWASP cheat sheets
(https://cheatsheetseries.owasp.org/), and the Python security considerations
page (https://docs.python.org/3/library/security_warnings.html).

## Contents
- The gate (run in this order)
- ruff: the curated rule set, explained
- Type checking: mypy strict (and why not ty or pyright yet)
- Vulnerability scanning
- CI
- Secure coding rules
- Secrets
- Review checklist

## The gate (run in this order)

```bash
uv sync --locked                       # lock is current; env matches it
uv run ruff format --check             # formatting
uv run ruff check                      # lint (add --output-format=github in CI)
uv run mypy                            # strict types
uv run coverage run -m pytest          # tests, warnings are errors
uv run coverage combine && uv run coverage report   # branch coverage floor
uv audit --preview-features audit-command           # known vulnerabilities
uv build --all-packages --no-sources   # wheels build from metadata alone
```

Zero warnings means: no ruff findings, no mypy errors, no unused `type:
ignore`, pytest `filterwarnings = ["error"]`, and no audit findings (or
explicit `--ignore ID` entries with a reason and date).

## ruff: the curated rule set, explained

**ruff 0.16.0 (2026-07-23) changed the default rule set from 59 rules to
413** (verified with `ruff check --show-settings`). The new defaults are a
curated selection: pyflakes, most of bugbear, pyupgrade, flake8-simplify,
pylint errors and warnings, parts of async, datetime, and logging, refurb, and
more. Some opinionated pycodestyle and pyflakes rules were dropped (E402, E731,
E741, F403, and others). So:

- **Keep the defaults and add families with `extend-select`.** A `select =
  [...]` list *replaces* the defaults, which throws away the curation (and
  pre-0.16 advice that says "select E, F, I, B, ..." now gives you *fewer*
  checks than doing nothing).
- `E501` (line length) isn't in the defaults; the formatter owns line length.

The template's `extend-select`, and why each family is there:

| Family | Catches | Why add it |
|---|---|---|
| `I` | Import order (all of isort) | One obvious order; defaults include only I001 |
| `S` | bandit: eval (S307), pickle (S301), shell=True (S602/S605), SQL strings (S608), no timeout (S113), verify=False (S501), hard-coded passwords (S105/S106), yaml.load (S506), mktemp (S306), `random` for secrets (S311) | Defaults only include 3 S rules |
| `PT` | pytest style (parametrize shapes, `raises` with `match`) | Consistent tests |
| `PTH` | `os.path` → `pathlib` | One path API |
| `ARG` | Unused arguments | Dead parameters and logic slips |
| `T20` | Leftover `print` | Use logging |
| `FAST` | Non-`Annotated` dependencies (FAST002), redundant `response_model` (FAST001) | House style for routes |
| `TID` | `ban-relative-imports = "all"` | Absolute imports only |
| `DTZ`, `ASYNC` | Naive datetimes (DTZ003 `utcnow`); blocking HTTP, sleep, and open in `async def` (ASYNC210/251/230) | Complete families, not samples |
| `BLE` | `except Exception` without re-raise (BLE001) | Swallowed errors |
| `G` | f-strings in logging calls (G004) | Structured logs |
| `RUF` | Dangling tasks (RUF006), unsorted `__all__` (RUF022), unused `noqa` (RUF100) | Correctness and hygiene |
| `N`, `RET`, `C4` | Naming, return consistency, comprehensions | Readability |

Verified: the template passes this set with zero findings, and on
`evals/files/flawed_service` ruff reports 37 findings that overlap most of the
audit script's source checks. The audit adds project-level checks (lockfile,
setup.py, requires-python), Dockerfile checks, credentialed URLs,
`get_event_loop`, and missing type hints, and it runs without installing
anything.

Configuration notes:
- Per-file ignores for tests: `S101` (assert), `S105/S106` (fake passwords),
  `ARG001` (fixtures requested for side effects). Migrations: `N999` (revision
  files start with digits).
- Set `target-version` explicitly in a virtual workspace root (see Gotchas):
  UP rules, PERF203, and F821 on PEP 649 annotations all depend on it.
- `noqa` always names the code and says why: `# noqa: S104 - containers must
  listen on all interfaces`.
- Add `D` (docstrings) only for published libraries, and `ANN` only if you
  don't run a type checker (mypy strict already requires annotations).
- On an existing codebase: enable the set, run `ruff check --fix`, then
  `--add-noqa` for the remainder and burn it down, rather than disabling rules.

## Type checking: mypy strict (and why not ty or pyright yet)

**Default: mypy 2.3 with `strict = true`.**

```toml
[tool.mypy]
strict = true
python_version = "3.14"
plugins = ["pydantic.mypy"]
warn_unreachable = true
enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool", "deprecated"]
files = ["packages"]
```

Why mypy: it installs with uv like any dev dependency (no Node.js), it has
the pydantic plugin (which understands `BaseSettings()` and model `__init__`s),
and its strict mode is the most widely targeted by library stubs. mypy 2.0
made `--local-partial-types` and `--strict-bytes` the default, and supports
PEP 695, PEP 649, and t-strings. `--num-workers N` (parallel checking) is
experimental; try it on large repos.

- **pyright 1.1.414** is excellent in the editor (Pylance) and fast in CI, but
  it needs Node.js and lacks the pydantic plugin: on the template it reported
  `Argument missing for parameter "database_url"` for `Settings()`. Fine as a
  second opinion in the editor; don't run two checkers in CI.
- **ty 0.0.84 is beta.** Astral's README says it has "no stable API; breaking
  changes, including changes to diagnostics, may occur between any two
  versions." It checked the template in about 0.2 s (mypy took about 6 s cold)
  and reported only the two lines where the code intentionally violates types in
  tests (and it doesn't honor mypy's `# type: ignore[code]`). Watch it; adopt it
  when it's 1.0 and has a pydantic story.
- Stubs: `uv add --dev types-requests` and similar for untyped libraries. For
  a library without stubs, add a per-module `[[tool.mypy.overrides]]
  ignore_missing_imports = true`, not a global switch.

## Vulnerability scanning

- **`uv audit --locked`** checks `uv.lock` against OSV advisories and adverse
  project statuses (deprecated, quarantined). It's a **preview** feature in uv
  0.12: it prints an "experimental" warning unless you pass
  `--preview-features audit-command`. It exits 1 on findings (verified with
  jinja2 3.1.2: 10 advisories), supports `--output-format json|sarif`, and
  takes `--ignore ID` and `--ignore-until-fixed ID`.
- **pip-audit 2.10** is the stable alternative (`uvx pip-audit` against an
  exported requirements file or the environment) for teams that won't depend on
  a preview command.
- `UV_MALWARE_CHECK=1` (opt-in preview) makes every uv sync check OSV
  `MAL-` advisories for the resolved packages.
- Dependabot or Renovate keep `uv.lock` moving; both understand uv.
- Keep the dependency list short. Each new package is code you ship and a
  supply-chain entry point; stdlib first.

## CI

`assets/github-ci.yml`: `actions/checkout@v7`, `astral-sh/setup-uv@v10`
(reads `required-version`, caches), a Postgres 18 service, `UV_LOCKED=1` job
wide, then the gate above. `assets/github-release.yml` builds with `uv build`
and publishes via PyPI trusted publishing (details in
`references/packaging-and-deploy.md`). Lint the workflows with `actionlint`
(both pass it).

## Secure coding rules

- **Input:** validate at the boundary into typed values (pydantic models
  with `extra="forbid"`, `parse_code`, `normalize_url`). Cap sizes (URL
  length, page `limit` with `Query(le=100)`, request body size at the proxy).
- **SQL:** SQLAlchemy expressions or bound parameters only; `text()` with
  `:name` binds. Never f-strings, `%`, `+`, or `.format` into SQL. Identifiers
  (table and column names) come from an allow-list, never from input.
- **Deserialization:** JSON (or msgpack) for anything that crosses a trust
  boundary. `pickle`, `marshal`, `shelve`, `dill`, `joblib.load`, and
  `torch.load` (without `weights_only=True`) execute code. `yaml.safe_load`
  only.
- **Processes:** `subprocess.run([...], check=True, timeout=...)` with an
  argument list; never `shell=True` or `os.system` with interpolated strings.
  `shlex.quote` is a last resort, not a design.
- **Code execution:** no `eval`/`exec`; `ast.literal_eval` parses literals.
- **HTTP clients:** always a timeout; never `verify=False`. Guard
  user-supplied URLs against SSRF (resolve and reject private ranges) before
  fetching them.
- **Files:** resolve user-influenced paths and check
  `path.resolve().is_relative_to(base)`; extract archives with
  `tarfile`'s `filter="data"` (the default since 3.14).
- **Randomness:** `secrets` for tokens, codes, and passwords; `random` only
  for simulations and jitter.
- **Crypto:** use a library (`cryptography`, `argon2-cffi` for password
  hashes); never roll your own, and never MD5/SHA-1 for security.
- **Web:** CORS allow-list (not `*` with credentials); cookies `Secure`,
  `HttpOnly`, and `SameSite`; errors return generic messages, and details go to
  logs.
- **Containers:** non-root user, no compilers or package managers in the
  runtime image, read-only config via env.

## Secrets

- Only from the environment (Kamal `env.secret`, CI secrets), parsed into
  `SecretStr` fields. Never in code, `pyproject.toml`, Dockerfiles, or images.
- `.env` files are for local development only; they're gitignored and
  dockerignored. `.kamal/secrets` holds references (e.g. `$(op read ...)`),
  and it's ignored too.
- Rotate on exposure; git history is forever.

## Review checklist

Rank findings high → low, each with file:line and a concrete fix.

**High:** code execution (`eval`, pickle/yaml on untrusted data, `shell=True`);
SQL built from strings; secrets or credentialed URLs in code; TLS verification
disabled; blocking calls in `async def` on request paths; migrations that
drop or rewrite data without an expand/contract plan; shell-form Docker CMD
(no graceful shutdown).

**Medium:** bare or swallowing `except`; mutable defaults; missing timeouts;
dropped `create_task` results; `asyncio.get_event_loop()`; naive datetimes;
`random` for secrets; no lockfile, or `setup.py`/`requirements.txt` only; ORM
objects or pydantic models leaking into domain code; module-level engines or
clients; tests that mock the database; missing tests for a changed behavior;
unpinned or unlocked Docker installs.

**Low:** missing type hints; legacy typing imports; f-strings in logging;
`os.path`; `print`; missing ruff or mypy config; `[tool.pytest.ini_options]`;
full-size base images; root containers.

Run `scripts/audit.py` first for the mechanical findings; then read for what
tools can't see: layering, naming, error design, transaction boundaries, and
test quality.
