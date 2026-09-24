# Quality gate: formatter, warnings, static analysis, CI

## Contents
- The gate, in order
- Warnings (GCC vs Clang)
- clang-format
- clang-tidy (curated)
- GCC -fanalyzer and cppcheck
- Vulnerability and dependency scanning
- The GitHub Actions workflow
- What was and wasn't verified locally

## The gate, in order

Every PR must pass all of these with **zero warnings**:
1. `clang-format --dry-run --Werror` on every `.c` and `.h` file.
2. Build and test under **ASan + UBSan** with warnings as errors, on GCC and
   Clang (`cmake --workflow --preset ci`).
3. Build and test the **hardened release** (`--preset ci-release`). This
   catches `-O2`-only warnings and FORTIFY failures.
4. The **TSan** test run (Clang).
5. **clang-tidy** with `.clang-tidy`, via the exported
   `compile_commands.json`.
6. **GCC `-fanalyzer`** and **cppcheck**.
7. A **60-second libFuzzer run** per fuzz target.
8. Optionally, this skill's `scripts/audit.py --fail-on medium`, for the
   API-misuse patterns that compilers don't flag.

## Warnings (GCC vs Clang)

The policy target in `assets/CMakeLists.txt` uses these warnings:

| Flag | GCC | Clang | Catches |
|---|---|---|---|
| `-Wall -Wextra -Wpedantic` | ✓ | ✓ | The baseline. `-Wpedantic` rejects extensions under `C_EXTENSIONS OFF` |
| `-Wconversion -Wsign-conversion` | ✓ | ✓ | Silent truncation and sign changes. Noisy at first; fix each with a range check |
| `-Wshadow` | ✓ | ✓ | Shadowed locals |
| `-Wformat=2`, `-Werror=format-security` | ✓ | ✓ | Non-literal format strings, and format/argument mismatches |
| `-Wimplicit-fallthrough` | ✓ | ✓ | Missing `break` (mark intent with `[[fallthrough]];`) |
| `-Wstrict-prototypes -Wmissing-prototypes` | ✓ | ✓ | Unprototyped functions, and non-`static` functions missing from headers |
| `-Wvla`, `-Wcast-qual`, `-Wundef`, `-Wnull-dereference` | ✓ | ✓ | VLAs, casting away `const`, undefined macros in `#if`, provable NULL derefs |
| `-Werror=implicit -Werror=incompatible-pointer-types -Werror=int-conversion` | ✓ | ✓ | Obsolete C that newer compilers already reject (OpenSSF) |
| `-Wtrampolines -Wlogical-op -Wduplicated-cond -Wduplicated-branches` | ✓ | ✗ | GCC-only, so they're behind `$<C_COMPILER_ID:GNU>`. Clang warns "unknown warning option" |

`-Wtrampolines` and `-Wbidi-chars=any` are unknown to Apple clang 21: it
warns and continues. That's why GCC-only flags go behind a generator
expression rather than being passed to every compiler. Don't use
`-Weverything` (Clang) in the gate. It includes contradictory and
experimental warnings, and it changes meaning with every release.

## clang-format

`assets/.clang-format` is LLVM style with 4-space indent, a 100-column limit,
and `InsertBraces: true` (braces on every `if`/`for`, the goto-fail lesson).
Run it with `clang-format -i $(git ls-files '*.c' '*.h')`. Verified with
clang-format 23.1.1. The scaffolder renames identifiers, which shifts line
lengths, so run clang-format once after scaffolding. The macOS Command Line
Tools include `clang-format`; `clang-tidy` isn't included (it's on PyPI as
`clang-tidy` if you need it in a virtualenv).

## clang-tidy (curated)

`assets/.clang-tidy` enables:
- `bugprone-*` (minus easily-swappable-parameters and
  assignment-in-if-condition);
- `clang-analyzer-*`: path-sensitive checks for leaks, NULL derefs, and
  stream misuse (it caught a real `fread`-after-EOF pattern in the first
  draft of `cli.c`);
- selected `cert-*` checks;
- `performance-*` and `portability-*`;
- a few `readability-*` checks.

`WarningsAsErrors: '*'` applies. These were left out on purpose, after
running them against the reference project:
- `cert-err33-c` flags every unchecked `fprintf`. Our API uses
  `[[nodiscard]]` instead.
- `misc-include-cleaner` gives false positives on the macOS SDK's split
  headers (for example, it wants `pthread_t` from an internal header).
  Consider enabling it in a Linux-only CI job.
- `readability-implicit-bool-conversion` flags idiomatic `if (!p)`.

Run it with `clang-tidy -p build/dev --quiet src/*.c app/*.c tests/*.c`. With
a non-Apple clang-tidy on macOS, add
`--extra-arg=-isysroot$(xcrun --show-sdk-path)`. Suppress a single line with
`/* NOLINTNEXTLINE(check-name): reason */`, and always give the reason.
Verified: clang-tidy 22.1.8 reports zero findings on the reference project.

## GCC -fanalyzer and cppcheck

- **`-fanalyzer`** (GCC ≥ 10, much faster in GCC 16) finds double frees,
  leaks on error paths, use-after-free, and file-descriptor leaks. It's slow
  and GCC-only, so run it as a separate CI job with
  `-DCMAKE_C_FLAGS=-fanalyzer -DCMAKE_COMPILE_WARNING_AS_ERROR=ON` on the
  command line. That one-off cache flag doesn't belong in project policy.
- **cppcheck** (optional) catches a different set (portability, some bounds
  issues): `cppcheck --project=build/dev/compile_commands.json
  --enable=warning,portability --error-exitcode=1`.

## Vulnerability and dependency scanning

C has no lockfile, so make dependencies explicit and scannable:
- Keep every third-party library in one place: FetchContent declarations
  with a pinned `URL_HASH` or commit, or `vcpkg.json` with a baseline.
- Scan the **container image** (the thing you ship) with a scanner such as
  Trivy or Grype in CI. A distroless/static image with a static binary gives
  them almost nothing to flag, which is the point.
- Subscribe to security advisories for each dependency, and rebuild the
  image when the base image updates.

## The GitHub Actions workflow

`assets/github-ci.yml` → `.github/workflows/ci.yml`:
- `test`: a matrix of {gcc, clang} × {ci, ci-release}, plus clang/tsan. Each
  job runs `cmake --preset`, `cmake --build --preset`, and
  `ctest --preset`.
- `analyze`: clang-format, clang-tidy, GCC `-fanalyzer`, and cppcheck.
- `fuzz`: 60 seconds of libFuzzer.
- It runs on `ubuntu-26.04` (GA 2026-09; `ubuntu-latest` moves to it between
  2026-10-19 and 2026-11-19). **Don't use `ubuntu-24.04` for C23 code**: its
  GCC 13 lacks `<stdckdint.h>` and `#embed`, and its default Clang 18 lacks
  `constexpr`.
  Source: https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/

## What was and wasn't verified locally

Verified on macOS (Apple clang 21, CMake 4.4.3, Ninja 1.13.2):
- all configure/build/test presets except `fuzz`;
- clang-format 23.1.1 and clang-tidy 22.1.8 (from a virtualenv);
- coverage via gcovr;
- installing and consuming the library with `find_package`;
- zig 0.16 cross builds to x86_64 and aarch64 musl (static-pie) and to
  x86_64 glibc.

Not run here: GCC (none installed), `-fanalyzer`, cppcheck, libFuzzer, the
Ubuntu 26.04 package names in the workflow, and the Docker build. Treat those
steps as "verify on first CI run".
