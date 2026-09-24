# Toolchain and versions

Verified on 2026-09-24 against the Zig download index, the 0.16.0 and 0.15.1 release
notes, the 0.16.0 language reference, and the 0.16.0 std source.

## Contents
- Versions to target
- Installing and pinning
- What changed in 0.15 and 0.16 (the parts agents get wrong)
- Everyday commands and flags
- Release modes
- Editor support (ZLS)
- Sources

## Versions to target

| Tool | Version | Notes |
|---|---|---|
| Zig | **0.16.0** (released 2026-04-13) | Latest stable. `master` is 0.17.0-dev; don't ship on it |
| LLVM / Clang (`zig cc`) | 21.1 / Clang 21.1.8 | Bundled; no system LLVM needed |
| musl (static Linux) | 1.2.5 + security backports | Many functions now come from Zig's own libc |
| glibc (cross targets) | up to 2.43 | Pick a floor with `-Dtarget=x86_64-linux-gnu.2.31` |
| ZLS | 0.16.0 | Match the ZLS minor version to the compiler |
| `mlugg/setup-zig` | v2 | Reads `minimum_zig_version` from `build.zig.zon` |

Zig is pre-1.0: **every minor release breaks APIs**. State the version in
`build.zig.zon` (`.minimum_zig_version = "0.16.0"`), and read code examples by version.
Most snippets on the web are 0.11–0.14 and won't compile on 0.16.

## Installing and pinning

- Local: `mise use zig@0.16.0` (writes `.mise.toml`) or the tarball from
  ziglang.org/download. One binary plus `lib/`; there's nothing else to install.
- CI: `mlugg/setup-zig@v2` with no `version`. It reads `minimum_zig_version` and caches the
  global cache.
- Docker: download the official tarball and check its SHA-256 from
  `https://ziglang.org/download/index.json` (see `assets/Dockerfile`). There's no official
  Zig image.

## What changed in 0.15 and 0.16 (the parts agents get wrong)

**0.15 (August 2025)**
- **"Writergate":** `std.io` readers and writers were replaced by the non-generic
  `std.Io.Reader` and `std.Io.Writer`. The buffer lives in the interface, so you must
  `flush()`. `BufferedWriter`, `CountingWriter`, `fifo`, `RingBuffer`, and `BoundedArray`
  were deleted.
- Format methods are `pub fn format(self, w: *std.Io.Writer) std.Io.Writer.Error!void` and
  need `{f}` to be called. Also new: `{t}` (tag or error name), `{b64}`.
- `std.ArrayList` became unmanaged: `.empty`, and the allocator is passed to every call.
- The `usingnamespace`, `async`, and `await` keywords were removed.
- The build system dropped `root_source_file`/`target`/`optimize` on `addExecutable` and
  friends. Use `.root_module = b.createModule(...)`.
- The http client and server were rewritten on top of Reader and Writer.

**0.16 (April 2026)**
- **I/O as an interface:** everything that blocks or is nondeterministic takes an
  `std.Io`: files (`std.Io.Dir`, `std.Io.File`), networking (`std.Io.net`), time
  (`io.sleep`, `Io.Timestamp`), randomness (`io.random`), child processes
  (`std.process.spawn`), and sync (`std.Io.Mutex`). `std.fs.cwd`, `std.net`, `std.time.sleep`,
  `std.Thread.Mutex`/`Pool`/`WaitGroup`, and `std.crypto.random` are gone. See
  `io-and-concurrency.md`.
- **"Juicy Main":** `pub fn main(init: std.process.Init)` gives `gpa`, `arena`, `io`,
  `environ_map`, `minimal.args`, and `preopens`. The environment and argv are no longer
  global (`std.os.getenv`, `std.process.argsAlloc`, `getEnvVarOwned` are gone).
- `@Type` was replaced by `@Int`, `@Struct`, `@Union`, `@Enum`, `@Pointer`, `@Fn`,
  `@Tuple`, and `@EnumLiteral`.
