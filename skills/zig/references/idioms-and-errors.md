# Idioms, errors, memory, and the "don't" list

These rules are for Zig 0.16. Every API named here exists in the 0.16.0 std source, and
the patterns are exercised by `assets/root.zig`, `assets/main.zig`, and `assets/server.zig`.

## Contents
- Naming and style
- Errors
- Resource management: defer / errdefer
- Allocators and ownership
- Containers (unmanaged)
- Slices, pointers, and strings
- comptime and generics
- Formatting and logging
- Interfaces
- Don't

## Naming and style

`zig fmt` decides layout, so don't argue about it. Naming follows the std style guide:
- `camelCase` for functions;
- `TitleCase` for types, and for functions that return types;
- `snake_case` for variables, constants, fields, and files that are namespaces;
- `TitleCase.zig` for files that are a struct with fields.

Acronyms are words (`HttpServer`, `parseJson`). Prefer **decl literals**: `var list:
std.ArrayList(u8) = .empty;`, `var arena: std.heap.ArenaAllocator = .init(gpa);`,
`const addr: Io.net.IpAddress = try .parse("0.0.0.0", port);`. The type is written once,
and the call site stays short.

The compiler errors on unused locals and parameters, on a `var` that's never mutated, and
on discarded non-void results. Fix the code; don't sprinkle `_ = x;` to silence it.

## Errors

- Errors are values in a closed set, returned as `E!T`. Propagate with `try`, and handle
  with `catch |err| switch (err) { ... }`. Switch exhaustively on the set so a new error
  becomes a compile error at every handler.
- **Declare error sets on public APIs** (`pub const ParseError = error{ Empty, TooLong } ||
  Allocator.Error;`). Inferred sets (`!T`) are fine for private functions. Avoid
  `anyerror`: callers can't handle it exhaustively.
- Errors carry no payload. When the caller needs details (a line number, the bad field),
  add an optional `diag: ?*Diagnostics` out-parameter, the way `std.json` does. Don't
  encode data in error names.
