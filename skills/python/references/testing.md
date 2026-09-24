# Testing: pytest, fixtures, properties, async, databases, coverage

Sources: pytest 9 (https://docs.pytest.org/en/stable/ and its changelog),
Hypothesis (https://hypothesis.readthedocs.io/), AnyIO's pytest plugin
(https://anyio.readthedocs.io/en/stable/testing.html), coverage.py
(https://coverage.readthedocs.io/), and httpx
(https://www.python-httpx.org/). The configuration below is what the template
runs: 61 tests, 96% branch coverage, and a real Postgres 18.

## Contents
- Configuration (pytest 9)
- Layout and naming
- Fixtures
- Parametrization
- Property-based tests (Hypothesis)
- Async tests (AnyIO plugin)
- HTTP tests (httpx + ASGITransport)
- Database integration tests
- CLI tests
- Mocking policy
- Coverage
- Benchmarks and fuzzing

## Configuration (pytest 9)

```toml
[tool.pytest]                     # native TOML (pytest 9.0+), not [tool.pytest.ini_options]
minversion = "9.0"
strict = true                     # strict markers, config, xfail, parametrization ids
testpaths = ["packages"]
addopts = ["--import-mode=importlib", "-ra"]
filterwarnings = ["error"]        # a new DeprecationWarning fails the build now, not at upgrade time
```

- `strict = true` makes a typo'd marker or config key an error.
- `filterwarnings = ["error"]` is the zero-warning gate; allow a specific
  third-party warning with `"ignore:...:DeprecationWarning:module"` and a
  comment, never globally.
- `--import-mode=importlib` is required in a workspace with several `tests/`
  directories (`test_api.py` twice would otherwise collide). It also means
  tests can't import each other as modules; share code through fixtures in
  `conftest.py`.

## Layout and naming

- `tests/` beside `src/` in each package; mirror module names
  (`src/acme_core/links.py` → `tests/test_links.py`).
- Test names state behavior: `test_duplicate_code_conflicts`,
  `test_parse_code_rejects`.
- One behavior per test; arrange-act-assert. Use plain `assert`: pytest
  rewrites it to show values, so assertion libraries add nothing.
- Every bug fix starts with a failing test.

## Fixtures

```python
@pytest.fixture(scope="session")
def migrated(settings: Settings) -> Settings:
    ...                           # expensive: once per run

@pytest.fixture
def clean_db(migrated: Settings) -> Iterator[Settings]:
    yield migrated
    ...                           # teardown after the yield
```

- Fixtures build dependencies; tests receive them by parameter name. Prefer
  factory fixtures (return a function) over many near-identical fixtures.
- Scope expensive setup (`session`) and keep per-test state cheap
  (truncate, or roll back).
- `conftest.py` holds fixtures for its directory. Don't put helper logic in
  tests that other tests import.
- `monkeypatch` for env vars and attributes (auto-restored);
  `tmp_path` for files; `capsys` for output. Never mutate `os.environ`
  directly.
- `@functools.cache` getters (like `get_settings`) need `cache_clear()`
  around tests that change the environment.

## Parametrization

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("https://Example.COM", "https://example.com/"), ("HTTP://example.com/a?b=1#frag", "http://example.com/a?b=1")],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected
```

- A tuple of names (ruff PT006), a list of tuples (PT007).
- `pytest.param(..., id="...")` when values don't make readable ids.
- `pytest.raises(SomeError, match="...")`, plus assertions on the
  exception's attributes.
- pytest 9 adds built-in subtests for values known only at run time; still
  prefer parametrize when you know them at collection time.

## Property-based tests (Hypothesis)

Use them for invariants over a large input space: parsers, normalizers,
serializers, and anything with a round trip.

```python
@given(st.text())
def test_slugify_output_is_always_a_valid_slug(text: str) -> None:
    slug = slugify(text)
    assert slug == slug.strip("-") and len(slug) <= 32
    assert slugify(slug) == slug             # idempotent
```

- Properties to look for: round-trips (`parse(format(x)) == x`),
  idempotence, invariants (length, charset), "never raises anything but X".
- Hypothesis shrinks failures to a minimal example and stores it in
  `.hypothesis/` (gitignore it; CI starts fresh). Use settings profiles for a
  slower, more thorough CI run if needed.
- For stateful systems, `hypothesis.stateful.RuleBasedStateMachine`.

## Async tests (AnyIO plugin)

AnyIO ships with Starlette/FastAPI, so its pytest plugin costs no extra
dependency. Mark tests `@pytest.mark.anyio` (or a module-level `pytestmark`),
and pin the backend:

```python
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"          # psycopg async and procrastinate need asyncio
```

- Async fixtures work as ordinary `async def` fixtures under the plugin.
- Use **pytest-asyncio** (1.x) instead only if the project already does;
  don't install both.
- Don't call `asyncio.run` inside a test; the plugin owns the loop.

## HTTP tests (httpx + ASGITransport)

```python
@pytest.fixture
async def app(clean_db: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(clean_db)
    async with application.router.lifespan_context(application):   # ASGITransport skips lifespan
        yield application

@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

- Tests talk HTTP to the real app: routing, validation (422), error mapping
  (404/409), and serialization all get covered.
- `httpx.ASGITransport` does **not** run lifespan events; enter
  `app.router.lifespan_context(app)` yourself, or the engine on `app.state`
  won't exist.
- FastAPI's sync `TestClient` runs the lifespan with `with TestClient(app)`,
  but it runs the app on another thread's event loop, which makes shared async
  resources awkward. Use httpx for async apps.

## Database integration tests

Test against **real Postgres**, never SQLite-as-a-stand-in (different SQL,
types, constraints, and locking) and never a mocked session.

- `TEST_DATABASE_URL` points at a disposable database. Without it, tests
  skip locally and **fail when `CI` is set**, so a broken pipeline can't pass
  by skipping.
- Migrate once per session through the production code path
  (`migrate(settings)`, twice, to prove idempotence), after resetting the
  schema (`DROP SCHEMA public CASCADE`).
- Isolate tests by truncating after each one (`TRUNCATE links,
  procrastinate_jobs RESTART IDENTITY CASCADE`). Rolling back an outer
  transaction is faster, but it breaks when code under test commits or when a
  worker uses its own connection, as here.
- CI: a `postgres:18` service container (`assets/github-ci.yml`). Locally: a
  Postgres you already run, or testcontainers-python if Docker is available.
- Test the job path for real: defer via HTTP, run the worker once
  (`wait=False`), and assert the effect.

## CLI tests

- `typer.testing.CliRunner().invoke(app, [...], input=...)`; assert
  `exit_code`, `stdout`, and `stderr` separately (typer 0.27's runner keeps them apart; verified).
- Test exit codes as a contract: 0 ok, 1 findings or invalid input, 2 usage.
- One real subprocess test (`python -m acme_cli ...`) proves the entry point
  and installed metadata work; keep the rest in-process for speed.

## Mocking policy

- Don't mock what you own: pass fakes through parameters (a session, a
  clock, a sender function) instead of `mock.patch` on import paths.
- Mock at process boundaries you don't control (third-party HTTP APIs):
  `httpx.MockTransport`, or `respx` if the project uses it.
- A test that mocks the database proves nothing about SQL.
- `monkeypatch.setattr("uvicorn.run", fake)` is fine for asserting how an
  entry point wires a third-party call (see `test_units.py`).

## Coverage

```toml
[tool.coverage.run]
branch = true
patch = ["subprocess"]          # measure `python -m ...` children too (verified on coverage 7.16)
source = ["acme_core", "acme_cli", "acme_api"]

[tool.coverage.report]
show_missing = true
skip_covered = true
fail_under = 90
exclude_also = ["if TYPE_CHECKING:", "@overload", "if __name__ == .__main__.:"]
```

Run `uv run coverage run -m pytest`, then `uv run coverage combine`, then `uv
run coverage report`. `patch = ["subprocess"]` writes one data file per
process, so **combine before report**. Branch coverage catches untested
`else` paths that line coverage calls covered. The threshold is a floor that
catches regressions, not a target: 90% of meaningful tests beats 100% of
assertion-free ones. pytest-cov is optional; plain coverage does the same with
one fewer plugin.

## Benchmarks and fuzzing

- Micro-benchmarks: `python -m timeit` or `timeit.repeat` for one-off
  questions; `pytest-benchmark` when you want to track them in CI.
  Measure before and after on the same machine.
- Fuzzing: Hypothesis property tests cover most pure-Python needs; raise
  `max_examples` in a nightly profile for parsers. For C extensions or parsers
  of hostile input, use a coverage-guided fuzzer such as Atheris (libFuzzer for
  Python) in a separate job; verify it supports your Python version first.
