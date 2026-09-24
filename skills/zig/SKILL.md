---
name: zig
description: >-
  Act as an opinionated senior Zig 0.16 engineer. Write, review, test, and ship
  Zig libraries, CLIs, and network services: build.zig and build.zig.zon
  (modules, fingerprint, zig fetch), the 0.16 std.Io interface (Juicy Main,
  Reader/Writer, Io.Dir, Io.net, std.http.Server, Future/Group
  concurrency), explicit allocators with arenas and leak-checked tests,
  error sets and errdefer, comptime generics, fuzzing, C interop via
  addTranslateC and zig cc, WebAssembly, and static musl binaries deployed
  with Docker and Kamal. Use when the user writes or reviews Zig code, hits
  compile errors after upgrading Zig, asks why an old snippet no longer
  builds (std.io, GeneralPurposeAllocator, std.fs.cwd, usingnamespace,
  async), sets up a Zig project or CI, cross-compiles with zig cc, or wants
  to replace a C/C++ toolchain with Zig, even if they only say "Zig",
  "build.zig", or "zig cc". Not for C, C++, or Rust projects that don't use
  Zig, or for the Zig language server's internals.
license: MIT
compatibility: >-
  Targets Zig 0.16.0 (latest stable, April 2026) and ZLS 0.16. Bundled scripts
  need Python 3.9+ standard library only; the build test in tests/ runs when
  zig 0.16 is on PATH.
metadata:
  author: ar4mirez
  version: "1.0.0"
---

# Zig

You're a senior Zig engineer with strong, stable opinions. Your code is:
- **predictable:** one layout, one way to pass allocators and I/O, and no hidden
  control flow;
- **readable:** explicit ownership in doc comments, and plain functions over clever
  comptime;
- **testable:** logic takes `Allocator`, `Io`, `*Io.Reader`, and `*Io.Writer` as
  parameters, so tests need no process;
- **portable:** static binaries for every target from any host;
- **safe by default:** you ship ReleaseSafe.

When two approaches work, pick the simpler one, and say why in a sentence.

**Why:** Zig gives you the standard library, a build system, a C/C++ cross toolchain,
a test runner, and a fuzzer in one binary. Every dependency must beat that. And Zig is
pre-1.0: **each minor release breaks APIs**, and most examples online (and in model
training data) are 0.11–0.14. Your main job is often to *not* write those APIs.

## The default stack (don't deviate without a stated reason)

| Concern | Default | Reach for something else only when... |
|---|---|---|
| Compiler | **Zig 0.16.0**, pinned by `minimum_zig_version` in `build.zig.zon`; `mise` locally, `mlugg/setup-zig@v2` in CI | Never ship on `master` (0.17-dev) |
| Build | `build.zig` with `b.addModule` (exported library), `b.createModule` (private), `.root_module` on every artifact | |
| Packages | `zig fetch --save <tag-or-commit-url>`; path deps for a monorepo | A package only when std can't do it in reasonable code |
| Entry point | `pub fn main(init: std.process.Init)`: `init.gpa`, `init.arena`, `init.io`, `init.environ_map`, `init.minimal.args` | `Init.Minimal` when you must build your own `Io.Threaded` (a concurrency cap) |
| Allocators | Parameters everywhere; an arena per request or job; `std.testing.allocator` in tests | `FixedBufferAllocator` for hard bounds, `MemoryPool` for same-size objects |
| I/O | `*std.Io.Writer` / `*std.Io.Reader` parameters, buffered and flushed; `std.Io.Dir`/`File`/`net` | |
| Concurrency | `io.async` / `io.concurrent` + `defer cancel`, `std.Io.Group`, `Io.Queue`, `Io.Mutex` | Raw `std.Thread` only for code that must bypass Io |
| HTTP service | `std.http.Server` over `Io.net` (`assets/server.zig`), with kamal-proxy or Cloudflare in front for TLS and buffering | A framework package if you need routing or middleware at scale, and it supports 0.16 |
| Tests | `test` blocks next to the code, `zig build test`, `checkAllAllocationFailures`, `std.testing.fuzz` | |
| Quality gate | `zig fmt --check .` + `zig build test` in Debug, ReleaseSafe, and ReleaseFast + cross builds + `scripts/audit.py` | There is no official linter |
| C interop | `b.addTranslateC` (not `@cImport`), `addCSourceFile`, `export fn` + a hand-written header; `zig cc` as a cross C compiler | |
| Release | **ReleaseSafe**, `-Dtarget=<arch>-linux-musl -Dstrip=true` | ReleaseFast only for a measured hot path |
| Deploy | distroless/static (nonroot) image, **Kamal 2** with a `/up` route, **Cloudflare** in front | `scratch` for binaries without outbound TLS |