- `@cImport` is deprecated in favor of `b.addTranslateC` (translate-c is now Aro-based).
- Returning the address of a local is a compile error. Runtime vector indexing is forbidden.
- Managed `ArrayHashMap`/`AutoArrayHashMap`/`StringArrayHashMap` were removed. Use
  `std.array_hash_map.Auto/String/Custom` (unmanaged). The `Unmanaged` aliases are
  deprecated.
- `std.mem.indexOf*` renamed to `std.mem.find*` (old names deprecated). New `cut*` helpers.
- `std.heap.ArenaAllocator` is thread-safe and lock-free. `ThreadSafeAllocator` was removed.
- Packages are fetched into a project-local `zig-pkg/` (gitignore it). The fingerprint is
  mandatory. New `zig build --fork=<path>` overrides a dependency locally.
- The fuzzer takes `*std.testing.Smith` instead of `[]const u8`, with multi-core fuzzing
  and crash dumps.
- LLVM loop vectorization is **disabled** in 0.16 (miscompile workaround, expected until
  0.18). Hand-written `@Vector` SIMD still works. Some loops got slower.

## Everyday commands and flags

```bash
zig init                                   # build.zig, build.zig.zon, src/main.zig, src/root.zig
zig build                                  # Debug build into zig-out/
zig build test --summary all               # all test steps, with a tree of what ran
zig build test --test-timeout 5s           # kill any single test that runs longer (new in 0.16)
zig build -Doptimize=ReleaseSafe           # release build with safety checks
zig build -Dtarget=x86_64-linux-musl -Doptimize=ReleaseSafe   # static Linux binary
zig build --release=safe                   # same as -Doptimize=ReleaseSafe for standard options
zig build -fincremental --watch            # near-instant rebuilds (still opt-in in 0.16)
zig build --error-style minimal            # replaces removed --prominent-compile-errors
zig build --fetch                          # fetch the dependency tree, then work offline
zig build --fork=../my-dep-checkout        # temporarily use a local fork of a dependency
zig fetch --save https://…/v1.2.3.tar.gz   # add a pinned dependency to build.zig.zon
zig fmt --check .                          # CI format gate (zig fmt . to rewrite)
zig build test --fuzz=100K -Doptimize=ReleaseSafe   # bounded fuzzing (see testing.md)
zig cc -target x86_64-linux-musl a.c       # the bundled Clang as a cross C compiler
```

## Release modes

| Mode | Safety checks | Use it for |
|---|---|---|
| `Debug` (default) | All, plus slow codegen | Development and tests |
| **`ReleaseSafe`** | Bounds, overflow, `unreachable`, null, and union-tag checks stay on | **Default for services and CLIs you ship** |
| `ReleaseFast` | Off; illegal behavior is undefined | Measured hot paths and benchmarks, after tests pass in Debug and ReleaseSafe |
| `ReleaseSmall` | Off; optimizes for size | Wasm and embedded |

Why ReleaseSafe: a logic bug becomes a crash with a stack trace instead of silent memory
corruption, and the cost is usually a few percent. Leave `-Doptimize` open in `build.zig`
(`b.standardOptimizeOption(.{})`), and choose the mode in CI and the Dockerfile.

## Editor support (ZLS)

Use ZLS built for the same minor version (0.16.x with Zig 0.16.x). Turn on build-on-save
so ZLS reports real compile errors from `zig build`. There's no official Zig linter: the
compiler's errors (unused locals, never-mutated `var`, unused parameters) plus `zig fmt`
are the lint.

## Sources
- Release notes 0.16.0: https://ziglang.org/download/0.16.0/release-notes.html
- Release notes 0.15.1: https://ziglang.org/download/0.15.1/release-notes.html
- Language reference 0.16.0: https://ziglang.org/documentation/0.16.0/
- Standard library docs 0.16.0: https://ziglang.org/documentation/0.16.0/std/
- Download index (versions, tarballs, SHA-256): https://ziglang.org/download/index.json
- setup-zig action: https://github.com/mlugg/setup-zig
- ZLS: https://github.com/zigtools/zls
