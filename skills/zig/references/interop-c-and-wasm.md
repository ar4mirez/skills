# C interop, zig cc, and WebAssembly

Everything below was built with Zig 0.16.0: a C header imported through
`b.addTranslateC`, a C file compiled and called from Zig, a Zig static library called
from a C program (`assets/c_api.zig`, `assets/tally.h`, `assets/use_tally.c`), `zig cc`
cross-compiling C, and wasm32 modules run in Node.

## Contents
- Calling C from Zig: translate-c in the build (not @cImport)
- Compiling and linking C sources
- Exporting a C ABI from Zig
- zig cc as a cross compiler
- WebAssembly
- Pitfalls

## Calling C from Zig: translate-c in the build (not @cImport)

`@cImport` still works in 0.16 but is **deprecated**. The replacement translates a header
as a build step and exposes it as a module:

```zig
// build.zig
const c = b.addTranslateC(.{
    .root_source_file = b.path("csrc/adder.h"),   // or a src/c.h that #includes several headers
    .target = target,
    .optimize = optimize,
});
const mod = b.createModule(.{
    .root_source_file = b.path("src/main.zig"),
    .target = target, .optimize = optimize, .link_libc = true,
    .imports = &.{.{ .name = "c", .module = c.createModule() }},
});
mod.addCSourceFile(.{ .file = b.path("csrc/adder.c"), .flags = &.{ "-Wall", "-Wextra", "-Werror" } });
mod.addIncludePath(b.path("csrc"));
// system library: c.linkSystemLibrary("glfw", .{}); on the TranslateC step (per the release notes)
```
```zig
// src/main.zig
const c = @import("c");
const sum = c.adder_add(2, 3);     // C functions, types, and simple #define constants
```

- translate-c is now built on Aro instead of libclang. Translation is meant to be identical;
  treat differences as compiler bugs.
- Wrap each C API in a thin Zig file that converts `[*c]` pointers to slices, C return
  codes to Zig errors, and ownership to `deinit`. The rest of the code never sees `c.*`.
- The official `translate-c` package is an alternative when you need translation options
  (see the release notes).

## Compiling and linking C sources

- `mod.addCSourceFile(.{ .file = ..., .flags = ... })` / `addCSourceFiles`, plus
  `mod.addIncludePath`, `mod.linkSystemLibrary("z", .{})`, `mod.linkLibrary(artifact)`.
  Set `.link_libc = true` on the module whenever C code or `std.c` is used.
- C in Debug builds gets UBSan (`sanitize_c`), so treat "illegal instruction" crashes in C
  code as UB reports.
- To package a C library, write a `build.zig` for it (fetch the upstream tarball as a
  dependency, compile it with `addLibrary`, and `installHeader`), instead of requiring
  system packages. Cross-compiling then just works.

## Exporting a C ABI from Zig

```zig
// src/c_api.zig: built with b.addLibrary(.{ .linkage = .static, .name = "tally", ... })
pub const Status = enum(c_int) { ok = 0, out_of_memory = 1, word_too_long = 2 };

export fn tally_count(text: [*]const u8, len: usize, out_total: *u64, out_distinct: *usize) Status {
    const gpa = std.heap.c_allocator;
    var r: std.Io.Reader = .fixed(text[0..len]);
    var t = tally.countWords(gpa, &r, .{}) catch |err| return switch (err) { ... };
    defer t.deinit(gpa);
    ...
}
```

- Only extern-compatible types cross the boundary: fixed-width ints, `c_int`, pointers
  plus lengths, `extern struct`, and `enum(c_int)`. **Zig errors, slices, and optionals
  of non-pointers don't cross it.** Map errors to status codes.
- Prefix every symbol (`tally_`); C has one namespace.
- **Hand-write the header** (`assets/tally.h`) and keep it next to `c_api.zig`, with a
  test that calls each export. Zig's header emission (`-femit-h`) has historically been
  unreliable (verify for your version before depending on it).
- Allocation across the boundary: either the caller provides buffers, or you export a
  matching `tally_free`. Never let C `free()` Zig-allocated memory unless you allocated it
  with `std.heap.c_allocator`.
- `c_lib.installHeader(b.path("include/tally.h"), "tally.h")` + `b.installArtifact(c_lib)`
  → `zig-out/lib/libtally.a` and `zig-out/include/tally.h`.
- Shared library: `.linkage = .dynamic` (versioned with `.version`). The static library is
  the default because it's simpler to ship.
- Test it from C inside the build: compile `use_tally.c` as an executable linked against
  the library and `expectExitCode(0)` (`assets/build.zig`). Gate it with
  `target.query.isNative()`.

## zig cc as a cross compiler

`zig cc` / `zig c++` are Clang 21 with bundled libc headers and libraries for every
supported target, so there's no sysroot to install:

```bash
zig cc -target x86_64-linux-musl -O2 main.c -o app          # fully static
zig cc -target aarch64-linux-gnu.2.28 main.c -o app          # dynamic, glibc >= 2.28 floor
CC="zig cc -target x86_64-linux-musl" make                    # drop into existing builds
```

It's also a common way to cross-compile cgo (`CC="zig cc -target ..."`) or Rust C
dependencies. Prefer `build.zig` over Makefiles for new C code: it's one tool, and
caching and cross-compiling come built in.

## WebAssembly

```bash
# Freestanding module (browser / host embeds): exports only, no libc, no entry point
zig build-exe add.zig -target wasm32-freestanding -fno-entry -rdynamic -O ReleaseSmall
# WASI program: normal main, runs in wasmtime or Node's WASI
zig build-exe hello.zig -target wasm32-wasi -O ReleaseSmall
```

- In `build.zig`: `b.resolveTargetQuery(.{ .cpu_arch = .wasm32, .os_tag = .freestanding })`,
  then set `exe.entry = .disabled` and `exe.rdynamic = true` so `export fn` symbols are
  kept.
- Verified: the freestanding module's `add(2, 3)` returned 5 in Node, and the WASI binary
  printed through `std.Io.File.stdout()` under Node's WASI.
- Freestanding has no OS, so there's no `std.Io.Threaded` file or network. Pass data
  through exported functions and linear memory, and use `std.heap.wasm_allocator`.
- WASI gets `init.preopens` from Juicy Main for directory access.
- Use `ReleaseSmall` for size. Size matters more than speed on the web.

## Pitfalls
- `@cImport` in new code: move it to `b.addTranslateC`.
- Forgetting `.link_libc = true`: undefined `malloc`/`printf` at link time.
- Passing a Zig slice to C: pass `.ptr` and `.len` separately, and `[:0]` for C strings
  (`try gpa.dupeZ(u8, s)` when you need to add the terminator).
- `export fn` returning `!T`: it doesn't compile for C callers. Return a status code.
- Running cross-target tests: the host can't execute them without `-fqemu`, `-fwine`,
  `-frosetta`, or `-fwasmtime`. Only build them.