- **No hidden control flow:** every early return is a visible `try`, `return`, or `catch`.
  Don't use `catch unreachable` to "make it compile". Use `unreachable` only for states the
  code has proven impossible, with a comment saying why (as in `c_api.zig`: a fixed reader
  can't fail). In ReleaseFast, reaching `unreachable` is undefined behavior.
- `std.debug.assert(cond)` documents and checks invariants in Debug and ReleaseSafe. In
  ReleaseFast it becomes an optimizer assumption, so never assert on untrusted input;
  validate input and return an error.
- `main` may return `!void` or `!u8`. A returned error prints `error: Name` plus a trace and
  exits 1. For expected user errors (bad flags, missing file), print a clear message and
  return a code instead of dumping a trace.

## Resource management: defer / errdefer

```zig
var t: Tally = .empty;
errdefer t.deinit(gpa);          // runs only if this function returns an error after this line
const file = try Io.Dir.cwd().openFile(io, path, .{});
defer file.close(io);            // runs on every exit path, in reverse order
```

- Put the `defer` or `errdefer` on **the line right after** acquiring. Reviewers look for
  it there.
- When ownership moves out on success (you return the object), use `errdefer`, not `defer`.
- `deinit` takes `*T`, frees, then sets `self.* = undefined`, so use-after-deinit trips
  Debug checks.
- When an insert half-completes (`getOrPut`, then a failed `dupe`), roll it back before
  returning the error (`assets/root.zig: Tally.add`). `checkAllAllocationFailures` finds
  these leaks (see `testing.md`).

## Allocators and ownership

- **Libraries take an `std.mem.Allocator` parameter** (conventionally `gpa` for a general
  allocator, `arena` when the caller promises bulk free). No globals, no hidden
  `page_allocator`.
- The application picks allocators once, in `main`:
  - `init.gpa` for long-lived data. Juicy Main sets it to `DebugAllocator` (leak checking)
    in Debug, and in ReleaseSafe when libc isn't linked. It's `c_allocator` when libc is
    linked, and `smp_allocator` in ReleaseFast/Small.
  - `init.arena` for data that lives as long as the process (parsed args, config).
  - **An `ArenaAllocator` per request, job, or frame**: allocate freely, and free
    everything once with `arena.deinit()` or `_ = arena.reset(.retain_capacity)`.
  - `std.heap.FixedBufferAllocator` when there's a hard upper bound known ahead of time.
  - `std.heap.DebugAllocator(.{})` (the name for what used to be
    `GeneralPurposeAllocator`) when you build your own leak-checked instance, for
    example with `main(init: std.process.Init.Minimal)`.
- **Write ownership in doc comments.** "Caller owns the returned slice; free with
  `gpa.free`." "The `word` fields borrow from `t` and are valid until `t.deinit`." A pointer
  into a container is invalidated by any call that can grow it.
- Memory freed or reset through an arena doesn't need individual `free` calls. Say so in a
  comment where you skip `deinit` (`assets/server.zig`).

## Containers (unmanaged)

`std.ArrayList(T)`, `std.StringHashMapUnmanaged(V)`, `std.AutoHashMapUnmanaged(K, V)`,
`std.array_hash_map.Auto(K, V)`/`.String(V)`, `std.MultiArrayList`, `std.Deque`,
`std.PriorityQueue`. Initialize with `.empty` and pass the allocator to every mutating
call (`list.append(gpa, x)`, `map.put(gpa, k, v)`, `list.deinit(gpa)`). Managed variants
(`std.array_list.Managed`, `std.AutoHashMap` with a stored allocator) are legacy or
removed. For a bounded stack buffer, use `std.ArrayList(T).initBuffer(&buf)` with the
`*Bounded` methods, not the removed `BoundedArray`.

Hash maps with string keys don't copy keys. `dupe` them on insert and free them in
`deinit` (`Tally`), or keep them in an arena.

## Slices, pointers, and strings

- Pass `[]const T` / `[]T`, never pointer plus length. Use `[*]T` only at a C boundary
  (`c_api.zig`: `text: [*]const u8, len: usize` becomes `text[0..len]` immediately).
- Strings are `[]const u8` (bytes, usually UTF-8). Use `std.unicode` when you need code
  points. Sentinel-terminated `[:0]const u8` is for C and argv.
- Returning `&local` is a compile error in 0.16 (it was UB before). Return by value, or
  allocate.
- Use `std.mem.eql`, `std.mem.find*` (`indexOf*` is deprecated), `std.mem.splitScalar`,
  `tokenizeAny`, and the new `cut`/`cutPrefix`/`cutScalar` helpers.

## comptime and generics

- Generics are functions that take `comptime T: type` and return a value or a type:
  `fn Stack(comptime T: type) type { return struct { items: std.ArrayList(T) = .empty, ... }; }`.
  That's the whole generics system. Use it plainly.
- Prefer a concrete type or an explicit `comptime T: type` over `anytype`. Use `anytype`
  only for duck-typed helpers such as `std.json.Stringify.value`, and document the
  interface it expects.
- Keep reflection (`@typeInfo`, `inline for` over fields, the new `@Struct`/`@Int`
  builtins that replaced `@Type` in 0.16) for serializers and similar code where it
  removes real duplication. If a reviewer can't predict the generated code, write it out.
- Size buffers and tables with comptime constants (`pub const max_word_cap = 256;`), and
  enforce the limit with an assert or error at runtime.

## Formatting and logging

- `writer.print("{d} {s} {t} {f} {any}", .{ n, str, enum_or_error, value_with_format, x })`.
  `{t}` prints a tag or error name. `{f}` calls a `format` method. **In 0.16, `{}` on a type
  with a `format` method doesn't call it** (verified: it prints the fields). Always write
  `{f}`.
- A format method is `pub fn format(self: T, w: *std.Io.Writer) std.Io.Writer.Error!void`,
  with no format string or options.
- `std.log.scoped(.name)` for diagnostics (stderr). Its default level is `.debug` in
  Debug and `.info` in release builds; set `pub const std_options: std.Options =
  .{ .log_level = .info };` in the root file. Use `std.debug.print` only in tests and
  throwaway code.

## Interfaces

For runtime polymorphism, use the std pattern: a struct holding `ptr: *anyopaque` plus
`vtable: *const VTable` (like `std.mem.Allocator` and `std.Io`), or a tagged
`union(enum)` when the set of variants is closed. **A tagged union is the default:** it's
exhaustively switchable and needs no pointers. Reach for a vtable only when outside code
must add implementations.

## Don't
- Don't use `catch unreachable`, `catch {}`, or `anyerror` on public APIs.
- Don't use global allocators, `std.heap.page_allocator` as a general allocator, or
  allocate in a library without taking an `Allocator`.
- Don't store an allocator inside every container (`Managed`); pass it per call.
- Don't write `ptr: [*]T, len: usize` in Zig-to-Zig APIs.
- Don't use `usingnamespace` (removed); re-export explicitly.
- Don't use `@setRuntimeSafety(false)` without a benchmark, a comment, and a test.
- Don't reach for comptime metaprogramming where a plain function or a small `switch`
  does the job.
- Don't use `std.debug.print` in library code. Take a `*std.Io.Writer` or use `std.log`.
