# Concurrency and parallelism

## Contents
- The default model
- std::jthread and stop_token
- The thread pool (assets/thread_pool.hpp)
- Shared state: mutexes, atomics, and condition variables
- Async I/O and std::execution
- Signals in services
- ThreadSanitizer
- Pitfalls

## The default model

1. **Don't share mutable state.** Give each task its own data and merge results at the end
   (the CLI counts each file into its own `Counter` and `merge`s on the main thread). This
   needs no locks and scales.
2. **A fixed-size thread pool** for CPU-bound work: `acme::ThreadPool` with `submit()`
   returning a `std::future`. Size it to `std::thread::hardware_concurrency()` (which can
   return 0, hence `std::max(1U, …)`).
3. **`std::jthread` + `std::stop_token`** for long-running workers that need cooperative
   cancellation.
4. **Blocking I/O on a pool** for services (cpp-httplib's model). Go async (Asio) only when
   you've measured that connection count, not CPU, is the bottleneck.

Parallel STL algorithms (`std::execution::par`) are fine for a single hot loop over a big
container on GCC (it needs TBB on Linux) and MSVC; libc++'s support is partial. Don't make them
your concurrency architecture.

## std::jthread and stop_token

- `std::jthread`'s destructor calls `request_stop()` then `join()`. A `std::thread` that's
  still joinable at destruction calls `std::terminate`.
- If the callable's first parameter is a `std::stop_token`, `jthread` passes its own token.
- `std::condition_variable_any::wait(lock, stop_token, pred)` wakes on stop and returns
  `pred()`. This lets a worker sleep on a queue and still exit promptly, with no hand-written
  "shutdown" flag or notify.
- `std::stop_callback` runs a function when stop is requested (for example, to close a socket
  that a blocking call is waiting on).

## The thread pool (assets/thread_pool.hpp)

Design points worth copying:
- **Rule of Zero:** no destructor. `std::vector<std::jthread>` is declared **last**, so it's
  destroyed first. Workers join while the mutex, condition variable, and queue still exist.
  Reordering members is a use-after-destroy bug that TSan/ASan catch only sometimes.
- **Drains on shutdown:** the wait predicate returns false only when stop is requested *and*
  the queue is empty. Choose "drain" or "drop" explicitly; dropping breaks the futures of
  queued tasks (`std::future_error: broken promise`).
- **Tasks are `std::packaged_task<void()>`**, which accepts move-only callables. `std::function`
  requires copyable callables, and `std::move_only_function` isn't in libc++ yet.
- **Exceptions travel through the future:** a throwing task never kills a worker; `get()`
  rethrows on the caller's thread.
- **`submit` is `[[nodiscard]]`:** discarding the future means you'll never see the task's
  exception. Fire-and-forget callers write `(void)pool.submit(…)` on purpose.
- The pool captures `this`, so it must not move. The `std::mutex` member makes it non-movable
  automatically.
- Verified under ASan+UBSan and TSan (100 tasks, move-only callables, exception propagation,
  drain-on-destruction).

## Shared state: mutexes, atomics, and condition variables

- `std::scoped_lock lock(m);` for one or more mutexes (deadlock-free acquisition order).
  `std::unique_lock` only when you need to unlock early or wait on a condition variable.
- Keep critical sections tiny: copy or move data out under the lock, then work outside it
  (the pool pops the task under the lock and runs it after releasing).
- `std::atomic<T>` for independent counters and flags. Use the default
  `memory_order_seq_cst` unless you can explain the weaker order in a comment;
  `memory_order_relaxed` only for statistics counters nobody synchronizes on.
- `std::shared_mutex` only after measuring read contention; it's slower than `std::mutex`
  when uncontended.
- `std::latch`/`std::barrier` for phase synchronization, `std::counting_semaphore` for
  bounding concurrency.
- Always wait on a condition variable with a predicate (spurious wakeups).

## Async I/O and std::execution

- **`std::execution` (P2300 senders/receivers) is in C++26, but no standard library ships it
  yet** (GCC 16, libc++ 23, and MSVC 14.51 all lack it, per cppreference). Don't design
  around it today. If you want the model now, NVIDIA's `stdexec` is the reference
  implementation, as an ordinary third-party dependency.
- **Coroutines** (C++20 language feature) are production-ready as a mechanism, but the
  standard gives you no task type. `std::generator` (C++23) is missing from libc++. Use
  coroutines through a library that provides the executor (Asio's `awaitable`).
- For network services, the default is blocking handlers on a thread pool behind
  kamal-proxy. That handles thousands of requests per second on a small VM and is trivial to
  reason about.

## Signals in services

A signal handler may only call async-signal-safe functions, so it can't stop an HTTP server,
lock a mutex, or log. The pattern (verified in `service-main.cpp`):
1. At the top of `main`, before creating any threads, block `SIGTERM`/`SIGINT` with
   `pthread_sigmask`. New threads inherit the mask.
2. A dedicated `std::jthread` calls `sigwait` and then `server.stop()` synchronously.
3. If startup fails after the waiter exists, send yourself `SIGTERM` (`kill(getpid(),
   SIGTERM)`) so the waiter returns and its `jthread` can join. Otherwise `main` hangs in
   the destructor.

kamal-proxy and Docker send `SIGTERM` on deploy; handling it lets in-flight requests finish.

## ThreadSanitizer

- The `tsan` preset builds `RelWithDebInfo` with `-fsanitize=thread`. TSan can't combine with
  ASan (`ProjectOptions.cmake` rejects that at configure time).
- Run the whole test suite under it in CI. Tests must actually exercise concurrency (many
  tasks, several threads) or TSan has nothing to observe.
- On Ubuntu 24.04 GitHub runners, TSan binaries can crash at startup with high mmap ASLR
  entropy; the CI template lowers it with `sysctl vm.mmap_rnd_bits=28` (verify for your
  runner image).
- Uninstrumented dependencies (built by vcpkg without `-fsanitize=thread`) can hide races
  inside them. Races between your own threads are still caught.

## Pitfalls

- Capturing loop variables or locals by reference in a task that outlives the scope. The CLI
  captures `&file` safely only because it `get()`s every future before `opts` dies.
- `std::async` with the default launch policy may run deferred (on `get()`), and its future's
  destructor blocks. Prefer the pool.
- `thread_local` objects with non-trivial destructors in pool threads live until the pool
  dies.
- Calling user callbacks while holding a lock is how deadlocks start.
- `hardware_concurrency()` reports the host's CPUs, not the container's CPU quota. In a
  container, size pools from config (an env var) instead.
