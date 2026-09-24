# Testing: unit, integration, fuzz, benchmarks, coverage

## Contents
- Framework choice: GoogleTest
- Layout and CTest wiring
- Writing tests
- Integration tests for CLIs and services
- Property-style tests
- Fuzzing with libFuzzer
- Benchmarks with google/benchmark
- Coverage
- Running under sanitizers

## Framework choice: GoogleTest

**Default: GoogleTest (1.17 from the vcpkg baseline, 1.18 upstream) through CTest.** Why:
- CMake ships the `GoogleTest` module: `gtest_discover_tests()` registers **one CTest test
  per `TEST()`**. `ctest -j` runs them in parallel with per-test timeouts, and a failure
  names the exact case.
- gMock is included for the rare seam that needs a mock.
- It's the most widely packaged C++ test framework (vcpkg `gtest`, Conan, every distro), and
  most C++ engineers already read it.

Catch2 v3 (3.16) is equally good; keep it if a project already uses it. Never mix the two in
one repo. doctest is for header-only libraries that must compile tests into the library
itself.

## Layout and CTest wiring

```
tests/
  CMakeLists.txt            # assets/tests-CMakeLists.txt
  wordcount_test.cpp        # one file per library unit: <unit>_test.cpp
  thread_pool_test.cpp
```

```cmake
find_package(GTest CONFIG REQUIRED)
include(GoogleTest)
add_executable(acme_tests wordcount_test.cpp thread_pool_test.cpp)
target_link_libraries(acme_tests PRIVATE acme::wordcount acme::options GTest::gtest_main)
gtest_discover_tests(acme_tests DISCOVERY_MODE PRE_TEST)
```

- **`DISCOVERY_MODE PRE_TEST`** lists tests when `ctest` runs, not as a post-build step. That
  keeps cross-compiled and sanitizer builds from executing test binaries during the build,
  and the environment from the test preset (for example `ASAN_OPTIONS`) applies to
  discovery too.
- One test executable per library is plenty until link times hurt.
- The test preset sets `outputOnFailure`, a 60-second timeout, and `noTestsAction: error`, so
  a broken discovery can't pass as "0 tests".

## Writing tests

- Name tests `TEST(Unit, BehaviorInPlainWords)`: `Counter.RejectsOversizedWordWithoutPartialUpdate`.
- Test behavior through the public API, not private members. If you need to reach inside,
  the unit is too big.
- `ASSERT_*` when continuing makes no sense (a missing value), `EXPECT_*` otherwise.
- Test the error paths of `std::expected` explicitly: the error code, the context (offset),
  and that no partial mutation happened.
- Table-driven cases with a loop and `<< input` in the message (see `ParseCount.RejectsGarbage`),
  or `TEST_P` when each case needs its own name in reports.
- **`[[nodiscard]]` meets `EXPECT_THROW`:** libc++ marks `std::future::get()` as
  `[[nodiscard]]`, so `EXPECT_THROW(f.get(), E)` warns (an error under `-Werror`). Write
  `EXPECT_THROW((void)f.get(), E)`.
- No sleeps to "wait for threads": use futures, latches, or joins. Sleep-based tests are flaky
  under sanitizers, which run 2 to 15 times slower.

## Integration tests for CLIs and services

- CLIs: `add_test(NAME cli.<case> COMMAND <target> args…)` with `WILL_FAIL` for non-zero exits
  and `PASS_REGULAR_EXPRESSION` for output. Generate input files with `file(WRITE …)` in the
  binary dir rather than committing fixtures you then have to locate.
- Services: keep handlers thin and test the library functions they call. For an end-to-end
  check, start the server binary on a free port in a CTest fixture (`FIXTURES_SETUP`) and hit
  it with `curl`, or with `httplib::Client` from a GoogleTest test.

## Property-style tests

There's no standard property-testing library worth the dependency. Get the same value from:
- invariants checked in the fuzz target (for example "`total()` equals the sum of the counts",
  or "`render()` of `top(n)` has at most n lines"), and
- small generated loops in unit tests (all short strings over a tiny alphabet).
RapidCheck exists (vcpkg `rapidcheck`) if a team wants shrinking; justify it first.

## Fuzzing with libFuzzer

```cpp
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size);
```
- Every function that parses untrusted bytes gets a fuzz target in `fuzz/`, built with
  `-fsanitize=fuzzer,address,undefined`.
- **Apple clang ships no libFuzzer runtime** (verified: `-fsanitize=fuzzer` fails to link).
  `ProjectOptions.cmake` probes with `check_cxx_source_compiles` and skips fuzz targets with
  a warning; fuzz on Linux with upstream Clang (the CI `fuzz` job) or Homebrew LLVM.
- CI runs `-max_total_time=60` on every PR. Keep a corpus directory and commit crashing inputs
  as regression tests.
- GCC has no libFuzzer; for GCC-only projects use AFL++ (`afl-clang-fast` or
  `afl-g++-fast`) with the same entry point.

## Benchmarks with google/benchmark

Optional, behind `-DACME_BUILD_BENCHMARKS=ON -DVCPKG_MANIFEST_FEATURES=bench`. Verified on
Apple clang (`BM_CounterAdd` ran at about 136 MiB/s).
- Always benchmark Release builds; Debug numbers are meaningless.
- `benchmark::DoNotOptimize(result)` so the optimizer can't delete the work;
  `state.SetBytesProcessed(...)` for throughput.
- Compare runs with `tools/compare.py` from the benchmark repo; one run is noise.
- Benchmarks aren't tests: don't run them in CTest.

## Coverage

Clang (source-based, the most accurate), verified with Apple clang:
```bash
cmake --preset dev -B build/cov -DCMAKE_CXX_FLAGS="-fprofile-instr-generate -fcoverage-mapping" \
  -DCMAKE_EXE_LINKER_FLAGS=-fprofile-instr-generate
cmake --build build/cov
cd build/cov && LLVM_PROFILE_FILE="$PWD/prof/%p.profraw" ctest -j4
llvm-profdata merge -sparse prof/*.profraw -o cov.profdata      # macOS: xcrun llvm-profdata
llvm-cov report ./tests/acme_tests -object ./apps/wc/wc -instr-profile=cov.profdata \
  -ignore-filename-regex='(vcpkg_installed|tests)/'
```
GCC: `--coverage` on compile and link, then `gcovr --root . --exclude tests`.
Coverage is a flashlight, not a target: chase untested error paths, not a percentage.

## Running under sanitizers

- `cmake --workflow --preset asan` and `cmake --workflow --preset tsan` before every PR; CI
  runs both.
- `-fno-sanitize-recover=all` makes UBSan findings fail the test instead of printing and
  continuing.
- **Don't set `detect_leaks=1` on macOS:** Apple's ASan doesn't support LeakSanitizer, and the
  option aborts every process ("detect_leaks is not supported on this platform"), including
  GoogleTest discovery. On Linux, LeakSanitizer is on by default with ASan.
- MemorySanitizer needs every dependency (including the standard library) instrumented;
  skip it unless you build the world from source.
