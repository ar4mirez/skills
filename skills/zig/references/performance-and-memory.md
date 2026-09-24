# Performance and memory

Measure first. Zig makes costs visible (every allocation takes an allocator, and every
copy is explicit), so most speedups come from allocating less and touching less memory,
not from clever code.

## Contents
- Workflow
- Build modes and the 0.16 vectorization caveat
- Profiling
- Allocation strategy
- Data layout
- Binary size
- Compile-time performance

## Workflow

1. Write a reproducible benchmark or load test (a `bench` exe in ReleaseFast, or
   `hyperfine` / `oha` against the binary).
2. Profile the **release** build, with frame pointers kept.
3. Fix the top item: usually allocation churn, copying, or a bad data layout.
4. Keep a regression check (the benchmark in CI, or at least in the PR description).

## Build modes and the 0.16 vectorization caveat

- Ship **ReleaseSafe**. Measure ReleaseFast as well: when the gap matters, find the hot
  function and disable safety only there (`@setRuntimeSafety(false)` in that block, with
  a test covering its edge cases). Don't switch the whole service to ReleaseFast.
- **LLVM loop auto-vectorization is disabled in Zig 0.16** (a workaround for a
  miscompilation; the release notes expect it back in 0.18). Tight numeric loops can be
  slower than on 0.15. If a loop matters, vectorize it explicitly with `@Vector(N, T)`
  (runtime indexing into vectors is now forbidden, so coerce to an array to iterate), or
  measure before and after upgrading.
- `-Dcpu=native` (or `-mcpu` on the CLI) tunes for the build machine. Use it only for
  binaries that run on the same CPU family. The default is a baseline CPU, which is
  portable.

## Profiling

- **Linux:** `perf record -g --call-graph=fp ./zig-out/bin/app` then `perf report`.
  Build with `.omit_frame_pointer = false` on the module (or `-fno-omit-frame-pointer`)
  so stacks are complete, and keep symbols (don't pass `-Dstrip`).
- **Valgrind / callgrind** for instruction-level costs; Debug builds carry valgrind
  client requests, `-fvalgrind` adds them to release.
- **macOS:** Instruments (Time Profiler) on the release binary.
- **Allocation profiling:** wrap the allocator in a counting allocator in a benchmark, or
  compare `DebugAllocator` stats. The cheapest win is usually "don't allocate in the loop".
- Time a region in code: `const t0 = std.Io.Timestamp.now(io, .awake);` …
  `std.log.info("took {f}", .{t0.untilNow(io, .awake)});`.

## Allocation strategy

| Situation | Allocator |
|---|---|
| Process lifetime (config, parsed args) | `init.arena` |
| Per request, job, or frame | `std.heap.ArenaAllocator` on `init.gpa`, `reset(.retain_capacity)` between uses |
| Hard upper bound known ahead of time | `std.heap.FixedBufferAllocator` over a stack or static buffer |
| Many same-size objects, freed individually | `std.heap.MemoryPool(T)` (unmanaged in 0.16: `.empty`, and pass the allocator to `create`) |
| General long-lived heap | `init.gpa` (`smp_allocator` in ReleaseFast/Small without libc; `c_allocator` when libc is linked) |
| Tests | `std.testing.allocator` |

- Reuse capacity: `list.clearRetainingCapacity()`, `map.clearRetainingCapacity()`,
  `arena.reset(.retain_capacity)`.
- Reserve before a loop (`try list.ensureTotalCapacity(gpa, n)`), then use
  `appendAssumeCapacity` inside it.
- Stream instead of loading: pass `*std.Io.Reader` through, and size the buffer to the
  largest record, not the file.
- `std.heap.page_allocator` is a syscall per allocation, rounded up to a page. Use it only
  as the backing allocator for an arena.
- `ArenaAllocator` is thread-safe and lock-free in 0.16, so one arena can be shared by
  tasks that finish together.

## Data layout

- Struct of arrays for hot iteration: `std.MultiArrayList(T)` stores each field
  contiguously.
- Use indices (`u32`) instead of pointers into growable arrays. They survive
  reallocation, are half the size, and serialize trivially.
- Store small enums and bools compactly (`packed struct` for flags). Look at the size
  with `@sizeOf`.
- Keep hot loops free of `anytype` dispatch and vtable calls when profiles show them.
  `comptime` parameters specialize the code.

## Binary size

Measured with the reference service (`tallyd`, a static musl build):

| Build | Size |
|---|---|
| ReleaseSafe, x86_64, with debug info | ~4.0 MB |
| ReleaseSafe, aarch64, `-Dstrip=true` | ~300 KB |

`-Dstrip=true` (a module `.strip` option wired in `assets/build.zig`) is the big lever.
`ReleaseSmall` shrinks further, but drops safety checks.

## Compile-time performance

- `zig build -fincremental --watch` gives near-instant rebuilds. It's still opt-in and
  has known bugs in 0.16, so use it for the edit loop, not for release builds.
- Debug builds use the self-hosted x86_64 backend (fast compiles). The aarch64 backend is
  unfinished, so Debug on ARM uses LLVM and compiles more slowly.
- `zig build --time-report` shows where compile time goes (it opens the web UI).
- Heavy `comptime` (large `inline for`, reflection over big types) costs compile time
  on every build. Keep it proportional.
