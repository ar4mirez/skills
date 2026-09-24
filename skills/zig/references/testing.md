# Testing

Zig's test runner is built into the compiler and the build system. There's nothing to
install. Everything below runs in the reference project (`zig build test`: 11 tests across
four modules plus a C program, in Debug, ReleaseSafe, and ReleaseFast).

## Contents
- Layout: tests live next to the code
- The test step
- Leak checks and allocation-failure tests
- Tests that need I/O: std.testing.io, tmpDir, sockets
- Integration tests
- Fuzzing (0.16 Smith API)
- Benchmarks and coverage
- CI matrix

## Layout: tests live next to the code

```zig
test "top orders by count then word" {        // described test
    const gpa = std.testing.allocator;
    ...
    try std.testing.expectEqualStrings("b", best[0].word);
}
test Tally { ... }                             // doctest: attached to the decl in generated docs
```

- Put unit tests in the same file as the code under test. They can reach private
  functions, and they compile away from non-test builds.
- Useful assertions: `expect`, `expectEqual(expected, actual)` (expected first; cast
  literals, e.g. `@as(u32, 3)`), `expectEqualStrings`, `expectEqualSlices`,
  `expectError(error.X, expr)`, `expectFmt`, `expectEqualDeep`, and
  `expectApproxEqAbs`.
- `return error.SkipZigTest;` skips a test (for example, when a platform feature is missing).
- Tests in another file run only if that file is actually used from the root. Add
  `test { _ = @import("parser.zig"); }` for files that would otherwise be skipped silently.

## The test step

In `build.zig`, add one `b.addTest(.{ .root_module = m })` per module, `addRunArtifact`,
and hang them all on `b.step("test", ...)` (`assets/build.zig`). Then:

```bash
zig build test --summary all            # prints each run step with pass/fail counts
zig build test -Doptimize=ReleaseSafe   # same tests, release codegen, checks on
zig build test --test-timeout 10s       # new in 0.16: kill hung or slow tests
zig build test -Dtest-filter=parser     # needs the option below
```

Filter option (verified):
```zig
const filters = b.option([]const []const u8, "test-filter", "Run only matching tests") orelse &.{};
const t = b.addTest(.{ .root_module = m, .filters = filters });
```

For one file without a build graph: `zig test src/root.zig --test-filter "top"`.

## Leak checks and allocation-failure tests

- **`std.testing.allocator`** is a `DebugAllocator` that fails the test when memory
  leaks, and prints the allocation's stack trace. Use it in every test that allocates.
  `page_allocator` or `c_allocator` in tests hides leaks.
- **`std.testing.checkAllAllocationFailures(std.testing.allocator, testFn, .{args})`**
  reruns `testFn` once per allocation, failing the Nth one each time. It proves every
  `errdefer` path frees what it allocated. `assets/root.zig` has an example that caught a
  real leak class (a half-inserted map entry).
- `std.testing.failing_allocator` always fails, for asserting `error.OutOfMemory`
  handling directly.
- Juicy Main's `init.gpa` leak report at exit **doesn't change the exit code**. Leaks are
  enforced by tests, not by running the binary.

## Tests that need I/O: std.testing.io, tmpDir, sockets

- `std.testing.io` is an `Io.Threaded` instance set up by the test runner. Pass it where
  production code takes `io`.
- Prefer pure I/O: construct `std.Io.Reader.fixed("input")` and
  `std.Io.Writer.Allocating.init(gpa)` (then `.written()`) instead of touching files.
- For real files: `var tmp = std.testing.tmpDir(.{}); defer tmp.cleanup();` and then
  `tmp.dir.createFile(io, "x", .{})`.
- For network code, listen on `127.0.0.1` port **0**, read the port back from
  `listener.socket.address.getPort()`, run the server loop with
  `io.concurrent(serve, .{...})` plus `defer task.cancel(io) catch {};`, and drive it
  with `std.http.Client.fetch` (the last test in `assets/server.zig`).
- Keep config parsing pure (`Config.fromEnv(*const std.process.Environ.Map)`), so tests
  build a map instead of mutating the process environment.

## Integration tests

Put black-box tests in `tests/*.zig`, as modules that import the library module, with
their own `addTest` on the same `test` step. For CLI behavior, `b.addRunArtifact(exe)`
plus `run.addArgs(...)`, `run.expectExitCode(0)`, and `run.expectStdOutEqual("...")`
turns a CLI invocation into a build-time test. The C example in `assets/build.zig` uses
`expectExitCode`. Gate foreign-target runs with `target.query.isNative()`, since the host
can't execute cross-compiled binaries without `-fqemu`, `-fwine`, or `-frosetta`.

## Fuzzing (0.16 Smith API)

```zig
test "fuzz: counts always sum to total" {
    try std.testing.fuzz({}, fuzzCount, .{ .corpus = &.{ "hello world", "a\nb" } });
}
fn fuzzCount(_: void, smith: *std.testing.Smith) !void {
    var buf: [512]u8 = undefined;
    const len = smith.slice(&buf);           // also: smith.value(T), .bytes, .eos(), .valueRangeAtMost
    ... // assert an invariant; return error.SkipZigTest for inputs you intentionally skip
}
```

- In 0.16, fuzz tests receive `*std.testing.Smith` (a value generator with weights), not
  `[]const u8`. Old examples with `input: []const u8` don't compile.
- Under plain `zig build test`, a fuzz test runs once per corpus entry, like a unit test.
- `zig build test --fuzz=100K` runs a bounded campaign (multi-core with `-j`, with crash
  inputs saved to a file). Plain `--fuzz` runs forever and starts the web UI.
- **Gotcha (verified in 0.16.0):** `--fuzz` fails to compile in Debug mode with a test
  runner type error (`*builtin.StackTrace` vs `*debug.StackTrace`), even for the
  `zig init` template. Run fuzzing with `-Doptimize=ReleaseSafe`, which works.
- Fuzz pure functions: parsers, decoders, and state machines. Assert invariants
  (round-trips, sums, no panics) rather than exact outputs.

## Benchmarks and coverage

- There's no benchmark framework in std. Write a small `bench` executable built with
  `-Doptimize=ReleaseFast`: time with `std.Io.Timestamp.now(io, .awake)` and
  `untilNow`, run enough iterations, and use `std.mem.doNotOptimizeAway(result)`. Compare
  runs, not absolute numbers. Use `hyperfine` for whole-binary runs.
- There's no built-in coverage. On Linux, `kcov` works on Zig test binaries in Debug
  (verify for your version). Treat coverage as a hint, and prefer
  `checkAllAllocationFailures` and fuzzing, which find more real bugs in Zig code.

## CI matrix

Run `zig build test` in **Debug and ReleaseSafe** at minimum. ReleaseFast is worth a job
because it exposes code that silently relied on safety-check behavior. Add native macOS
and Linux, plus cross builds for each release target. The template is
`assets/github-ci.yml` (see `quality-and-security.md`).