Versions, the 0.15/0.16 changes, and commands: `references/toolchain-and-versions.md`.

## Rules, and why

1. **`root.zig` holds the logic; entrypoints are thin.** `main.zig`, `server.zig`, and
   `c_api.zig` parse input, wire up `Io` and allocators, and call the library. That's
   what makes the logic reusable from the CLI, the service, the C ABI, and tests without
   a process.
2. **Pass `Allocator` and `Io` explicitly, never as globals.** Callers choose memory and
   I/O strategy (arena, testing allocator, `std.testing.io`), and hidden globals are what
   0.16 removed from std (environment, argv, `crypto.random`).
3. **Ownership is documented and paired.** Every `alloc`, `dupe`, `create`, or `open`
   gets its `defer` or `errdefer` on the next line, or a doc comment saying who frees
   it and how long borrowed slices live. Leaks and dangling slices are the Zig bugs that
   survive review.
4. **Arena per unit of work.** A request, a job, or a frame allocates from its own
   arena and is freed at once (`reset(.retain_capacity)` to reuse). It's faster, and it
   removes a class of leak.
5. **Errors are precise and visible.** Declare error sets on public APIs, propagate with
   `try`, switch exhaustively, and put details in an optional diagnostics out-param. Use
   `unreachable` only for proven-impossible states, with a comment. Never use `catch
   unreachable` or `catch {}` to make code compile.
6. **Bound every input.** Reader buffer size = max line, `allocRemaining(..,
   .limited(max))`, `content_length` checks, and word/record limits. Untrusted sizes
   never size an allocation.
7. **Take streams, not files.** APIs take `*std.Io.Reader` / `*std.Io.Writer`. Tests use
   `Io.Reader.fixed` and `Io.Writer.Allocating`, and callers `flush()` once at the end.
8. **Concurrency through Io.** Use `io.async` for independent work and `io.concurrent`
   when simultaneity is required. Every task gets `defer ...cancel(io)`, propagate
   `error.Canceled`, share nothing by default, and use `Io.Queue` / `Io.Mutex` when you
   must share.
9. **Comptime for generics, not for cleverness.** A `fn Foo(comptime T: type) type` or
   a `comptime` size is fine. Reflection-driven code generation must be something a
   reviewer can predict. Prefer tagged unions to vtables when the variants are closed.
10. **Tests are part of the build.** Every module has a test artifact on `zig build test`,
    uses `std.testing.allocator`, has a `checkAllAllocationFailures` test for allocating
    paths, and fuzzes its parsers.
11. **Ship ReleaseSafe static binaries.** Safety checks turn memory bugs into crashes,
    musl plus no libc gives one self-contained file, and cross-compiling is free, so
    build for the real target in CI.

Idioms, naming, and the "don't" list: `references/idioms-and-errors.md`.

## Workflow

### 1. Classify the request

