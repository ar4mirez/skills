# Concurrency and performance

## Contents
- Choosing a threading API
- The house concurrency model
- Atomics and memory order
- Signals and shutdown
- ThreadSanitizer
- Profiling workflow
- Optimization settings: -O2, LTO, PGO
- Allocation and data layout

## Choosing a threading API

**Default: POSIX threads (`<pthread.h>`)** plus C11 `<stdatomic.h>`, linked
with `find_package(Threads)` and `Threads::Threads`.

| API | Use when | Why not by default |
|---|---|---|
| pthreads | Linux, macOS, BSD: every POSIX target | Not on Windows without a shim |
| C11 `<threads.h>` (`thrd_*`, `mtx_*`, `cnd_*`) | glibc/musl/MSVC-only code | **Missing on macOS**, confirmed on the macOS 27 SDK. It also lacks timeouts, attributes, and rwlocks |
| Win32 threads | Windows-only code | Not portable |
| OpenMP | Data-parallel loops in numeric code | A runtime dependency. Not for servers |

`<stdatomic.h>` is portable C11 and available everywhere, including macOS.

## The house concurrency model

1. **Share immutable data; don't lock it.** Build state on one thread, then
   hand out only `const` pointers. `kvstore-server` loads the store once, and
   its worker threads only call `kvstore_get(const kvstore *, ...)`. No locks
   are needed, and `test_concurrent_readers` proves it under TSan.
2. **When state must change, give it one owner.** A single thread owns
   mutable state, and others send it messages over a mutex+condvar queue.
   Share a mutex-protected structure only when that's measurably too slow.
3. **Document thread safety in the header** ("not synchronized; concurrent
   readers are safe once writes are done").
4. **One thread per core is plenty.** Size worker pools from configuration
   (`WORKERS`), not from `sysconf` guesses baked into code. Blocking I/O on N
   threads is simpler than an event loop and fine for thousands of requests
   per second. Reach for `epoll`/`kqueue`, or libuv or libevent, only when
   you need tens of thousands of concurrent connections.
5. **Keep lock order fixed.** Never call user callbacks while holding a lock,
   and keep critical sections free of I/O.

## Atomics and memory order

- Use `atomic_bool stopping`, `atomic_load`, and `atomic_store`. Default
  (`memory_order_seq_cst`) is correct and fast enough for flags and
  counters. Use `memory_order_relaxed` only for statistics counters, and
  acquire/release only for a measured hot path with a written proof.
- `volatile` gives neither atomicity nor ordering. It's for memory-mapped I/O
  and `volatile sig_atomic_t` signal flags only (the audit flags other uses).
- Double-checked locking and hand-rolled lock-free structures are review
  blockers unless they come with a TSan-clean stress test.

## Signals and shutdown

The pattern in `assets/server.c`:
1. Before creating any thread, block `SIGINT` and `SIGTERM` with
   `pthread_sigmask`. Every thread inherits the mask.
2. The main thread calls `sigwait()`, so the signal arrives as an ordinary
   return value. You get no async-signal-safety problems and no `EINTR` in
   workers.
3. Set an atomic `stopping` flag. Workers poll the listening socket with a
   timeout (`poll(..., 250)`) and exit. `pthread_join` them all, then free
   shared state.
4. Ignore `SIGPIPE` (`signal(SIGPIPE, SIG_IGN)`) in network servers, or a
   client that disconnects mid-response kills the process.

Kamal and Docker send `SIGTERM` and wait (10 seconds by default) before
`SIGKILL`. Graceful shutdown must finish within that window.

## ThreadSanitizer

- Use `cmake --workflow`-style `tsan` preset runs: `cmake --preset tsan &&
  cmake --build --preset tsan && ctest --preset tsan`. TSan is incompatible
  with ASan, which is why they're separate presets and the CMake file fails
  fast if both are on.
- Every component that uses threads needs at least one test that actually
  runs threads concurrently. TSan only reports races that execute.
- The reference server was exercised under TSan with 40 concurrent requests
  and a SIGTERM shutdown, with no reports.
- TSan and ASan work with Apple clang 21. MSan (uninitialized reads) is
  Linux + LLVM clang only.

## Profiling workflow

Measure first, then change one thing and measure again.
1. Build `RelWithDebInfo` (optimized, with symbols) and add
   `-fno-omit-frame-pointer` for usable stacks.
2. CPU:
   - **Linux:** `perf record -g ./app …`, then `perf report` or a flame
     graph.
   - **macOS:** `xcrun xctrace record --template 'Time Profiler' --launch
     -- ./app …`, or Instruments.
   - Anywhere: `valgrind --tool=callgrind` for deterministic instruction
     counts (slow).
3. Memory:
   - `heaptrack` (Linux) or `valgrind --tool=massif` for heap growth.
   - `leaks`/Instruments on macOS.
   - ASan's LeakSanitizer (`ASAN_OPTIONS=detect_leaks=1`) finds leaks in
     tests. It's on by default on Linux. On macOS its support is incomplete,
     so rely on Linux CI for leak checks.
4. Micro-benchmarks: a separate executable that runs the operation N times
   between `clock_gettime(CLOCK_MONOTONIC)` calls, stores results in a
   `volatile` sink so they aren't optimized away, and reports the median of
   several runs. Use `hyperfine` for whole-CLI timings. Don't register
   benchmarks as CTest tests.

## Optimization settings

- CMake's default `Release` flags are `-O3 -DNDEBUG`. The OpenSSF guide
  recommends `-O2`. Both are fine: benchmark before changing, and never ship
  `-O0`, because `_FORTIFY_SOURCE` is inert without optimization.
- **LTO:** `include(CheckIPOSupported)`, then
  `check_ipo_supported(RESULT ok)` and
  `set_property(TARGET x PROPERTY INTERPROCEDURAL_OPTIMIZATION ${ok})`. It's
  worth it for executables that link several of your own libraries.
- **PGO** (`-fprofile-generate`/`-fprofile-use`) only for CPU-bound services
  with a representative workload.
- Avoid `-Ofast` and `-ffast-math`, which break IEEE semantics silently.
  Avoid `-march=native` in distributed binaries (it produces illegal
  instructions on older CPUs). Pick an explicit baseline such as
  `-march=x86-64-v2` when needed.

## Allocation and data layout

- The fastest allocation is the one you don't make. Reuse buffers across
  loop iterations, use arenas for per-request memory, and use stack buffers
  for small bounded data.
- Store arrays of structs contiguously (the kvstore slot array), not linked
  lists of individually allocated nodes. Cache misses dominate.
- Open addressing with a power-of-two capacity and a load factor under
  0.75 is the default hash table. Grow by doubling, with checked
  multiplication.
- `restrict` on non-aliasing pointer parameters of hot functions can enable
  vectorization. It's a promise: violating it is UB.
- Don't put `strlen` in loops, `realloc` by +1, or `printf` in hot paths.
  These are the usual profile surprises.
