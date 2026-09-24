# Project layout, build.zig, and packages

Everything here was built with Zig 0.16.0 in a scratch reference project (the tree
`scripts/new_project.py` produces), in a two-package workspace, and with a `zig fetch --save`
round-trip.

## Contents
- One layout for every project
- build.zig anatomy (0.16)
- build.zig.zon: fingerprint, paths, dependencies
- (a) Library
- (b) CLI
- (c) Network service
- (d) Workspace / monorepo
- Build options and generated config
- Don't

## One layout for every project

```
build.zig            build graph (modules, artifacts, steps)
build.zig.zon        package manifest (name, fingerprint, deps, paths)
src/root.zig         the library module: all reusable logic, no process I/O
src/main.zig         thin CLI entrypoint: parse args, wire Io + allocators, call root
src/server.zig       thin service entrypoint (when there is one)
src/c_api.zig        C ABI exports (only if C callers exist)
include/<name>.h     hand-written C header for c_api.zig
.gitignore           .zig-cache/  zig-out/  zig-pkg/
```

**Why:** `root.zig` holds the logic and takes `Allocator`, `Io`, `*Io.Reader`, and
`*Io.Writer` as parameters, so every entrypoint (CLI, service, C ABI, tests) reuses it and
tests need no process. Files that are both a module and a type use `TitleCase.zig` with
top-level fields (`Tally.zig`); namespaces use `snake_case.zig`.

## build.zig anatomy (0.16)

The 0.15+ build API centers on **modules**:
- `b.addModule(name, opts)` creates a module and **exports** it to packages that depend on
  yours (`dep.module(name)`).
- `b.createModule(opts)` creates a private one.
- Artifacts (`addExecutable`, `addLibrary`, `addTest`) take `.root_module`. The old
  `.root_source_file`/`.target`/`.optimize` fields on them were removed, and so were
  `addStaticLibrary`/`addSharedLibrary`: use `addLibrary(.{ .linkage = .static | .dynamic })`.

```zig
const target = b.standardTargetOptions(.{});      // -Dtarget=...
const optimize = b.standardOptimizeOption(.{});   // -Doptimize=... (Debug by default)

const lib = b.addModule("tally", .{ .root_source_file = b.path("src/root.zig"),
    .target = target, .optimize = optimize });

const exe = b.addExecutable(.{ .name = "tally", .root_module = b.createModule(.{
    .root_source_file = b.path("src/main.zig"), .target = target, .optimize = optimize,
    .imports = &.{.{ .name = "tally", .module = lib }},
}) });
b.installArtifact(exe);

const test_step = b.step("test", "Run all tests");
for ([_]*std.Build.Module{ lib, exe.root_module }) |m|
    test_step.dependOn(&b.addRunArtifact(b.addTest(.{ .root_module = m })).step);
```

- `addTest` only **compiles**. Tests run when you `addRunArtifact` and hang it on a step.
  Every module with `test` blocks needs its own test artifact. Tests in an imported file run
  only if something in that file is actually used. A file that's imported but unused, or
  holds only tests, is silently skipped (verified). Add `test { _ = @import("x.zig"); }` in
  the root file for each such file.
- Module options also carry `link_libc`, `strip`, `single_threaded`, `sanitize_c`
  (`.off/.trap/.full`), `sanitize_thread`, `pic`, `omit_frame_pointer`, `error_tracing`,
  and `fuzz`.
- **Keep `b.standardOptimizeOption(.{})` plain.** Passing
  `.preferred_optimize_mode` removes `-Doptimize` entirely (only `--release` remains), and
  plain `--release` without `=safe|fast|small` errors when no preferred mode is set.
- The complete, tested file is `assets/build.zig`: library, CLI, service, C static library
  plus header, a C example run as a test, and a `fmt` step.

## build.zig.zon: fingerprint, paths, dependencies

```zig
.{
    .name = .tally,                        // enum literal, not a string
    .version = "0.1.0",
    .fingerprint = 0xe8b6fe03ae5584f4,     // package identity; never change it
    .minimum_zig_version = "0.16.0",
    .dependencies = .{},
    .paths = .{ "build.zig", "build.zig.zon", "src", "include", "examples" },
}
```

