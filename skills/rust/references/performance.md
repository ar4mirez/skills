# Performance

Primary sources: the Cargo profiles reference (https://doc.rust-lang.org/cargo/reference/profiles.html),
the Cargo book's "Optimizing Build Performance" chapter (new in 1.92,
https://doc.rust-lang.org/cargo/guide/build-performance.html), and The Rust
Performance Book (https://nnethercote.github.io/perf-book/).

## Contents
- Workflow: measure first
- Release profile
- Profiling
- Allocation and memory
- Cloning, Arc, and Rc
- Strings and collections
- Async service performance
- Compile times

## Workflow: measure first

1. Write the obvious, idiomatic version.
2. Measure the real workload: a criterion bench for a function, or a load
   test (`oha`, `wrk`, or `k6`) for a service, on a release build.
3. Profile to find where time actually goes.
4. Change one thing, and re-measure against the saved baseline.
5. Keep the change only if the numbers move and the code stays readable.

Never benchmark a debug build: it's 10-100x slower, with a different profile.

## Release profile

From `assets/workspace-Cargo.toml`:

```toml
[profile.release]
lto = "fat"          # cross-crate inlining; about 5-20% faster, slower link
codegen-units = 1    # better optimization, slower build
strip = "symbols"    # smaller binary

[profile.profiling]  # cargo build --profile profiling
inherits = "release"
debug = "line-tables-only"
strip = "none"
```
- `lto = "thin"` gets most of the gain with a much faster link. Use it when
  release builds are on the critical path of development.
- **`panic = "abort"`** shrinks binaries and helps slightly, but it removes
  per-request panic isolation in services. Use it for CLIs only.
- `opt-level = 3` is the release default. `"s"`/`"z"` are for size-constrained
  targets (WASM, embedded).
- `target-cpu=native` makes binaries that crash on older CPUs. For servers,
  pin a known level in `.cargo/config.toml` (`-C target-cpu=x86-64-v3`) only
  if every host supports it.
- PGO (profile-guided optimization, via `cargo-pgo`) gives another 10-20% on
  branchy code. Only for hot, stable binaries.

## Profiling

- **samply** (0.13) is the default: a sampling profiler for macOS, Linux, and Windows
  that opens results in the Firefox Profiler.
  `cargo build --profile profiling && samply record ./target/profiling/acme-api`
- **cargo flamegraph** (flamegraph 0.6.14) wraps `perf` (Linux) or dtrace
  (macOS) and writes an SVG: `cargo flamegraph --profile profiling --bin acme-api`.
- Symbols need `debug = "line-tables-only"` (the `profiling` profile). Since
  1.97, symbols use v0 mangling by default, so update old profilers if names
  show up mangled.
- Allocations: `dhat` (the `dhat` crate, as a global allocator in a test
  build) or heaptrack on Linux.
- Async services: `tokio-console` shows tasks that are busy, idle, or never
  woken (needs `tokio_unstable`). Tracing spans with timings show which awaits
  are slow.
- Compile-time profile: `cargo build --timings` writes an HTML report of crate
  build times.

## Allocation and memory

- Allocation is the usual hidden cost. In hot loops: reuse buffers
  (`clear()` keeps the capacity), preallocate (`Vec::with_capacity`,
  `String::with_capacity`), and avoid `format!` just to build keys.
- Borrow instead of allocate: `&str`/`&[T]` parameters, `Cow<'_, str>` for
  "usually unchanged" transforms, and iterators instead of collecting
  intermediate `Vec`s.
- `Box<[T]>`/`Box<str>` for immutable data you keep a lot of (no spare
  capacity field).
- Small collections: consider `smallvec` or `arrayvec` only after a profile
  shows allocation churn.
- **Global allocator:** glibc's malloc is fine for most services. musl's
  malloc is slow under multi-threaded contention, so static musl builds should
  set a global allocator (`mimalloc` 0.1.52: `#[global_allocator] static GLOBAL:
  mimalloc::MiMalloc = mimalloc::MiMalloc;`). Measure first on glibc.
- `std::mem::size_of::<T>()` for hot enum types: a single large variant makes
  every value large, so `Box` the big variant (clippy's `large_enum_variant`).

## Cloning, Arc, and Rc

- A `.clone()` of a `String`, `Vec`, or `HashMap` is an allocation plus a
  copy. A clone of `Arc<T>`, `PgPool`, `Bytes`, or `reqwest::Client` is a
  refcount increment. Know which one you're writing.
- Share large read-only data across tasks with `Arc<T>` (or `Arc<str>` for
  shared strings), not by cloning the data.
- `Rc` only in single-threaded code: it skips the atomic operations, but it's
  `!Send`, so it can't be used across `tokio::spawn`.
- Clippy pedantic flags needless clones and pass-by-value (`redundant_clone`,
  `needless_pass_by_value`). Take its suggestions seriously in hot code.
- `Arc<Mutex<T>>` shared by many tasks serializes them. Shard the data,
  use `RwLock` for read-heavy data, or use atomics or message passing.

## Strings and collections

- `String` building: `write!(s, ...)` into one buffer (`std::fmt::Write`), not
  repeated `format!` and `+`. 1.98 adds `core::fmt::NumBuffer` and
  `format_into` for allocation-free integer formatting.
- Hashing: the default SipHash resists HashDoS. For hot maps with
  trusted keys (integers, internal ids), `rustc-hash`'s `FxHashMap` is much
  faster. Never use it for attacker-controlled keys.
- `Vec` plus binary search, or sorting once, often beats a `HashMap` for small
  or read-mostly data.
- Iterators compile to the same code as index loops, without bounds checks.
  Prefer them to `get_unchecked`.

## Async service performance

- The usual culprits, in order: blocking calls on the runtime, N+1 queries,
  missing indexes, a pool that is too small (requests queue for connections),
  and serializing through one lock.
- Batch database work (`WHERE id = ANY($1)`), and add indexes for every
  `WHERE`/`JOIN` column that you look up (`EXPLAIN ANALYZE`).
- `tokio::spawn` has a cost; don't spawn per item in tight loops. Use
  `buffer_unordered` or `JoinSet` with a concurrency limit.
- Response compression (tower-http `compression-*` features) usually belongs
  at Cloudflare, not in the app.

## Compile times

- `[profile.dev.package."*"] opt-level = 1` optimizes dependencies once, so
  debug builds of tests and servers run fast without slowing your own
  crate's rebuilds.
- Keep proc-macro-heavy dependencies out of the core crate. Splitting crates
  along real boundaries lets Cargo build them in parallel.
- `cargo build --timings` shows the critical path. `cargo check` in the
  editor loop, and `cargo test` only for the crate you're changing (`-p`).
- Since 1.90, `x86_64-unknown-linux-gnu` links with `lld` by default, so
  there's no need to configure `mold`/`lld` yourself there.
