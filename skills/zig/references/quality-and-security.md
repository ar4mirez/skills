# Quality gate, CI, sanitizers, and security

## Contents
- The gate (zero warnings)
- GitHub Actions template
- Static analysis without a linter
- Sanitizers and runtime checks
- Security checklist
- Dependency hygiene
- Review checklist (severity-ranked)

## The gate (zero warnings)

Zig has **no official linter**. The compiler is strict (unused locals and parameters,
never-mutated `var`, and ignored results are all errors), so the gate is:

```bash
zig fmt --check .                                   # formatting (fails on any diff)
zig build test                                      # Debug: every safety check
zig build test -Doptimize=ReleaseSafe               # release codegen, checks on
zig build test -Doptimize=ReleaseFast               # exposes reliance on checked behavior
zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSafe    # each shipped target builds
python3 scripts/audit.py . --fail-on medium         # this skill's anti-pattern + old-API scan
```

**Why several modes:** Zig analyzes lazily, so code that no build references is never
compiled at all. Different modes and targets reach different `if (builtin.mode ...)` and
`switch (builtin.os.tag)` branches. A function that isn't called anywhere can hold a type
error nobody sees. The tests are what reference your code.

## GitHub Actions template

`assets/github-ci.yml` (copy to `.github/workflows/ci.yml`):
- `mlugg/setup-zig@v2` with no version pinned in the workflow; it reads
  `minimum_zig_version` from `build.zig.zon` and caches the Zig caches;
- a matrix of `ubuntu-latest` and `macos-latest`, running fmt, tests in
  Debug/ReleaseSafe/ReleaseFast, and musl cross builds for x86_64 and aarch64;
- a bounded fuzz job: `zig build test --fuzz=100K -Doptimize=ReleaseSafe` (Debug fuzz
  builds don't compile in 0.16.0).

## Static analysis without a linter

- `zig build` with `--error-style minimal` for readable CI logs. `-freference-trace` shows
  why a declaration was analyzed when a compile error surfaces deep in a generic.
- ZLS, with build-on-save, for editor diagnostics.
- `scripts/audit.py` catches what the compiler can't:
  - removed APIs, with their 0.16 replacements (so an agent-written snippet fails review,
    not the build);
  - `catch unreachable` and `catch {}`;
  - global allocators;
  - arenas without `deinit`;
  - buffered writers without `flush`;
  - manifest and Dockerfile mistakes.
- Keep ownership visible: every `alloc`, `dupe`, or `create` has a `defer` or `errdefer`
  on the next line, or a doc comment saying who frees it.

## Sanitizers and runtime checks

- **Zig's own safety checks** (Debug and ReleaseSafe) are the main sanitizer: bounds,
  integer overflow, `unreachable`, null unwrap, wrong union field, invalid enum value,
  and misaligned `@ptrCast`. The `DebugAllocator` also reports double frees and leaks
  with stack traces.
- **C code compiled by Zig** (`addCSourceFile`, `zig cc`) gets UBSan in Debug by default.
  Module option `.sanitize_c = .full` (runtime with messages) or `.trap` (smaller; SIGILL),
  or `-fsanitize-c=trap|full` on the CLI.
- **ThreadSanitizer:** module option `.sanitize_thread = true` or `-fsanitize-thread`.
  Run it on Linux CI. On this macOS 27 host it failed to build libtsan (the libcxx
  sub-compilation failed), so verify it for your platform.
- **Valgrind:** Debug builds include valgrind client requests (`-fvalgrind` for release),
  so `valgrind ./zig-out/bin/app` understands Zig allocations. Linux only.
- The leak-checking `DebugAllocator` in tests (`std.testing.allocator`) catches more leaks
  than any external tool. Make it non-negotiable.

## Security checklist

- **Ship ReleaseSafe.** Bounds and overflow checks turn memory-safety bugs into crashes.
  Use ReleaseFast only for a measured hot path; `@setRuntimeSafety(false)` is scoped,
  commented, and tested.
- **Bound every input:** maximum line and record sizes (the reader buffer),
  `allocRemaining(..., .limited(max))`, `Options.max_word_len`-style limits, and
  `content_length` checks before reading HTTP bodies. Untrusted sizes never size an
  allocation directly.
- **Integer handling:** use `std.math.add/mul/cast` (which return `error.Overflow` or
  `null`) for arithmetic on untrusted values. Plain `+` is checked in ReleaseSafe (a panic
  is still a DoS), `+%` wraps silently, and `@intCast` panics in safe modes.
- **Never assert on input.** `std.debug.assert` is an optimizer assumption in ReleaseFast;
  validate and return an error instead.
- **Pointer lifetimes:** slices from `takeDelimiter`/`peek` (reader buffer), map
  iterators, `ArrayList.items` (invalidated on growth), and `request.head` strings
  (invalidated by reading the body) must not be kept.
- **Randomness:** use `io.randomSecure` for keys and tokens (a fresh syscall each time),
  and `std.crypto` for primitives (AEADs, including the new AES-GCM-SIV and Ascon). Never
  hand-roll crypto.
- **Secrets:** read them from the environment in `main` (`init.environ_map`, injected by
  Kamal `env.secret`). Never put them in build options, `@embedFile`, or logs. Zero
  sensitive buffers with `std.crypto.secureZero`.
- **C boundary:** validate lengths and nulls at `export fn` entry, never let Zig errors or
  panics cross into C (map them to status codes), and document who frees what.
- **Archives and paths:** `std.tar` now sanitizes path traversal. For your own path
  joins, reject `..` and absolute components from untrusted input.

## Dependency hygiene

- There's no official vulnerability database or `audit` command for Zig packages. Keep
  dependencies few, pinned by hash (`zig fetch --save` with a tag or commit URL), and
  reviewed. In 0.16, `zig-pkg/` puts their source in-tree, so grep it.
- Prefer std. Add a package only when it saves real work (TLS server, database driver,
  big protocols), and check that its `build.zig.zon` supports your Zig version.
- Update deliberately: bump the tag, run `zig fetch --save <new-url>`, run the full gate,
  and read the dependency's changelog. Use `zig build --fork=../checkout` to test a patched
  dependency without editing the manifest.
- C dependencies you vendor through the build system are yours to patch. Track their
  CVEs (OSV) manually.

## Review checklist (severity-ranked)

**High**
1. Removed or old APIs (`std.io`, `std.fs.cwd`, `GeneralPurposeAllocator`,
   `root_source_file` on artifacts, `usingnamespace`, `async`, `@Type`): the code doesn't
   build on 0.16.
2. Unbounded reads or allocations from untrusted input; missing body or line limits.
3. Use after free or dangling slices (buffer-backed slices kept, `head` strings after the
   body is read, container growth).
4. `catch unreachable`, or `assert`, on anything that can actually happen.
5. A Debug or ReleaseFast service build; a `build.zig.zon` without a fingerprint or hash.

**Medium**
6. Missing `errdefer` on the error path (run `checkAllAllocationFailures`).
7. Tests that don't use `std.testing.allocator`; missing test step; untested modules.
8. `catch {}` swallowing errors; `anyerror` in public APIs.
9. Missing `flush()`; `std.debug.print` in library code.
10. Shared mutable state across `Io` tasks without `Io.Mutex`; unbounded
    `io.concurrent` per connection with no cap or proxy in front.

**Low**
11. Deprecated aliases (`ArrayListUnmanaged`, `indexOf`, `@cImport`), naming, and doc
    comments on ownership.
