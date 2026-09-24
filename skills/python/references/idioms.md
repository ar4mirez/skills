# Idioms: types, data, errors, resources, and the "don't" list

Grounded in the Python 3.14 docs (https://docs.python.org/3.14/), the typing
spec (https://typing.python.org/), and the mypy docs
(https://mypy.readthedocs.io/). Examples are from the verified templates.

## Contents
- Naming and modules
- Type hints (modern syntax, PEP 695, PEP 649)
- Data: dataclasses vs pydantic vs dicts
- Enums, pathlib, datetime
- Errors: one hierarchy per package
- Resources: context managers
- Logging: stdlib, JSON, once
- Strings: f-strings and t-strings
- API design
- The "don't" list

## Naming and modules

- `snake_case` functions, variables, and modules; `PascalCase` classes;
  `UPPER_CASE` module constants; a leading `_` for anything private to the
  module. There's no `private` keyword: `_name` is the contract.
- A package's `__init__.py` re-exports the public API and sets `__all__`.
  Callers import `from acme_core import parse_code`, never from submodules, so
  you can move code between files without breaking anyone.
- Absolute imports only (`from acme_api.store import ...`); ruff's
  `ban-relative-imports = "all"` enforces it.
- No import-time side effects: no network, no env reads, no logging config at
  import. `jobs.py` builds an unconnected procrastinate `App`; the connection is
  opened in `open_jobs()` at runtime. Import-time work makes tests slow and
  entry points unpredictable.

## Type hints

Every public function is fully annotated, and mypy runs with `strict = true`.
Hints are documentation that CI checks.

```python
def parse_code(raw: str) -> Code: ...                  # builtin generics, no typing.List
def find(code: str) -> Link | None: ...                  # X | None, not Optional[X]
type LogLevel = Literal["DEBUG", "INFO", "WARNING"]      # PEP 695 type alias statement

@dataclass(frozen=True, slots=True)
class Page[T]:                                            # PEP 695 generic class
    items: tuple[T, ...]
    next_cursor: str | None = None

def paginate[T](items: Iterable[T], *, limit: int, cursor_of: Callable[[T], str]) -> Page[T]: ...
```

- Accept abstract types (`Iterable`, `Mapping`, `Sequence` from
  `collections.abc`), return concrete ones (`list`, `dict`, `tuple`).
- `NewType("Code", str)` marks validated values at zero runtime cost; only the
  validator constructs one (`parse_code` returns `Code`).
- `typing.override` on overriding methods; `Self` for fluent returns;
  `TypedDict` only for JSON-shaped dicts you don't own; `Protocol` for
  structural interfaces declared by the consumer.
- **PEP 649 (3.14):** annotations are lazy, so `def of(cls, link: Link) ->
  LinkOut:` inside `class LinkOut` works without quotes. Remove `from __future__
  import annotations` in 3.14-only code; keep it in libraries that still support
  3.13 and older. To read annotations at runtime, use
  `annotationlib.get_annotations()`.
- `Any` is a hole in the type system. `cast()` and `# type: ignore[code]`
  need a reason in a comment; mypy strict's `warn_unused_ignores` removes stale
  ones. Always name the error code (`ignore-without-code` is enabled).

## Data: dataclasses vs pydantic vs dicts

| Shape | Use |
|---|---|
| Internal value or domain object | `@dataclass(frozen=True, slots=True, kw_only=True)` |
| Data crossing a trust boundary (HTTP body, env, file, queue message) | pydantic `BaseModel` / `BaseSettings` with `extra="forbid"` |
| ORM row | SQLAlchemy `Mapped[...]` model, mapped to a domain dataclass in the store |
| Throwaway grouping inside a function | a tuple, or a `NamedTuple` if it escapes |

Why: dataclasses are stdlib, fast, and carry no validation cost where the data
is already trusted. pydantic validates and coerces, which is exactly what you
want at the boundary and wasteful (and surprising) everywhere else. Don't pass
pydantic models or ORM rows into domain code; convert at the edge
(`LinkRow.to_domain()`, `LinkOut.of(link)`).

- `frozen=True`: hashable and safe to share; use `dataclasses.replace()` (or
  `copy.replace()`, 3.13+) to derive a changed copy.
- `slots=True`: smaller, faster attribute access, typos raise
  `AttributeError`.
- `kw_only=True` for more than about three fields, so call sites stay readable
  and field order can change.
- Pydantic validators can reuse domain validation:
  `Annotated[str, AfterValidator(normalize_url)]`. A `ValueError` raised inside
  becomes a 422 in FastAPI automatically.

## Enums, pathlib, datetime

- `enum.StrEnum` for string choices (`class Format(StrEnum): TEXT = "text"`).
  Members compare equal to their values and serialize as plain strings; typer
  and pydantic accept them as choices.
- `match` with class patterns for dispatch on types or shapes; it reads better
  than `isinstance` chains (`app.py` maps errors to status codes this way).
- `pathlib.Path` for every filesystem path; `os.path` is legacy (ruff's PTH
  rules flag it). `Path.read_text(encoding="utf-8")`: always pass the encoding
  until 3.15 makes UTF-8 the default.
- Timezone-aware datetimes only: `datetime.now(UTC)`; store `timestamptz`.
  `datetime.utcnow()` is deprecated and returns naive values (ruff DTZ).

## Errors: one hierarchy per package

```python
class LinkError(Exception): ...                          # the package's root
class InvalidInputError(LinkError, ValueError): ...      # also a ValueError for generic callers
class NotFoundError(LinkError): ...
class ConflictError(LinkError): ...
```

- Raise specific subclasses; callers catch the root to handle "anything this
  package does on purpose". Programmer errors (`TypeError`, `KeyError` from a
  bug) stay unwrapped and crash loudly.
- Attach data as attributes (`exc.field`, `exc.reason`), not only in the
  message, so callers branch on data instead of parsing strings.
- `raise NewError(...) from exc` when translating (the store maps
  `psycopg.errors.UniqueViolation` to `ConflictError`), so the traceback keeps
  the cause. Translate driver errors at the adapter; domain code never imports
  psycopg or SQLAlchemy exceptions.
- Catch the narrowest exception, as close to the cause as you can act on it.
  Never a bare `except:` (it also catches `KeyboardInterrupt` and
  `SystemExit`), and never `except Exception: pass`.
- Handle each error once: log it *or* raise it, not both.
- `ExceptionGroup` / `except*` only for concurrent failures (TaskGroup
  raises them).
- `assert` is for invariants in tests and internal sanity checks; it disappears
  under `python -O`, so never use it to validate input.

## Resources: context managers

Anything that must be released (files, connections, locks, pools, temp dirs)
lives in a `with` block. Write your own with `@contextmanager` /
`@asynccontextmanager`:

```python
@asynccontextmanager
async def open_jobs(conninfo: str, *, max_size: int = 4) -> AsyncIterator[App]:
    connector = PsycopgConnector(conninfo=conninfo, min_size=1, max_size=max_size)
    with jobs.replace_connector(connector):
        async with jobs.open_async():
            yield jobs
```

- Group several resources in one parenthesized `with (a as x, b as y):`.
- `contextlib.ExitStack` / `AsyncExitStack` for a dynamic number of
  resources.
- `tempfile.TemporaryDirectory()`, `NamedTemporaryFile(delete_on_close=False)`;
  never `tempfile.mktemp()` (racy).
- Don't rely on `__del__` or garbage collection to close things.

## Logging: stdlib, JSON, once

Default: the stdlib `logging` module with a small JSON formatter (`logs.py`).
It has zero dependencies, and every library you use already logs through it.
Reach for **structlog** only when you want bound, context-rich loggers across
a large codebase and accept the dependency; don't mix the two.

- Libraries: `log = logging.getLogger(__name__)` and nothing else. Only the
  entry point configures handlers.
- Pass fields with `extra={"code": code}`; the JSON formatter emits them as
  keys. Use `%s` args (`log.info("created %s", code)`), not f-strings: they
  format even when the level is filtered, and log aggregators group by the
  unformatted message.
- `log.exception(...)` inside `except` to keep the traceback.
- uvicorn: pass a `dictConfig` as `log_config` (`logging_config()`), not
  `None`. uvicorn re-applies it in each worker process; with `None`, workers
  spawned by `--workers` get no handlers and drop their logs.

## Strings: f-strings and t-strings

- f-strings for everything human-facing; `!r` for identifiers in messages
  (`f"no link with code {code!r}"`).
- **t-strings (3.14, PEP 750):** `t"SELECT ... {x}"` produces a `Template`, so
  the consumer decides how to escape each interpolation. They're the right
  interface for SQL, HTML, or shell builders you *write*. Until your driver or
  library accepts templates, keep using bound parameters (`execute(sql,
  params)`); a t-string you `str()` or join yourself is as unsafe as an
  f-string.

## API design

- Keyword-only parameters (`*,`) for anything that isn't obviously
  positional, especially booleans (`paginate(items, *, limit, cursor_of)`).
- Return values, don't mutate arguments. Never use a mutable default
  argument: `def f(tags: list[str] | None = None)` and build inside.
- Small functions over classes. A class earns its place by holding state
  or implementing a protocol; a class with one method and `__init__` is a
  function.
- Dependency injection by parameter: pass the session, settings, or
  clock into the function. Tests then need no patching.
- Pure functions for rules (the `acme_core` package has no I/O), I/O at the
  edges (routes, store, jobs, CLI commands).

## The "don't" list

| Don't | Why | Instead |
|---|---|---|
| `eval`/`exec` on data | Arbitrary code execution | `ast.literal_eval`, `json`, a parser |
| `pickle`/`marshal`/`shelve` on untrusted bytes | Executes code on load | JSON, msgpack, or pydantic models |
| `yaml.load(f)` | Constructs arbitrary objects | `yaml.safe_load` |
| `subprocess.run(cmd, shell=True)`, `os.system` | Shell injection | `subprocess.run([...], check=True, timeout=...)` |
| SQL via f-string / `%` / `+` | SQL injection | Bound parameters / SQLAlchemy expressions |
| `requests.get(url)` without `timeout=` | Hangs forever | `timeout=10` or httpx (5 s default) |
| Bare `except:` / `except Exception: pass` | Hides bugs and Ctrl-C | Catch specific errors; log or re-raise |
| Mutable default arguments | Shared across calls | `None` default |
| `typing.List`, `Optional`, `Union` | Legacy spellings | `list[int]`, `X | None` |
| Global mutable state and singletons | Hidden coupling, test order bugs | Pass dependencies in; `functools.cache` for pure lookups |
| `import *`, relative parent imports | Unclear names | Explicit absolute imports |
| `os.path`, string paths | Error-prone | `pathlib.Path` |
| Naive datetimes, `utcnow()` | Wrong around DST and in comparisons | `datetime.now(UTC)` |
| `random` for tokens | Predictable | `secrets.token_urlsafe()`, `secrets.choice` |
| `print` for diagnostics in libraries | Can't be filtered or routed | `logging` |
| `setup.py` + `requirements.txt` | No lock, no standard metadata | `pyproject.toml` + `uv.lock` |
| `__del__` for cleanup | Not guaranteed to run | Context managers |
| Inheritance for code reuse | Tight coupling | Composition and functions |
