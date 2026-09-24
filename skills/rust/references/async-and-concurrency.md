# Async, concurrency, and parallelism

Primary sources: the Tokio tutorial and API docs (https://tokio.rs/tokio/tutorial,
https://docs.rs/tokio), the Async Book (https://rust-lang.github.io/async-book/),
and the std `thread`/`sync` docs.

## Contents
- Pick the model
- The Tokio runtime
- Blocking work
- Shared state and locks
- Send bounds and the handler error
- Cancellation and cancellation safety
- Structured concurrency: JoinSet, select!, timeouts
- Channels
- Graceful shutdown
- Threads and data parallelism
- Pitfall list

## Pick the model

| Workload | Use |
|---|---|
| Many concurrent I/O waits (HTTP, DB, sockets) | **tokio** async, multi-threaded runtime |
| CPU-heavy, data-parallel work | **rayon** (`par_iter`) or `std::thread::scope` |
| A CLI that does some I/O sequentially | Plain blocking std code. No async runtime |
| A library | Sync API unless the domain is inherently async; never start a runtime inside a library |

Async is for waiting, not for speed. A CLI that reads files and prints doesn't
need tokio, and adding it costs compile time and complexity.

## The Tokio runtime

- `#[tokio::main]` builds the multi-threaded runtime (feature `rt-multi-thread`)
  in binaries. Enable only the features you use (`macros`, `rt-multi-thread`,
  `net`, `signal`, `time`, `sync`, `fs`), not `full`.
- Tests: `#[tokio::test]` runs a current-thread runtime by default; use
  `#[tokio::test(flavor = "multi_thread")]` when the code under test spawns
  and relies on parallelism.
- Never create a runtime inside async code, and never call
  `Runtime::block_on`/`futures::executor::block_on` from an async context: it
  panics ("Cannot start a runtime from within a runtime") or deadlocks.

## Blocking work

The runtime has a few worker threads. A task that blocks one (with CPU work
or a blocking syscall) stalls every other task scheduled there, and the
symptoms (latency spikes, timeouts) appear far from the cause.

- `std::thread::sleep` in async: use `tokio::time::sleep(..).await`.
- `std::fs` in async: use `tokio::fs` (which uses `spawn_blocking` inside), or
  one `spawn_blocking` around a batch of std I/O.
- Blocking libraries (bcrypt/argon2 hashing, image processing, compression,
  sync DB drivers, `reqwest::blocking`): wrap them in
  `tokio::task::spawn_blocking(move || ..).await?`.
- Long CPU loops: `spawn_blocking`, or rayon plus a `oneshot` channel for
  results. As a rule of thumb, anything over ~100 µs between `.await`s is
  blocking.
- `spawn_blocking` tasks can't be cancelled: they run to completion even when
  the awaiting future is dropped.

## Shared state and locks

- **`std::sync::Mutex` is the default**, even in async code, when the critical
  section is short and contains **no `.await`** (Tokio's own guidance). It's
  faster than `tokio::sync::Mutex`.
- **Never hold a std `MutexGuard` (or `RwLock` guard) across `.await`.** The
  future becomes `!Send` (so `tokio::spawn` and axum reject it), and if it did
  compile it could deadlock the worker. Scope it:
  ```rust
  let next = {
      let mut n = state.counter.lock().expect("poisoned");
      *n += 1;
      *n
  }; // guard dropped here
  store.save(next).await?;
  ```
- Use `tokio::sync::Mutex` only when the lock must be held across an
  `.await` (for example, serializing access to one connection). Prefer
  redesigning so it isn't needed.
- Better than a lock: give the state to **one task** and talk to it over an
  `mpsc` channel (actor pattern), or use atomics (`AtomicU64`) for counters.
- `Arc<T>` to share across tasks and threads; `Rc<T>` only in single-threaded
  code (it's `!Send`, so it can't cross a `tokio::spawn`).
- `PgPool`, `reqwest::Client`, `axum::Router`, and most `tokio::sync` handles
  are already cheap-to-clone handles. Clone them; don't wrap them in `Arc`.
- Poisoning: a std mutex is poisoned when a holder panics. `.lock().expect(..)`
  propagates the panic, which is the right default for a broken invariant.

## Send bounds and the handler error

`tokio::spawn` and axum handlers require `Send + 'static` futures. Anything
held across an `.await` becomes part of the future's state: `Rc`, `RefCell`
borrows, std mutex guards, and raw pointers make it `!Send`.

axum reports this as the confusing "the trait `Handler<_, _>` is not
implemented for fn item". Add `#[axum::debug_handler]` (axum `macros`
feature) to the handler temporarily to get the real error, which points at
the `!Send` value.

`'static` means spawned tasks can't borrow from the caller's stack. Move owned
data (or `Arc`s) in with `async move`.

## Cancellation and cancellation safety

A future is cancelled by being **dropped**: when a `select!` branch loses,
a timeout fires, a client disconnects (axum drops the handler future), or a
`JoinHandle` is aborted. Code after the pending `.await` never runs.

- Design each `.await` point so stopping there leaves state consistent. Put
  multi-step writes in a database transaction (sqlx rolls back on drop) instead
  of relying on code after an `.await`.
- In `tokio::select!` loops, use only **cancel-safe** operations in branches
  that may lose: `mpsc::Receiver::recv`, `broadcast::Receiver::recv`,
  `TcpListener::accept`, `tokio::time::sleep`, and `CancellationToken::cancelled`
  are cancel-safe. `AsyncReadExt::read_exact` and `AsyncWriteExt::write_all`
  are not (partial progress is lost), and a cancelled `tokio::sync::Mutex::lock`
  loses its place in the fairness queue. Each Tokio method documents its
  cancel safety; check before putting it in a `select!` loop.
- To use a non-cancel-safe future in a loop, create it once outside the loop,
  `tokio::pin!` it, and poll `&mut fut` in the branch.
- Work that must finish even if the request goes away: `tokio::spawn` it (a
  detached task isn't cancelled when the handle drops), or enqueue a job.

## Structured concurrency: JoinSet, select!, timeouts

- Run N things concurrently and collect them: `tokio::task::JoinSet`
  (dropping it aborts the remaining tasks), or `futures::future::try_join_all`
  for a fixed list in the same task.
- Bound concurrency: a `tokio::sync::Semaphore`, or
  `futures::stream::iter(..).buffer_unordered(n)`. Unbounded `spawn` in a loop
  is how services fall over under load.
- Every outbound call gets a timeout: `tokio::time::timeout(dur, fut)`, the
  client's own timeout, or tower's `TimeoutLayer` for inbound requests.
- Always handle `JoinError` (a panic or abort in the task): `handle.await?`.
- Don't fire and forget. Keep the `JoinHandle`, or a `JoinSet`, or a
  `tokio_util::task::TaskTracker`, so shutdown can wait for tasks.

## Channels

| Need | Channel |
|---|---|
| Many producers, one consumer, backpressure | `tokio::sync::mpsc::channel(n)` (bounded) |
| One response | `tokio::sync::oneshot` |
| Fan-out to all subscribers | `tokio::sync::broadcast` |
| Latest value (config, shutdown flag) | `tokio::sync::watch` |
| Between plain threads | `std::sync::mpsc` or crossbeam-channel |

Prefer bounded channels: an unbounded channel turns a slow consumer into a
memory leak.

## Graceful shutdown

Kamal and `docker stop` send **SIGTERM**, then SIGKILL after a grace period
(configurable in Kamal as `stop_wait_time`; check the default for your version).
The service must listen for SIGTERM (not just Ctrl-C) and let in-flight
requests finish:

```rust
axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
db.close().await;
```
`shutdown_signal` in `assets/api-main.rs` waits for either signal. For
background workers, pass a `tokio_util::sync::CancellationToken` (or a
`watch` channel), `select!` on `token.cancelled()` in each loop, and await the
`JoinSet`/`TaskTracker` before exiting.

## Threads and data parallelism

- `std::thread::scope` borrows from the stack safely: the scope joins every
  thread before returning. Use it for a few parallel chunks without rayon.
- rayon for data parallelism: `iter()` becomes `par_iter()`. Don't call rayon
  from inside tokio worker threads for long jobs; hand off with
  `spawn_blocking` or a dedicated pool, and send results back on a `oneshot`.
- `std::sync::atomic` with `Ordering::Relaxed` for counters and statistics;
  `Acquire`/`Release` pairs when the atomic publishes other data. Use
  `SeqCst` only if you can't justify something weaker.

## Pitfall list

1. Blocking call in async (sleep, std::fs, CPU loops, sync clients).
2. A std guard held across `.await` (`!Send`, deadlocks).
3. `block_on` inside async (panic or deadlock).
4. Non-cancel-safe futures in a `select!` loop, or multi-step state changes
   split across `.await`s without a transaction.
5. Unbounded `spawn` or unbounded channels (no backpressure).
6. Missing timeouts on outbound calls.
7. Fire-and-forget tasks that shutdown can't wait for, and panics swallowed in
   unawaited `JoinHandle`s.
8. `Rc`/`RefCell` in async code that gets spawned.
9. A runtime started inside a library, or tokio pulled into a library that
   doesn't need it.
10. Listening only for Ctrl-C, so SIGTERM kills in-flight requests.
