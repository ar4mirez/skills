# Performance: measure, then fix

Sources: the profile docs (https://docs.python.org/3.14/library/profile.html),
py-spy (https://github.com/benfred/py-spy), pyinstrument
(https://pyinstrument.readthedocs.io/), Scalene
(https://github.com/plasma-umass/scalene), memray
(https://bloomberg.github.io/memray/), and PEP 799 (3.15's `profiling`
package). Versions checked on PyPI on 2026-09-24; all listed tools publish
3.14 support (classifiers or cp314 wheels).

## Contents
- The workflow
- Which profiler
- Reading a profile
- Common wins (in order of likelihood)
- Memory
- Services: latency and throughput
- When to reach for native code
- Startup time

## The workflow

1. **Reproduce with a number.** A benchmark script, a `pytest-benchmark`
   test, or a load test (`oha`, `k6`) against the real endpoint. Record
   the baseline.
2. **Profile the real workload,** not a guess. Sampling profilers first.
3. **Fix the top item only,** then re-measure against the baseline.
4. **Keep the benchmark** (or a regression test) so it stays fixed.

Most Python slowness is I/O (N+1 queries, missing indexes, serial HTTP calls)
or an algorithm (a list membership test inside a loop). Interpreter speed is
rarely the first problem.

## Which profiler

| Tool | Kind | Use for |
|---|---|---|
| **py-spy 0.4.2** | Sampling, out of process, no code changes | A running service: `py-spy top --pid N`, `py-spy record -o flame.svg --pid N`, `py-spy dump --pid N` (stuck process). Needs root/ptrace on Linux and sudo on macOS |
| **pyinstrument 5.1** | Sampling, in process, call-tree output | Scripts, CLIs, tests: `uvx pyinstrument script.py`; has ASGI middleware for one request |
| `cProfile` + `pstats` | Deterministic (every call) | Exact call counts; `python -m cProfile -s cumtime app.py`. Heavy overhead: a 0.46 s CPU loop took 1.6 s under it (verified), so the timings skew toward call-heavy code |
| **Scalene 2.3** | Sampling CPU + memory + GPU, line level | Separating Python time from native time, per line |
| **memray 1.20** | Allocation tracker | Memory growth and leaks: `memray run app.py`, then `memray flamegraph` |
| `tracemalloc` (stdlib) | Allocation snapshots | Diffs in tests or production without extra dependencies |
| `python -X importtime` | Import timing | Slow startup (`-X importtime=2` in 3.14 also shows cached imports) |
| `python -m asyncio pstree PID` (3.14) | Task tree of a live process | "What is every task awaiting right now?" |

3.15 adds `profiling.sampling`, a built-in low-overhead sampling profiler
(PEP 799), and deprecates the `profile` module. Plan to use it when you move to
3.15; until then, use py-spy or pyinstrument.

## Reading a profile

- Sort by **cumulative** time to find the expensive subtree, then by
  **self** (tottime) to find the hot function inside it.
- In async services, wall-clock time spent awaiting shows as idle in CPU
  profiles. If CPU is low but latency is high, the problem is I/O or lock
  waits: look at query timings and connection-pool waits.
- Flame graphs: width is time. Look for wide plateaus, not tall towers.

## Common wins (in order of likelihood)

1. **Database:** N+1 queries (load relationships with `selectinload`, or
   write one query), missing indexes (`EXPLAIN (ANALYZE, BUFFERS)`), `OFFSET`
   pagination (use keyset), fetching columns you don't need, per-row commits
   (batch them).
2. **Serial I/O:** fan out with `TaskGroup` + a semaphore (async) or a
   `ThreadPoolExecutor` (sync). Reuse clients (`httpx.AsyncClient`,
   connection pools) instead of creating one per request.
3. **Data structures:** `set`/`dict` for membership (O(1) vs a list's O(n));
   `collections.deque` for queues; `bisect` for sorted lookups;
   `heapq` for top-k.
4. **Do less:** cache pure lookups with `functools.cache` / `lru_cache`
   (bounded); move work out of loops; stream with generators instead of
   building lists; `str.join` instead of `+=` in loops.
5. **Builtins and the stdlib are C:** `sum`, `min`, `sorted(key=...)`,
   `itertools`, `collections.Counter`, and comprehensions beat hand-written
   loops.
6. **Serialization:** pydantic v2's core is Rust and fast; for hot paths,
   `model_validate_json` (parse and validate in one step) beats `json.loads` +
   `model_validate`. Consider `msgspec` or `orjson` only after profiling.
7. **Vectorize** numeric work (NumPy, Polars) instead of looping in Python.

## Memory

- `__slots__` (or `@dataclass(slots=True)`) for many small objects.
- Generators and `itertools` to stream large inputs; read files line by line.
- Watch unbounded caches (`@cache` on a method holds `self` forever; use
  `lru_cache(maxsize=...)` at module level, or cache per instance).
- Services: memory that grows per request is usually a module-level
  list/dict, an unbounded cache, or tasks that are never awaited. `memray` or
  `tracemalloc` snapshots taken 1,000 requests apart show which one.
- Free-threaded builds use more memory per object; measure before switching.

## Services: latency and throughput

- Size pools deliberately: `db_pool_size` × processes × containers must stay
  under Postgres `max_connections` (or use PgBouncer).
- uvicorn workers ≈ CPU cores per container; more processes only add
  memory once the CPU is saturated.
- Timeouts everywhere (HTTP clients, DB `statement_timeout`), so a slow
  dependency degrades one endpoint instead of exhausting every worker.
- Move slow, retryable work (emails, webhooks, click counting) to background
  jobs.
- Cache at the edge (Cloudflare) for public GETs before adding Redis.

## When to reach for native code

Avoid premature C extensions: each one adds a build toolchain, platform
wheels, and a class of memory bugs. In order:

1. An algorithm or I/O fix (above).
2. An existing native library (NumPy, Polars, orjson, regex engines).
3. Parallelism: processes, or the free-threaded build for CPU-bound threads
   (see `references/concurrency.md`).
4. **Rust via PyO3 + maturin** for a small, hot, well-tested kernel. Build with
   `maturin` (it replaces the `uv_build` backend for that package) and ship
   abi3 wheels.
5. Cython or C only if the team already maintains them.

Don't expect the experimental JIT to fix a hot loop. 3.14 ships it in some
official binaries, experimental and disabled by default, and the
interpreter-level gains are modest (the new tail-call interpreter gives about
3 to 5%). Measure before relying on either.

## Startup time

CLI latency is usually import time. Measure with `python -X importtime -c
"import acme_cli.main" 2> imports.txt`, then import heavy modules inside the
command that needs them. 3.15's `lazy import` (PEP 810) will make this
declarative; don't target it until you require 3.15.
