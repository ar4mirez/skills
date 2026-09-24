# Project layout and build

## Contents
- Layouts: library, CLI, service, monorepo
- CMake rules (the ones agents get wrong)
- Presets
- Installing and exporting a library
- Dependencies
- Meson (the acceptable alternative)

## Layouts

`scripts/new_project.py NAME DIR --kind lib|cli|service` produces these from
the tested assets.

**(a) Library**
```
include/<name>/<name>.h     public API only: opaque types, status enum, ownership comments
src/<name>.c                implementation; internal headers live beside it (src/arena.h)
tests/test.h                zero-dependency CHECK macros
tests/test_<name>.c         one executable per test file, one add_test() each
fuzz/fuzz_parse.c           libFuzzer target for every parser that takes bytes
cmake/zig-toolchain.cmake   optional cross-compilation
CMakeLists.txt  CMakePresets.json  .clang-format  .clang-tidy  .github/workflows/ci.yml
```
Public headers go under `include/<name>/` so consumers write
`#include <name/name.h>`. That avoids collisions with other libraries' headers,
such as a second `util.h`.

**(b) CLI.** Everything in (a), plus `app/cli.c`. The CLI is a thin `main`: it
parses argv, calls the library, and maps statuses to exit codes (0 ok, 1
"not found" or findings, 2 usage). All logic lives in the library, where it's
tested without spawning processes.

**(c) Network service.** Everything in (b), plus:
- `app/http_handler.{c,h}`: **pure** request-to-response code with no
  sockets, unit-tested and fuzzable.
- `app/server.c`: the socket loop, threads, and signals, kept as thin as
  possible.
- `Dockerfile` and `config/deploy.yml`.

Put TLS, HTTP/2, and rate limiting in the proxy (kamal-proxy, Cloudflare),
never in your C code.

**(d) Monorepo / multi-package.** Use one top-level CMake project with one
directory per component:
```
CMakeLists.txt              project(), policy targets (warnings/hardening/sanitizers), add_subdirectory() each
libs/<a>/CMakeLists.txt     add_library(a ...) + add_library(org::a ALIAS a)
libs/<b>/CMakeLists.txt     target_link_libraries(b PUBLIC org::a)
apps/<tool>/CMakeLists.txt
tests/…  or  libs/<a>/tests/…
```
Link only through `org::x` alias targets. A typo in an alias target name is a
configure error; a typo in a plain name silently becomes `-lx`. Keep the
policy targets in the top-level file so every component gets the same
warnings and hardening. Split into separate repositories only when release
cadence or ownership differ.

## CMake rules (the ones agents get wrong)

The full working file is `assets/CMakeLists.txt`.

1. **`cmake_minimum_required(VERSION 3.25...4.4)`.** The range sets policies
   up to 4.4 while still allowing 3.25. Anything below 3.5 **errors** under
   CMake 4. `CMAKE_POLICY_VERSION_MINIMUM=3.5` is only a stopgap for configuring
   old third-party code.
2. **Target commands only.** Use `target_compile_options`,
   `target_include_directories`, `target_link_libraries`, and
   `target_compile_definitions`. Never set `CMAKE_C_FLAGS`, and never call
   `add_compile_options`, `include_directories`, `link_libraries`, or
   `add_definitions` in project files. Global flags leak into
   FetchContent dependencies, can't be scoped per target, and can't be
   exported.
3. **Policy lives on INTERFACE targets.** `kvstore_warnings`,
   `kvstore_hardening`, and `kvstore_sanitizers` are linked
   `PRIVATE $<BUILD_INTERFACE:...>`. The `BUILD_INTERFACE` part matters: a
   static library's PRIVATE link dependencies still end up in its export set,
   and `install(EXPORT)` fails with "requires target kvstore_warnings that is
   not in any export set". That was verified with CMake 4.4.3.
4. **`-Werror` lives in the CI preset.** Set
   `CMAKE_COMPILE_WARNING_AS_ERROR=ON` there. Hard-coding it in the
   CMakeLists breaks every downstream build on the next compiler release,
   which adds warnings. The OpenSSF guide says the same thing. Locally,
   `cmake --compile-no-warning-as-error` overrides it.
