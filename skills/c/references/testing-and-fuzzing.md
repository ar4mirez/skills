# Testing and fuzzing

## Contents
- The default: tiny assert macros plus CTest
- Test layout and what to test
- CLI and integration tests
- Sanitizers in every test run
- Fuzzing with libFuzzer
- Property tests
- Coverage
- Benchmarks

## The default: tiny assert macros plus CTest

Use `assets/test.h`: `CHECK`, `CHECK_EQ_INT`, `CHECK_EQ_STR`, `RUN`, and
`TEST_EXIT`. That's about 50 lines with no dependencies. Each test file is
one executable and one `add_test()`. Why this default:
- **Zero dependencies.** It builds anywhere the code builds (cross-compilers,
  WASI, embedded simulators), with the same warnings and sanitizers as
  production code.
- **CTest is already there.** It provides parallel runs (`ctest -j`),
  `--output-on-failure`, labels, timeouts, and `PASS_REGULAR_EXPRESSION` for
  CLI tests. Test presets make local and CI runs identical.
- **Sanitizers abort the process.** A test binary doesn't need fixture or
  crash isolation to report a memory error. ASan or UBSan kills it, and
  CTest reports the failure with the sanitizer trace.
- Failures print `file:line`, the expression, and both values, which is
  enough to debug without an assertion library.

Reach for a framework only when a real need appears. Unity (ThrowTheSwitch)
suits embedded targets with no `stdio`. `cmocka` is useful when you need
mocking of linked functions. Don't adopt a C++ framework (GoogleTest,
Catch2) for a C project: it drags in a second language and toolchain.

## Test layout and what to test

```
tests/test.h
tests/test_<module>.c     unit tests: one per public module
tests/test_http.c         the pure handler: request bytes → response bytes
```
- Test through the **public header**. Tests are the first consumer of the
  API: if a test needs internals, the API is missing something.
- For each function, cover: the happy path; every documented error status
  (NULL args, oversized input, not found); boundaries (empty, max length,
  max+1); growth past initial capacities (the 1000-key test crosses several
  rehashes); and the `destroy(NULL)` no-op.
- Test ownership contracts: a borrowed pointer stays valid across unrelated
  writes. ASan turns violations into failures.
- Name tests `test_<behavior>` and run each through `RUN(fn)`, so the log
  shows which one failed.
- Keep I/O out of the logic so it can be unit-tested: `http_handle()` takes
  bytes and returns bytes, while `server.c` only moves bytes between sockets
  and that function.

## CLI and integration tests

Test the real binary through CTest, with no shell scripts:
```cmake
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/sample.kv "greeting = hello\n")
add_test(NAME cli_found COMMAND kvstore-cli ${CMAKE_CURRENT_BINARY_DIR}/sample.kv greeting)
set_tests_properties(cli_found PROPERTIES PASS_REGULAR_EXPRESSION "^hello\n$")
add_test(NAME cli_missing COMMAND kvstore-cli ${CMAKE_CURRENT_BINARY_DIR}/sample.kv nope)
set_tests_properties(cli_missing PROPERTIES WILL_FAIL ON)   # exit 1 = not found
```

For a network service, unit-test the pure handler, then smoke-test the
binary in CI. Start it, `curl` `/up` and one real route, send `SIGTERM`, and
assert that exit code 0 arrives within the deploy's stop timeout.

## Sanitizers in every test run

- The `ci` preset runs everything under **ASan + UBSan** with
  `-fno-sanitize-recover=all`. Without that flag, UBSan prints and carries
  on, and the test passes.
- **Don't combine `-fno-strict-overflow` (or `-fwrapv`) with UBSan.** It
  makes signed overflow defined, so UBSan's signed-overflow check goes silent.
  That was verified: the same `INT_MAX + 1` is reported without the flag and
  silent with it. The template drops that hardening flag when
  `KVSTORE_SANITIZE` is on.
- `_FORTIFY_SOURCE` and ASan interfere, so the template applies FORTIFY only
  in optimized, non-sanitizer builds.
- The `tsan` preset runs the thread tests under TSan.
- Useful CI settings are `ASAN_OPTIONS=detect_leaks=1:strict_string_checks=1:detect_stack_use_after_return=1`
  and `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`.
- Reference: https://clang.llvm.org/docs/AddressSanitizer.html

## Fuzzing with libFuzzer

Every function that parses bytes from outside the process gets a fuzz target
(`assets/fuzz_parse.c`):
```c
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    kvstore *kv = nullptr;
    if (kvstore_create(&kv) != KVSTORE_OK) return 0;
    (void)kvstore_parse(kv, (const char *)data, size, &line);
    kvstore_destroy(kv);
    return 0;
}
```
- Build it with the `fuzz` preset (`-DKVSTORE_FUZZ=ON`, LLVM clang,
  `-fsanitize=fuzzer` plus ASan/UBSan). Run it with
  `./build/fuzz/fuzz_parse corpus/ -max_total_time=60 -max_len=4096`.
  Commit interesting inputs to `fuzz/corpus/`, and any crash reproducer as a
  regression test.
- **Apple clang has no libFuzzer runtime**: linking fails with
  `libclang_rt.fuzzer_osx.a not found`. Fuzz on Linux (the CI `fuzz` job) or
  with Homebrew LLVM. The template therefore also builds the same file with
  `-DKVSTORE_FUZZ_REPLAY`, a small `main()` that replays corpus files, and
  registers it as a CTest test. The harness keeps compiling and running on
  every platform.
- The target must be deterministic, must not leak (the fuzzer reports
  leaks), and must not `exit()`. Return 0 always; -1 means "don't add to
  corpus".
- For continuous fuzzing of an open-source library, apply to OSS-Fuzz.
- Reference: https://llvm.org/docs/LibFuzzer.html

## Property tests

C has no mainstream property-testing library, and a fuzz target *is* a
property test. Put invariants in the harness: parse → serialize → parse is
identical; `count()` equals the number of distinct keys set; `get` after
`set` returns the value. `__builtin_trap()` on violation, and libFuzzer
searches for counterexamples. For small exhaustive domains (all 256 bytes,
all short strings), write a plain loop in a unit test.

## Coverage

The `coverage` preset adds `--coverage` (gcov format, understood by GCC and
Clang):
```bash
cmake --preset coverage && cmake --build --preset coverage && ctest --preset coverage
gcovr -r . --filter src/ --filter app/ --txt-summary build/coverage          # GCC / Linux
gcovr --gcov-executable "xcrun llvm-cov gcov" -r . --filter src/ build/coverage   # Apple clang
```
The Apple clang line was verified. On the reference project it reports about
87% line coverage for `src/`. Aim for full coverage of error paths in the
library. Coverage of `server.c`'s socket code comes from the smoke test, not
unit tests. For clang-only projects, source-based coverage
(`-fprofile-instr-generate -fcoverage-mapping` + `llvm-cov report`) is more
precise. `gcovr` is a Python package, so install it in a virtualenv or with
`pipx`.

## Benchmarks

Keep benchmarks out of CTest. Build a separate `bench_<module>` executable in
`RelWithDebInfo`, time with `CLOCK_MONOTONIC`, repeat, and report the median.
Compare against the previous commit on the same machine. Numbers from a
laptop on battery, or from a sanitizer build, are meaningless.
