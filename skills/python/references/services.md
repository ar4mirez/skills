# Services: FastAPI, pydantic, SQLAlchemy, Alembic, jobs, and serving

Sources: FastAPI (https://fastapi.tiangolo.com/), pydantic
(https://docs.pydantic.dev/), pydantic-settings
(https://docs.pydantic.dev/latest/concepts/pydantic_settings/), SQLAlchemy 2.0
asyncio (https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
Alembic (https://alembic.sqlalchemy.org/), psycopg 3
(https://www.psycopg.org/psycopg3/docs/), procrastinate
(https://procrastinate.readthedocs.io/), and uvicorn
(https://www.uvicorn.org/settings/). Everything here runs in the `acme-api`
template, verified against Postgres 18.

## Contents
- The shape
- App factory and lifespan
- Routes: translate only
- Validation with pydantic v2
- Settings
- SQLAlchemy 2.0 (async, typed)
- Alembic migrations
- Background jobs: procrastinate on Postgres
- Serving: uvicorn, workers, proxies, shutdown
- Health, logging, and errors
- Alternatives and when

## The shape

```
src/acme_api/
  __main__.py   serve | migrate | worker (argparse): one entry point for the image
  app.py        create_app(settings) -> FastAPI: lifespan, /up, error mapping
  config.py     Settings(BaseSettings), get_settings() cached
  db.py         DeclarativeBase models, make_engine(), make_sessions()
  store.py      queries: session in, domain objects out, driver errors translated
  routes.py     APIRouter: request/response models, dependencies
  jobs.py       procrastinate App + tasks, open_jobs()
  logs.py       JSON formatter + dictConfig
  migrations/   env.py, script.py.mako, versions/ (ships inside the wheel)
```

Dependencies point inward: routes → store → db; everything → `acme_core`.
`acme_core` imports nothing from the service.

## App factory and lifespan

`create_app(settings: Settings | None = None) -> FastAPI` builds the app;
uvicorn calls it with `--factory` (or `factory=True`), and tests call it with
test settings. Resources are created in the **lifespan** and stored on
`app.state`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(settings)
    app.state.engine = engine
    app.state.sessions = make_sessions(engine)
    try:
        async with open_jobs(settings.libpq_url):
            yield
    finally:
        await engine.dispose()
```

No module-level engine or client: those make import order matter and tests
share state. Don't use the deprecated `@app.on_event("startup")`.

## Routes: translate only

Handlers parse input, call the store (or a service function), and shape the
output. Business rules live in `acme_core`.

```python
Session = Annotated[AsyncSession, Depends(get_session)]
PathCode = Annotated[Code, AfterValidator(parse_code)]

@router.get("/links/{code}")
async def get_link(code: PathCode, session: Session) -> LinkOut:
    return LinkOut.of(await store.get_link(session, code))
```

- `Annotated[...]` dependencies (ruff's FAST002 enforces it); reuse aliases
  like `Session`.
- Return annotations *are* the response model; don't repeat
  `response_model=` (FAST001).
- Map domain errors to status codes once, in an exception handler (`match
  exc: case NotFoundError(): 404 ...`), not with `HTTPException` scattered
  through the store.
- A redirect: return the URL string with `response_class=RedirectResponse`
  and `status_code=302`.

## Validation with pydantic v2

- `model_config = ConfigDict(extra="forbid")` on request models: unknown
  fields are client bugs, so reject them (422).
- Reuse domain validation: `url: Annotated[str,
  AfterValidator(normalize_url)]`. A `ValueError` inside becomes a 422 with the
  field name.
- Separate input and output models (`CreateLink`, `LinkOut`); never return
  ORM objects.
- `model_validate`, `model_dump`, and `model_dump_json`; the v1 API
  (`.dict()`, `.parse_obj()`, `class Config`) is gone or deprecated.
- The pydantic mypy plugin (`plugins = ["pydantic.mypy"]`) makes mypy
  understand `BaseSettings()` with no arguments and typed `__init__`s; pyright
  can't (verified: pyright reports "Argument missing for parameter
  database_url").

## Settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")
    database_url: SecretStr                   # required: missing env fails at startup
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = "INFO"

@cache
def get_settings() -> Settings:
    return Settings()
```

- Read once, at the entry point; pass `Settings` down. Tests construct
  `Settings(database_url=SecretStr(url))` directly instead of mutating
  `os.environ`.
- `SecretStr` keeps passwords out of `repr`, logs, and tracebacks; call
  `.get_secret_value()` only where the secret is used.
- Normalize URL forms in a validator (`postgres://` → `postgresql://`), and
  derive driver-specific URLs as properties (`sqlalchemy_url` adds
  `+psycopg`).
- No `.env` loading in production; Kamal injects env vars. For local work,
  `uv run --env-file .env ...` works without adding python-dotenv.

## SQLAlchemy 2.0 (async, typed)

```python
class LinkRow(Base):
    __tablename__ = "links"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- `postgresql+psycopg://` URL (psycopg 3; async and sync from one driver).
  Install `sqlalchemy[asyncio]` (it brings greenlet) and `psycopg[binary,pool]`.
- `create_async_engine(url, pool_size=..., pool_pre_ping=True)` once per
  process; `async_sessionmaker(engine, expire_on_commit=False)`. Without
  `expire_on_commit=False`, touching an attribute after commit triggers a lazy
  refresh, which in async raises `MissingGreenlet`.
- Relationships: load explicitly (`selectinload`) or set `lazy="raise"`;
  implicit lazy loading doesn't work under asyncio.
- 2.0-style queries only: `select(...)`, `session.scalars(...)`,
  `session.scalar(...)`, `update(...).values(...)`. The legacy `Query` API
  (`session.query`) is for old code.
- Counters and similar updates are one atomic `UPDATE ... SET clicks = clicks
  + 1`, never read-modify-write in Python.
- Keyset pagination (`WHERE code > :cursor ORDER BY code LIMIT n+1`), not
  `OFFSET`.
- Translate `IntegrityError` by inspecting `exc.orig`
  (`psycopg.errors.UniqueViolation`) to a domain `ConflictError`, and roll
  back the session first.
- **Sync alternative:** plain `def` endpoints with a sync `Session` are
  simpler and avoid `MissingGreenlet` entirely, but cap concurrency at the thread
  pool (40). Choose async for new services; keep sync for an existing sync
  codebase.
- **SQLAlchemy 2.1.0** was released on 2026-09-24. It requires Python 3.11+,
  makes greenlet opt-in (the `[asyncio]` extra), switches the default
  `postgresql://` driver to psycopg 3, and types rows with `Unpack`. The
  templates were verified on 2.0.54, so they cap `<2.1`. 2.1 installs cleanly
  with uv (wheels are on PyPI). Re-test, then
  lift the cap.
- **Leaner alternative:** raw psycopg 3 with SQL in the store, when the
  schema is small and you'd rather write SQL than map it. You lose
  autogenerate, not safety: always pass parameters (`cur.execute("... WHERE
  code = %s", (code,))`).

## Alembic migrations

- Migrations live in `src/acme_api/migrations/` so the wheel carries them;
  `acme-api migrate` runs them from the image with no alembic.ini:

```python
cfg = Config()
cfg.set_main_option("script_location", "acme_api:migrations")
cfg.attributes["sqlalchemy_url"] = settings.sqlalchemy_url   # not set_main_option: '%' in passwords
command.upgrade(cfg, "head")
```

- Developers use `[tool.alembic]` in the member's pyproject.toml (Alembic
  1.16+; `alembic init --template pyproject_async` generates it) and run `uv
  run alembic revision --autogenerate -m "..."`, `uv run alembic check`
  (fails if models and migrations disagree; wire it into CI when a database is
  available).
- `env.py` gets the URL from `config.attributes` or `Settings`, never a
  hard-coded ini value, and filters autogenerate to tables it owns with
  `include_name` (otherwise it proposes dropping procrastinate's tables).
- The async `env.py` calls `asyncio.run()`, so run migrations from sync code
  (the CLI, a test fixture), never from the app's lifespan.
- Review every autogenerated revision: it misses renames (emits drop + add),
  server-default changes, and enum changes.
- Zero-downtime deploys: expand, then contract. Add nullable columns or new
  tables, deploy code that writes both, backfill, then drop in a later release.
  The old version keeps serving while the pre-deploy hook migrates.
- Hand-written revision ids (`0001`, `0002`) keep history readable; set
  `file_template = "%%(rev)s_%%(slug)s"`.

## Background jobs: procrastinate on Postgres

Default: **procrastinate** (Postgres-backed; `SELECT ... FOR UPDATE SKIP
LOCKED` plus `LISTEN/NOTIFY`), not Celery + Redis. One fewer stateful service to
run, and a job deferred inside your transaction commits or rolls back with it.
Choose Celery (or a broker) only for very high job throughput, or when a broker
already exists.

```python
jobs = App(connector=PsycopgConnector())      # import-safe: nothing connects yet

@jobs.task(queue="clicks", pass_context=True, retry=RetryStrategy(max_attempts=5, exponential_wait=2))
async def record_click(context: JobContext, code: str) -> None:
    sessions: async_sessionmaker[AsyncSession] = context.additional_context["sessions"]
    async with sessions.begin() as session:
        await increment_clicks(session, Code(code))
```

- Defer from a route: `await record_click.defer_async(code=link.code)`.
  Arguments must be JSON-serializable; pass ids, not objects.
- The worker is its own process and Kamal role: `acme-api worker`
  (`run_worker_async(queues=[...], concurrency=..., shutdown_graceful_timeout=...,
  additional_context={...})`). `additional_context` hands resources (the
  session factory) to tasks without globals.
- Open the app with a fresh connector per context (`open_jobs()`, using
  `jobs.replace_connector(...)` + `open_async()`). Passing your own pool to
  `open_async(pool)` is a trap: after `close_async()` the connector keeps the
  reference to the closed pool, and the next `open_async` in the same process
  silently reuses it (`PoolClosed`).
- Schema: `acme-api migrate` applies procrastinate's schema on a fresh
  database (`schema_manager.apply_schema_async()`). On upgrades, apply the SQL
  files from `procrastinate schema --migrations-path` (named `{version}_{nn}_
  {pre|post}_...sql`) per its release notes: `pre` before deploying, `post`
  after.
- Tasks are idempotent (retries happen). Periodic jobs use
  `@jobs.periodic(cron="...")`. `queueing_lock` dedupes jobs waiting in the
  queue; `lock` serializes execution.
- Tests: run a real worker once with `wait=False`, which processes the queue
  and returns (the template's `test_redirect_defers_a_click_job_the_worker_runs`).

## Serving: uvicorn, workers, proxies, shutdown

`acme-api serve` calls `uvicorn.run` with:
- `"acme_api.app:create_app", factory=True`: an import string, required for
  `workers > 1`;
- `workers=settings.web_concurrency` (uvicorn supervises and restarts its
  workers itself; gunicorn is no longer needed, and FastAPI's docs deprecate the
  gunicorn-based image). About one per CPU core; one process per container is
  fine if you scale by containers instead;
- `proxy_headers=True, forwarded_allow_ips="*"`: trust `X-Forwarded-*`
  from kamal-proxy. This is safe only because nothing else can reach the
  container port;
- `timeout_graceful_shutdown=8`: drain within Docker's 10 s stop window;
- `log_config=logging_config(level)`: a dict, so each worker gets JSON logs.

Verified end to end: `acme-api migrate`, `serve` with 2 workers, `/up` 200,
POST/redirect, SIGTERM → "Waiting for application shutdown" → exit;
`worker` processed the deferred click and stopped cleanly on SIGTERM.

`uvicorn[standard]` adds uvloop and httptools (faster loop and parser). It
also pulls watchfiles (only used by `--reload`), which is harmless in prod.
Granian is a Rust ASGI server; consider it only after profiling shows the
server itself is the bottleneck.

## Health, logging, and errors

- `GET /up` returns 200 only when `SELECT 1` succeeds, and 503 otherwise;
  kamal-proxy polls it before routing traffic to a new container. Exclude it
  from the OpenAPI schema.
- JSON logs to stdout (`logs.py`); uvicorn's access log goes through the same
  root handler. Never log `Settings` secrets (they're `SecretStr`).
- Unhandled exceptions return a generic 500 (FastAPI's default), and the
  traceback goes to logs, never to the client.
- Rate limiting, TLS, and caching belong at the edge (Cloudflare) unless the
  rule depends on app data.

## Alternatives and when

| Instead of | Consider | When |
|---|---|---|
| FastAPI | **Litestar 2.24** | You want built-in DTOs, class-based controllers, and msgspec speed; the team knows it |
| FastAPI | Django + django-ninja | Admin UI, auth, and ORM batteries matter more than async throughput |
| SQLAlchemy ORM | psycopg 3 + SQL | Small schema, SQL-first team |
| procrastinate | Celery/Dramatiq + broker | Very high throughput, or a broker already runs |
| stdlib logging | structlog | Large codebase that wants bound context everywhere |
| pydantic at the edge | msgspec | Hot serialization paths, measured |