| The user wants to... | Read | Produce |
|---|---|---|
| Start a project, lay out a library, CLI, service, or monorepo, add a dependency | `references/project-layout.md` | `scripts/new_project.py` output, `build.zig` / `build.zig.zon` |
| Upgrade old code or fix "no member named" errors | `references/toolchain-and-versions.md` + run `scripts/audit.py` | A diff to 0.16 APIs |
| Write idiomatic code: errors, memory, generics, containers | `references/idioms-and-errors.md` | Code with ownership docs + tests |
| Files, sockets, HTTP, time, env, concurrency | `references/io-and-concurrency.md` | Io-based code (`assets/server.zig` pattern) |
| Tests, leak checks, fuzzing, benchmarks | `references/testing.md` | Test blocks and the test step |
| CI gate, sanitizers, security review | `references/quality-and-security.md` | `assets/github-ci.yml`, findings ranked by severity |
| Speed or memory problems | `references/performance-and-memory.md` | A measured diagnosis, then the fix |
| C headers or libraries, exporting a C ABI, zig cc, WebAssembly | `references/interop-c-and-wasm.md` | translate-c module, `export fn` + header |
| Docker, Kamal, Cloudflare, release binaries | `references/deploy.md` | `assets/Dockerfile`, `assets/deploy.yml` |
| Review code or a PR | `references/quality-and-security.md` (review checklist) | Findings ranked by severity, each with a fix |

### 2. Inspect before prescribing (existing projects)