5. **Probe flags; don't switch on OS or architecture.** Use
   `check_c_compiler_flag` and `check_linker_flag` under
   `CMAKE_REQUIRED_FLAGS=-Werror`. Without `-Werror`, Apple clang's
   "argument unused" warning for `-fstack-clash-protection` counts as
   success, and the flag then warns on every compile.
6. **List sources explicitly.** Don't use `file(GLOB)`: a new file is
   silently missed until someone re-runs configure.
7. **PIE:** set the `POSITION_INDEPENDENT_CODE ON` property and call
   `check_pie_supported()` once. CMake then passes `-fPIE` at compile time
   and `-pie` at link time. Without `check_pie_supported()`, you only get
   `-fPIE`.
8. **Visibility:** set `C_VISIBILITY_PRESET hidden` so only symbols you mark
   are exported from shared libraries (see `deploy-and-interop.md`).
9. **Tests are opt-out for consumers.** Use
   `option(X_BUILD_TESTS "..." ${PROJECT_IS_TOP_LEVEL})`, so a project that
   pulls you in with FetchContent doesn't build your tests.

## Presets

`assets/CMakePresets.json` uses schema v6 (CMake ≥ 3.25; 4.4 supports v12).
It defines:

| Preset | Purpose |
|---|---|
| `dev` | Debug, hardening on (except `_FORTIFY_SOURCE`, which needs optimization) |
| `asan` | Debug + ASan + UBSan, with `-fno-sanitize-recover=all` so UB fails the test |
| `tsan` | Debug + TSan (can't be combined with ASan) |
| `release` | Release + full hardening, tests still built and run |
| `coverage` | Debug + `--coverage` (gcov format; report with gcovr) |
| `ci`, `ci-release` | `asan` / `release` + `CMAKE_COMPILE_WARNING_AS_ERROR` |
| `fuzz` | LLVM clang + libFuzzer + ASan/UBSan |

Run a full gate with `cmake --workflow --preset ci`
(configure → build → test). Test presets set `outputOnFailure` and
`noTestsAction: error`, so a misconfigured build that registers no tests
fails instead of passing.

Reference: https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html

## Installing and exporting a library

- `target_sources(x PUBLIC FILE_SET HEADERS BASE_DIRS include FILES ...)`
  (CMake ≥ 3.23) installs headers with the target, with no separate
  `install(DIRECTORY)`.
- `install(TARGETS x EXPORT xTargets FILE_SET HEADERS)`, then
  `install(EXPORT xTargets NAMESPACE x:: FILE xConfig.cmake DESTINATION
  ${CMAKE_INSTALL_LIBDIR}/cmake/x)`. Naming the export file `xConfig.cmake`
  directly is enough when the library has no `find_dependency` needs. Add a
  `Config.cmake.in` with `CMakePackageConfigHelpers` only when it does.
- Consumers write `find_package(x REQUIRED)` and
  `target_link_libraries(app PRIVATE x::x)`. This was verified from a
  `-std=c11 -Wpedantic -Werror` consumer.

## Dependencies

C has no universal package manager. Use this order of preference:
1. **Don't add one.** The C library plus POSIX covers most needs. A 200-line
   module you own often beats a dependency you have to track for CVEs.
2. **System packages via `find_package()`** for large, stable libraries
   (OpenSSL, zlib, libcurl, SQLite). Distros patch them.
3. **`FetchContent` pinned by hash** for small libraries without good
   packaging: `FetchContent_Declare(x URL https://…/x-1.2.3.tar.gz
   URL_HASH SHA256=…)`, or a `GIT_TAG` set to a full commit SHA, never a
   branch. Record every vendored dependency and its version in one place, so
   security updates are one diff.
4. **vcpkg manifest mode** (`vcpkg.json` + a toolchain file) only when you
   have many third-party libraries across Windows, macOS, and Linux.

Never commit a copy of a dependency with local edits and no recorded upstream
version.

## Meson (the acceptable alternative)

Meson + Ninja is a fine choice, especially in the GNOME and systemd ecosystem.
Its `b_sanitize`, `b_pie`, and `warning_level` options cover much of this.
Don't mix build systems in one repository, and don't convert a working Meson
project to CMake without a reason. New projects here use CMake, because
editors, clang-tidy, vcpkg, and the CI templates assume it.
