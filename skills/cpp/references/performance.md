# Performance: measure, then fix

## Contents
- Workflow
- Profilers by platform
- Allocation and memory
- Moves and copies
- Dispatch: virtual vs templates
- Build-level optimizations
- Containers and data layout

## Workflow

1. **Reproduce with a benchmark or a realistic input** on a Release build (`release` preset,
   or `RelWithDebInfo` for symbols). Debug and sanitizer builds are 2 to 20 times slower and
   distort profiles.
2. **Profile to find the hot spot.** Don't guess: in most programs, a handful of functions
   take most of the time, and they're rarely the ones you suspect.
3. **Fix the algorithm or the data layout first,** allocations second, and micro-optimizations
   last.
4. **Re-measure** with google/benchmark (`bench/`) and keep the benchmark to stop regressions.

## Profilers by platform

| Platform | CPU | Allocations / heap |
|---|---|---|
| Linux | `perf record -g --call-graph dwarf ./app` → `perf report` (or a flamegraph via `perf script`) | `heaptrack ./app` → `heaptrack_gui`/`heaptrack_print` |
| macOS | Instruments Time Profiler (`xcrun xctrace record --template 'Time Profiler' --launch -- ./app`) | Instruments Allocations template |
| Windows | Visual Studio Profiler / WPA | VS memory usage tool |
| Anywhere | `valgrind --tool=callgrind` (slow but exact) | `valgrind --tool=massif` |

Build with `-fno-omit-frame-pointer` for reliable stacks with `perf` (it costs about 1%). The
sanitizer presets already set it.

## Allocation and memory

- **Reserve when you know the size:** `rows.reserve(counts_.size())` before a push loop
  avoids log(n) reallocations and copies.
- **Reuse buffers in loops:** `Counter::add` keeps one `std::string word` and `assign`s into
  it per token, instead of constructing a new string each iteration.
- **Heterogeneous lookup** (a transparent hash and `std::equal_to<>`) lets
  `find(std::string_view)` skip building a temporary `std::string`.
- Small-string optimization means strings up to about 15 to 22 characters don't allocate;
  don't hand-roll string pools before profiling.
- `std::vector` beats `std::list`/`std::map` for almost everything below about 10k elements,
  thanks to cache locality. `std::flat_map` (C++23; GCC 15+, libc++ 20+) is a sorted-vector
  map with fast lookup for read-mostly data.
- `std::unordered_map` allocates one node per element. For hot maps, a flat open-addressing
  map (Abseil `flat_hash_map`, Boost `unordered_flat_map`) is 2 to 5 times faster; add the
  dependency only after profiling.
- `std::pmr::monotonic_buffer_resource` for per-request arenas when allocation shows up in
  the profile.
- `std::string_view`/`std::span` parameters avoid copies, within their lifetime rules.

## Moves and copies

- Sink parameters by value and `std::move` into place. Return locals by value (NRVO or an
  implicit move); **don't `return std::move(local);`**, because it disables copy elision.
- Mark move constructors and move assignment `noexcept` (or keep them defaulted):
  `std::vector` only moves elements on reallocation if the move can't throw.
- `const` locals can't be moved from; don't make a variable `const` if you intend to move it
  out.
- `emplace_back` builds in place; with an already constructed object, `push_back(std::move(x))`
  is identical.
- Watch for accidental copies in range-for (`for (auto x : big_things)`) and in lambdas
  capturing by value; clang-tidy `performance-*` flags many of these.

## Dispatch: virtual vs templates

- A virtual call costs an indirect branch, and it blocks inlining, which is the real cost in
  tight loops. It's irrelevant at the boundaries of I/O, request handling, or plugins.
- Use **virtual interfaces** for runtime-chosen implementations (plugins, test seams at module
  boundaries), and **templates or concepts** for inner loops where inlining matters
  (comparators, visitors, numeric kernels).
- `std::variant` + `std::visit` for a closed set of types: no heap, and the compiler sees all
  alternatives.
- Mark leaf classes `final` so the compiler can devirtualize.
- Templates cost compile time and binary size; keep them in headers only when callers need
  them, and put the non-generic core in a `.cpp`.

## Build-level optimizations

- The release preset enables IPO/LTO (`CMAKE_INTERPROCEDURAL_OPTIMIZATION ON`, which became
  `-flto=thin` with Apple clang). Verified to build warning-free.
- `-O2` is the OpenSSF baseline; CMake's Release uses `-O3`. Keep `-O3` unless code size
  matters.
- `-march=native` only for binaries built and run on the same machine; containers built in CI
  run on unknown CPUs. Use `-march=x86-64-v2`/`-v3` only if every production host supports
  it.
- PGO (`-fprofile-generate` / `-fprofile-use`, or Clang's `-fprofile-instr-*`) gives 5 to 20%
  on branchy code; worth it for a hot service with a representative workload.
- Hardening costs: `_LIBCPP_HARDENING_MODE_FAST` and `-fstack-protector-strong` are low
  single-digit percent; benchmark before disabling them, never disable them by default.

## Containers and data layout

- Structure-of-arrays for hot numeric loops; array-of-structs for object-at-a-time code.
- Keep hot data contiguous and small: reorder members from largest to smallest to reduce
  padding, and use an `enum class` with `std::uint8_t` as the underlying type.
- Avoid false sharing between threads: pad per-thread counters to
  `std::hardware_destructive_interference_size` (from `<new>`, where available), or better,
  accumulate thread-locally and merge once.
- `std::endl` flushes; `'\n'` doesn't. For bulk output, build a string (`std::format_to`) and
  write it once, as `render()` does.