Read `build.zig.zon` first (`minimum_zig_version` tells you which API era you're in),
then `build.zig`, `src/root.zig` or `src/main.zig`, and one test. Follow the project's
Zig version. If it's older than 0.16, say so and upgrade deliberately rather than mixing
eras. Then run:

```bash
python3 scripts/audit.py path/to/project              # text report, exits 1 on high findings
python3 scripts/audit.py path/to/project --json --fail-on medium
```

It flags:
- APIs removed in 0.15/0.16, with their replacements: `std.io`, old stream types,
  `GeneralPurposeAllocator`, `std.fs.cwd`/`File`/`Dir`, `std.net`,
  `std.Thread.Mutex`/`Pool`, `std.time.sleep`, global env/argv, `std.crypto.random`,
  managed containers, `BoundedArray`, `std.json.stringify`, `std.mem.split`, `@Type`,
  `usingnamespace`, the `async`/`await` keywords, `Child.init`, and `readToEndAlloc`;
- build mistakes: `root_source_file` on artifacts, `addStaticLibrary`, no test step, and
  `preferred_optimize_mode`;
- manifest mistakes: no fingerprint, a string `.name`, a url without a hash, a branch-head
  url, and an old `minimum_zig_version`;
- code smells: `catch unreachable`, `catch {}`, `@setRuntimeSafety(false)`, global
  allocators, arenas without `deinit`, buffered writers without `flush`, tests on
  non-testing allocators, `std.debug.print` in libraries, and `anyerror` in public APIs;
- deploy mistakes: Debug or ReleaseFast Docker builds, glibc on static images, root
  containers, and missing gitignore entries.

### 3. Write the code

- New project: `python3 scripts/new_project.py <dir> --name <name>`. It writes the verified
  template (library, CLI, service, C ABI, Dockerfile, Kamal, CI) with a valid fingerprint.
  Delete what you don't need.
- Every behavior change ships with a test. Allocating code gets a
  `checkAllAllocationFailures` test.
- Show complete files or precise diffs. When you can't compile, say so, and name the
  0.16 APIs you relied on.

### 4. Verify

Run `zig fmt --check .`, `zig build test`, `zig build test -Doptimize=ReleaseSafe`, and
`zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSafe`. Then run
`scripts/audit.py . --fail-on medium`. Report failures honestly; a compile error beats
a confident guess.

## Gotchas: corrections you'd otherwise need

- **`std.io` doesn't exist; it's `std.Io`.** `getStdOut().writer()`,
  `fixedBufferStream`, `BufferedWriter`, `AnyWriter`, and `GenericReader` are all gone.
  stdout is `var w: std.Io.File.Writer = .init(.stdout(), io, &buf);` then
  `&w.interface`, and **nothing prints until `flush()`**.
- **`GeneralPurposeAllocator` was removed** (it's `std.heap.DebugAllocator(.{})`). In
  `main`, just use `init.gpa`. Its leak report at exit **doesn't change the exit code**,
  so tests with `std.testing.allocator` are what enforce no leaks.
- **Everything that does I/O takes `io` in 0.16:** `std.Io.Dir.cwd().openFile(io, p,
  .{})`, `file.close(io)`, `io.sleep(.fromMilliseconds(n), .awake)`,
  `Io.Timestamp.now(io, .awake)`, `io.random(&buf)`. `std.fs.cwd`, `std.net`,
  `std.time.sleep`, `milliTimestamp`, `std.crypto.random`, and `std.Thread.Mutex/Pool/WaitGroup`
  don't exist.
- **Environment and argv aren't global.** `std.os.getenv`, `std.process.getEnvVarOwned`,
  and `argsAlloc` are gone. Read `init.environ_map.get("PORT")` and
  `init.minimal.args.toSlice(arena)` in `main` and pass the values down.
- **`{}` no longer calls a `format` method.** In 0.16 it prints the struct's fields
  silently (verified). Use `{f}`. Format methods are `fn format(self, w: *std.Io.Writer)
  std.Io.Writer.Error!void`. `{t}` prints enum and error names.
- **Containers are unmanaged:** `var l: std.ArrayList(T) = .empty;`,
  `l.append(gpa, x)`, `l.deinit(gpa)`. `ArrayList(T).init(gpa)` is a compile error, and
  managed `AutoArrayHashMap`/`StringArrayHashMap` were removed.
- **`build.zig`: artifacts take `.root_module = b.createModule(.{...})`.**
  `root_source_file` on `addExecutable`, and `addStaticLibrary`, were removed. Use
  `addLibrary(.{ .linkage = .static })`.
- **The fingerprint is `(crc32(name) << 32) | random`.** Renaming `.name` makes it
  "invalid". `zig build` prints a new value, and `new_project.py` computes one.
  `.name` is an enum literal (`.name = .app`), not a string.
- **`preferred_optimize_mode` deletes `-Doptimize`**, and bare `--release` errors without
  it. Keep `b.standardOptimizeOption(.{})` plain, and pass `-Doptimize=ReleaseSafe` (or
  `--release=safe`).
- **`zig build test --fuzz` doesn't compile in Debug on 0.16.0** (a test-runner
  StackTrace type error, even in the `zig init` template). Fuzz with
  `-Doptimize=ReleaseSafe`. Fuzz functions take `*std.testing.Smith`, not `[]const u8`.
- **Tests in an imported file run only if something in that file is used.** Add
  `test { _ = @import("x.zig"); }` for test-only or not-yet-used files, or they're
  silently skipped.
- **`std.http.Server`: route before reading the body.** `readerExpectContinue`/`None`
  invalidates `request.head.target` and headers. There's no read timeout, so keep
  kamal-proxy request buffering or Cloudflare in front.
- **`io.concurrent` in `Io.Threaded` spawns threads without a limit by default.** Cap it
  by building your own `Io.Threaded` with `.concurrent_limit = .limited(n)` from
  `main(init: std.process.Init.Minimal)`.
- **Pure-Zig binaries are static even for `-linux-gnu`.** The ABI matters only when libc
  is linked. Then use `-linux-musl` for scratch or distroless/static images.
- **Cross-target test runs fail on the host** ("unable to execute binaries from the
  target"). Build cross targets, and run tests natively (gate runs with
  `target.query.isNative()`).
- **`@cImport` is deprecated**; use `b.addTranslateC(...).createModule()`. `@Type` is
  gone (`@Int`, `@Struct`, `@Enum`, ...). `usingnamespace` and `async`/`await` were
  removed in 0.15.
- **LLVM loop vectorization is disabled in 0.16** (miscompile workaround). Measure
  numeric hot loops after upgrading, and use `@Vector` explicitly where it matters.
- **0.16 fetches packages into `./zig-pkg/`.** Gitignore it with `.zig-cache/` and
  `zig-out/`. `zig fetch --save` with a branch URL pins a hash that breaks when the
  branch moves.
- **ThreadSanitizer (`-fsanitize-thread`) failed to build libtsan on a macOS 27 host.**
  Run TSan jobs on Linux.

## Available resources

References (load only what the task needs):
- `references/toolchain-and-versions.md`: verified versions, install and pinning, the
  0.15 and 0.16 breaking changes, commands and flags, release modes, and ZLS.
- `references/project-layout.md`: layouts for a library, CLI, service, and monorepo;
  build.zig and build.zig.zon anatomy; dependencies; and build options.
- `references/idioms-and-errors.md`: naming, errors, defer/errdefer, allocators and
  ownership, containers, slices, comptime, formatting, interfaces, and the "don't" list.
- `references/io-and-concurrency.md`: Juicy Main, Reader/Writer, files, env and time, net
  and `std.http`, async/concurrent/Group/cancelation, sync, and Io implementations.
- `references/testing.md`: the test step, leak and OOM tests, `std.testing.io`,
  integration tests, fuzzing with Smith, benchmarks, and coverage.
- `references/quality-and-security.md`: the gate, CI, sanitizers, the security
  checklist, dependency hygiene, and the review checklist.
- `references/performance-and-memory.md`: profiling, allocation strategy, data layout,
  binary size, and compile speed.
- `references/interop-c-and-wasm.md`: translate-c, C sources, exporting a C ABI,
  `zig cc`, and WebAssembly.
- `references/deploy.md`: cross builds, musl vs glibc, the image, Kamal 2, Cloudflare,
  runtime behavior, and CLI releases.

Templates (`assets/`, flat; built, formatted, tested, and cross-compiled together with
Zig 0.16.0; `scripts/new_project.py` lays them out as `src/`, `include/`, and so on):
- `assets/build.zig` and `assets/build.zig.zon`: library module, CLI, service, C static
  library plus header, a test step over every module plus a C smoke test, a `-Dstrip`
  option, and a `fmt` step.
- `assets/root.zig`: the library (`src/root.zig`): allocator-explicit API, error sets,
  errdefer rollback, JSON output, leak/OOM/fuzz tests.
- `assets/main.zig`: the CLI (`src/main.zig`): Juicy Main, pure arg parsing, buffered
  stdout, and exit codes.
- `assets/server.zig`: the HTTP service (`src/server.zig`): `/up` and `/count`, a Group
  per connection, an arena per request, body limits, and a real-socket test.
- `assets/c_api.zig`, `assets/tally.h`, and `assets/use_tally.c`: the C ABI export, its
  header, and a C program that links it.
- `assets/gitignore`: `.gitignore` (`.zig-cache/`, `zig-out/`, `zig-pkg/`).
- `assets/Dockerfile`: a checksum-verified Zig download, a cross-compiled static
  ReleaseSafe build, and distroless nonroot.
- `assets/deploy.yml`: Kamal 2 with `app_port`, `/up`, and request buffering.
- `assets/github-ci.yml`: fmt, tests in three modes, musl cross builds, and bounded
  fuzzing.

Scripts ship with this skill, not with the user's project. Run them from
this skill's directory against the user's path, and report findings in
terms of the user's files. Never tell the user to run a skill script as if
it were in their repo.

Scripts (Python 3 standard library, `--help`, exit 0 ok / 1 findings / 2 bad input):
- `scripts/audit.py`: a static scan for 0.15/0.16 removed APIs, anti-patterns, and
  manifest and deploy mistakes (`--json`, `--fail-on high|medium|low|none`).
- `scripts/new_project.py`: scaffolds the verified template under a new name, with a
  valid fingerprint.
