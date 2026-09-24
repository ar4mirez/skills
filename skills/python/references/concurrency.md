# Concurrency: asyncio, threads, processes, free-threading, subinterpreters

Sources: the asyncio docs (https://docs.python.org/3.14/library/asyncio.html),
the free-threading HOWTO
(https://docs.python.org/3.14/howto/free-threading-python.html), and
`concurrent.interpreters`
(https://docs.python.org/3.14/library/concurrent.interpreters.html). Behaviors
marked "verified" were run on CPython 3.14.7.

## Contents
- Choosing a model
- asyncio rules
- Structured concurrency: TaskGroup and timeouts
- Blocking calls in async code
- Threads
- Processes
- Free-threaded Python (3.14t)
- Subinterpreters
- Cancellation and shutdown
- Pitfalls checklist

## Choosing a model

| Workload | Default | Why |
|---|---|---|
| Many concurrent I/O waits (HTTP APIs, DB, sockets) | **asyncio** | One thread, thousands of waits, explicit suspension points |
| A few blocking calls in an async program | `asyncio.to_thread(fn, ...)` | Keeps the loop free without rewriting the library |
| Blocking I/O in sync code (a CLI fetching 20 URLs) | `ThreadPoolExecutor` | Simple; the GIL is released during I/O |
| CPU-bound pure Python | `ProcessPoolExecutor` | Sidesteps the GIL; true parallelism |
| CPU-bound, heavy data sharing, dependencies all free-threading-ready | Free-threaded 3.14t + threads | Parallel threads, shared memory, no pickling |
| CPU-bound, isolated tasks, lower overhead than processes | `InterpreterPoolExecutor` | Per-interpreter GIL; still maturing |
| NumPy/Polars-style array work | Let the library parallelize | Vectorized C code releases the GIL |

Don't mix models without a reason. A FastAPI service is asyncio end to end;
a CLI is synchronous unless it truly fans out I/O.

## asyncio rules

1. **One entry point:** `asyncio.run(main())`. Never
   `asyncio.get_event_loop()`: on 3.14 it raises `RuntimeError` when no loop is
   running (verified), and the policy APIs are deprecated. Inside coroutines,
   use `asyncio.get_running_loop()`.
2. **`async def` only when the function awaits something.** An `async def`
   that never awaits just adds overhead and misleads readers.
3. **Every task has an owner.** Create tasks in a `TaskGroup` (or keep them
   in a set and discard on completion). A bare `asyncio.create_task(...)` whose
   result is dropped can be garbage-collected mid-flight, because the loop keeps
   only weak references, and its exception is never seen.
4. **Never block the loop** (next section). One blocking call stalls every
   request in the process.
5. **Bound concurrency:** `asyncio.Semaphore(n)` around outbound calls; a
   database pool size is a hard limit too (`pool_size`, `max_size`).
6. **Async all the way down** in a request path: async driver (psycopg async,
   httpx `AsyncClient`), async session.

## Structured concurrency: TaskGroup and timeouts

```python
async def fetch_all(client: httpx.AsyncClient, urls: list[str]) -> list[str]:
    limit = asyncio.Semaphore(10)

    async def one(url: str) -> str:
        async with limit:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async with asyncio.timeout(30):              # a deadline for the whole batch
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(one(u)) for u in urls]
    return [t.result() for t in tasks]
```

- `TaskGroup` (3.11+) waits for all children; if one fails, it cancels the
  rest and raises an `ExceptionGroup`. Handle it with `except* HTTPError`.
- `asyncio.timeout(seconds)` / `timeout_at(deadline)` replace `wait_for`
  for new code; the timeout surfaces as `TimeoutError`.
- `asyncio.gather` has no cancellation-on-failure by default; prefer
  `TaskGroup`.
- For fire-and-forget work that must survive the request, don't use a task:
  defer a **job** (procrastinate), which is durable and retried.

## Blocking calls in async code

These block the event loop inside `async def`: `time.sleep`, `requests.*`,
`urllib.request.urlopen`, `subprocess.run`, `open()`/file reads of any size,
`psycopg2`, CPU loops over large data, and any sync SDK (boto3, most payment
SDKs).

- Async replacement first: `await asyncio.sleep`, `httpx.AsyncClient`,
  `asyncio.create_subprocess_exec`, psycopg 3 async, `aioboto3`.
- Otherwise `await asyncio.to_thread(fn, *args)`. It runs in the default
  thread pool; that's fine for occasional calls, but not for hot paths.
- Detect them: ruff's `ASYNC` rules (ASYNC210 and friends), the audit script's
  `blocking-in-async`, and `PYTHONASYNCIODEBUG=1` (or `asyncio.run(...,
  debug=True)`), which logs callbacks slower than 100 ms.
- Diagnose a stuck process live: `python -m asyncio pstree <PID>` (3.14) shows
  what every task awaits.
- FastAPI note: a plain `def` endpoint runs in a thread pool (AnyIO's default
  limit is 40 threads), so blocking code there doesn't stall the loop. It's
  still a capacity limit, so keep endpoints `async def` with async I/O as the
  default, and use `def` only for endpoints wrapping sync libraries.

## Threads

- `concurrent.futures.ThreadPoolExecutor` with `with` (joins on exit);
  `executor.map` or `submit` + `as_completed`. Don't manage `threading.Thread`
  lifecycles by hand unless it's a long-lived service thread with a stop
  `Event`.
- Share nothing mutable, or guard it with a `threading.Lock`. Passing work
  through `queue.Queue` is simpler than locking.
- `contextvars` don't propagate into plain threads on the GIL build; on the
  free-threaded build, threads inherit the caller's context by default
  (`sys.flags.thread_inherit_context`). Use `contextvars.copy_context().run`
  when it matters.

## Processes

- `ProcessPoolExecutor` for CPU-bound Python. Arguments and results are
  pickled, so send small inputs (paths, ids), not large objects.
- **3.14 changed the default start method on Linux to `forkserver`**
  (macOS and Windows already use `spawn`). Workers no longer inherit the parent's
  memory, so module-level state set at runtime isn't there, and the callable must
  be importable (module level, not a lambda or closure). Guard entry points with
  `if __name__ == "__main__":`.
- Don't fork a process that has threads or an event loop running (explicit
  `get_context("fork")` in such programs deadlocks intermittently).

## Free-threaded Python (3.14t)

Status (PEP 779): **officially supported, not the default build.** Install it
with `uv python install 3.14t` (uv lists `cpython-3.14.7+freethreaded`), or
use the python.org installers. Check it with
`sysconfig.get_config_var("Py_GIL_DISABLED")` and `sys._is_gil_enabled()`.

Verified on 3.14.7 (Apple M-series, 4 threads × a pure-Python sum): the GIL
build took 0.45 s threaded vs 0.46 s serial (no speedup); 3.14t took 0.19 s
threaded vs 0.42 s serial.

Use it when all of these hold:
- the workload is CPU-bound pure Python that you'd otherwise split across
  processes, and shares a lot of memory;
- every C extension you import supports it. One that doesn't **re-enables the
  GIL at import** (with a warning), silently removing the benefit. Check
  https://py-free-threading.github.io/tracking/;
- you've measured: single-threaded code runs about 1 to 8% slower and uses more
  memory.

Don't use it for I/O-bound services (asyncio already handles those) or as a
default runtime. Builtins stay internally consistent, but compound operations
(check-then-set on a dict) still need locks.

## Subinterpreters

3.14 adds `concurrent.interpreters` (PEP 734) and
`concurrent.futures.InterpreterPoolExecutor`: isolated interpreters in one
process, each with its own GIL, so CPU work runs in parallel without spawning
processes (verified: `InterpreterPoolExecutor().map(square, range(5))` works on
3.14.7).

- Functions and arguments must be shareable (module-level functions;
  arguments are pickled or shared through `Queue`).
- Many C extensions don't support multiple interpreters yet and fail to
  import in a subinterpreter.
- Close interpreters you create (`interp.close()`); 3.14 warns about leftover
  subinterpreters at exit (verified).
- Treat it as an option for new CPU-bound code that uses pure Python and
  stdlib modules; `ProcessPoolExecutor` remains the safe default.

## Cancellation and shutdown

- Cancellation is an exception (`CancelledError`) delivered at an `await`.
  Clean up in `finally` or `async with`, and **re-raise** it. It subclasses
  `BaseException`, so `except Exception` lets it through, but a bare `except:`
  or `except BaseException:` swallows it and the task never stops.
- Wrap cleanup that must finish in `asyncio.shield()` sparingly, or
  better, make it idempotent.
- Services: uvicorn handles SIGTERM, stops accepting connections, waits up
  to `timeout_graceful_shutdown` for in-flight requests, then runs lifespan
  shutdown (dispose the engine, close pools). procrastinate's worker handles
  SIGTERM and waits up to `shutdown_graceful_timeout` for running jobs. Keep
  both under the orchestrator's stop timeout (Docker's default is 10 s).
- Use exec-form `CMD ["acme-api", "serve"]` in Docker, or SIGTERM goes to
  `/bin/sh` and Python never sees it.

## Pitfalls checklist

- [ ] No `time.sleep`/`requests`/sync DB drivers inside `async def`.
- [ ] Every `create_task` is in a TaskGroup or stored.
- [ ] Every outbound call has a timeout; every fan-out has a semaphore.
- [ ] No `asyncio.get_event_loop()`, `set_event_loop_policy`, or nested
      `asyncio.run` (Alembic's async `env.py` calls `asyncio.run`, so run
      migrations from sync code, never from inside the app's loop).
- [ ] Locks are held briefly and never across `await` for `threading.Lock`.
- [ ] Process-pool callables are importable at module level (forkserver).
- [ ] Free-threaded builds are opted into deliberately, with measurements.