- **The fingerprint is mandatory.** Its high 32 bits are the CRC-32 of `.name` and its low
  32 bits are a random id. Renaming the package makes the old value "invalid", and
  `zig build` prints a fresh suggestion. `scripts/new_project.py` computes a valid one.
  Keep it stable after publishing: it's how the package manager tells "new version of
  X" from "hostile fork of X".
- `.paths` limits what is hashed and shipped. List sources, the license, and the manifest
  files.
- **Add dependencies with `zig fetch --save <url>`**, which writes `.url` plus the content
  `.hash`. Point the url at a tag or commit tarball, or at `git+https://…#<commit>`. A
  branch-head URL breaks the hash when the branch moves. Mark optional heavy deps
  `.lazy = true` and load them with `b.lazyDependency`.
- In 0.16, `zig build` fetches into `./zig-pkg/` (editable and greppable). Don't commit
  it. `zig build --fetch` pre-fetches for offline or Docker layer caching.
- Use a dependency: `const dep = b.dependency("httpz", .{ .target = target, .optimize =
  optimize }); mod.addImport("httpz", dep.module("httpz"));`

## (a) Library

`src/root.zig` + `b.addModule` + tests, with no executable. Don't put `pub fn main` in
it, and don't read the environment, stdout, or globals. Ownership is in doc comments
("Caller owns the returned slice; free with `gpa.free`"). Export a C ABI only on request
(`interop-c-and-wasm.md`).

## (b) CLI

`src/main.zig` with `pub fn main(init: std.process.Init) !u8`:
- parse `init.minimal.args.toSlice(init.arena.allocator())` in a pure `parseArgs` function
  that returns an error on bad input (unit-testable);
- create one buffered stdout writer and `flush()` before returning;
- return `2` for usage errors and `1` for runtime failures.

There's no std argument-parsing library. Hand-roll small CLIs; for large ones, evaluate a
maintained package and pin it. See `assets/main.zig`.

## (c) Network service

`src/server.zig`: read config once from `init.environ_map`, `Io.net.IpAddress.listen`,
and handle each connection in an `Io.Group`, with one arena per request, a `/up` route,
and body limits. See `io-and-concurrency.md` and `assets/server.zig`. It stays a thin
adapter: routing and handlers call `root.zig`.

## (d) Workspace / monorepo

Zig has no workspace file. Each package has its own `build.zig` and `build.zig.zon`, and
siblings depend on each other by **path**:

```
libs/mathx/{build.zig, build.zig.zon, src/root.zig}      # b.addModule("mathx", ...)
apps/calc/{build.zig, build.zig.zon, src/main.zig}
# apps/calc/build.zig.zon
.dependencies = .{ .mathx = .{ .path = "../../libs/mathx" } },
# apps/calc/build.zig
const mathx = b.dependency("mathx", .{ .target = target, .optimize = optimize });
... .imports = &.{.{ .name = "mathx", .module = mathx.module("mathx") }},
```

Path deps have no hash and always track the working tree. Every package still needs its
own fingerprint. Run `zig build test` in each package, or add a root `build.zig` whose
`test` step depends on each package's test step. Split into packages only when a part is
published or versioned on its own. Otherwise, several modules in one `build.zig` is simpler.

## Build options and generated config

```zig
const enable_metrics = b.option(bool, "metrics", "Enable metrics") orelse false;
const opts = b.addOptions();
opts.addOption(bool, "metrics", enable_metrics);
exe.root_module.addOptions("build_options", opts);   // @import("build_options").metrics
```

Use build options for compile-time switches, and environment variables (read in `main`)
for runtime config and secrets. Never bake a secret into a build option.

## Don't
- Don't copy a 0.11–0.14 `build.zig`; the field names changed.
- Don't use `b.addStaticLibrary`, `exe.addModule`, `std.build.Builder`, or
  `root_source_file` on artifacts.
- Don't commit `zig-out/`, `.zig-cache/`, or `zig-pkg/`.
- Don't use a `.url` without a `.hash`, or a branch-head URL.
- Don't put logic in `main.zig` that tests can't reach.
