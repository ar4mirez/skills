# Project layout, CMake, presets, and dependencies

## Contents
- One layout for everything
- Library-only, CLI-only, service, and monorepo variants
- Where each asset goes
- CMake rules (target-based, one options target)
- Presets
- vcpkg manifest mode
- Installing and exporting a library
- Naming and file conventions

## One layout for everything

```
<repo>/
  CMakeLists.txt            # project(), language level, options, add_subdirectory — no flags
  CMakePresets.json         # dev, asan, tsan, release (+ workflows)
  vcpkg.json                # dependencies + builtin-baseline
  .clang-format .clang-tidy .dockerignore Dockerfile
  cmake/ProjectOptions.cmake  # <name>::options: warnings, sanitizers, hardening
  libs/<lib>/
    CMakeLists.txt
    include/<name>/<lib>/*.hpp  # public headers: namespaced path, so includes read "<name>/<lib>/x.hpp"
    src/*.cpp                   # private sources and private headers
  apps/<app>/{CMakeLists.txt, main.cpp}   # thin: parse args/env, call libs, map errors to exit codes
  tests/                     # GoogleTest + CTest; one test file per library unit
  fuzz/ bench/               # optional, off by default
  config/deploy.yml          # Kamal (services only)
  .github/workflows/ci.yml
```

**Why:** every piece of logic lives in a library target, so tests, fuzzers, benchmarks, the
CLI, and the service all link the same code. Apps stay thin enough that they rarely need
their own tests. The namespaced include directory (`include/<name>/<lib>/`) prevents header
collisions once installed.

## Variants

- **Library only:** keep `libs/<lib>` + `tests/`; drop `apps/`. Add install/export rules
  (below) and a `vcpkg.json` with `"name"`/`"version"` so it can become a port. Library
  headers never set global state, never `using namespace`, and never require the consumer's
  warning flags.
- **CLI:** `apps/<cli>/main.cpp` owns argument parsing and exit codes (0 ok, 1 runtime
  failure, 2 usage). Parse with a hand-written loop over `std::span(argv, argc)` until you
  have more than ~5 flags; then use CLI11 (vcpkg `cli11`).
- **Network service:** `apps/<svc>/main.cpp` wires transport to library functions. Keep the
  request handling logic in the library, transport-agnostic (the reference `render()` and
  `Counter` know nothing about HTTP), so it's unit-testable without sockets. The HTTP layer
  is cpp-httplib (a single header, blocking I/O with a thread pool, `httplib::httplib`
  target). Reach for Boost.Beast/Asio or Drogon only when you need async I/O at high
  connection counts, and measure first.
- **Monorepo:** more `libs/*` and `apps/*` under one root `CMakeLists.txt`, one
  `vcpkg.json`, one preset file. Libraries depend on libraries through
  `target_link_libraries`, never through include paths. Apps never depend on apps. Split a
  library into its own repo only when another team consumes it on its own release cadence.

## Where each asset goes

`scripts/new_project.py <name>` lays these out for you (renaming `acme` to `<name>`):

| Asset | Destination |
|---|---|
| `root-CMakeLists.txt` | `CMakeLists.txt` |
| `ProjectOptions.cmake` | `cmake/ProjectOptions.cmake` |
| `CMakePresets.json`, `vcpkg.json`, `Dockerfile` | repo root |
| `clang-format.yaml`, `clang-tidy.yaml`, `dockerignore` | `.clang-format`, `.clang-tidy`, `.dockerignore` |
| `lib-CMakeLists.txt`, `wordcount.hpp`, `thread_pool.hpp`, `wordcount.cpp` | `libs/wordcount/…` (headers under `include/<name>/wordcount/`) |
| `cli-CMakeLists.txt`, `cli-main.cpp` | `apps/wc/` |
| `service-CMakeLists.txt`, `service-main.cpp` | `apps/wc-server/` |
| `tests-CMakeLists.txt`, `wordcount_test.cpp`, `thread_pool_test.cpp` | `tests/` |
| `fuzz-CMakeLists.txt`, `wordcount_fuzz.cpp` | `fuzz/` |
| `bench-CMakeLists.txt`, `wordcount_bench.cpp` | `bench/` |
| `github-ci.yml` | `.github/workflows/ci.yml` |
| `deploy.yml` | `config/deploy.yml` |

## CMake rules (target-based, one options target)

1. **Only language level and options at the top.** `CMAKE_CXX_STANDARD`,
   `CMAKE_CXX_STANDARD_REQUIRED`, `CMAKE_CXX_EXTENSIONS OFF`, `CMAKE_EXPORT_COMPILE_COMMANDS`.
   No `add_compile_options`, `include_directories`, `add_definitions`, `link_libraries`, or
   `CMAKE_CXX_FLAGS`: they leak into every target, including fetched dependencies, and they
   can't be scoped PUBLIC/PRIVATE.
2. **One `<name>::options` INTERFACE target** holds warnings, sanitizers, and hardening. Link
   it `PRIVATE`. In a library that gets installed, wrap it: `PRIVATE
   $<BUILD_INTERFACE:<name>::options>`. Otherwise `install(EXPORT)` fails because the options
   target isn't in the export set, and consumers would inherit your `-Werror`.
3. **Usage requirements on targets:** `target_compile_features(lib PUBLIC cxx_std_23)`,
   `target_link_libraries(lib PUBLIC Threads::Threads)`, and headers via `target_sources(...
   FILE_SET HEADERS BASE_DIRS include FILES ...)`.
4. **List sources explicitly.** `file(GLOB)` misses new files until the next configure.
5. **Build type comes from the preset**, never `set(CMAKE_BUILD_TYPE …)` in a CMakeLists.
6. **Options are prefixed** (`ACME_BUILD_TESTS`, `ACME_SANITIZERS`) and default tests to
   `${PROJECT_IS_TOP_LEVEL}`, so the project behaves as a dependency when added via
   `add_subdirectory` or a package manager.
7. **`-Werror` only via an option set in CI** (`-DACME_WARNINGS_AS_ERRORS=ON`). OpenSSF warns
   that unconditional `-Werror` in distributed source breaks users on newer compilers.

## Presets

`CMakePresets.json` (schema v8, CMake 3.28+) is the single source of build configurations:

| Preset | Build type | Adds | Use |
|---|---|---|---|
| `dev` | Debug | libc++ debug hardening | day-to-day, IDE |
| `asan` | Debug | `address;undefined` | CI + before every PR |
| `tsan` | RelWithDebInfo | `thread` | CI for anything with threads |
| `release` | Release + IPO/LTO | `_FORTIFY_SOURCE=3`, `-ftrivial-auto-var-init=zero` | shipping |

`cmake --workflow --preset asan` runs configure, build, and test in one command. Put
machine-specific settings (a local compiler path) in the gitignored `CMakeUserPresets.json`,
never in the committed file. Schema v11 (CMake 4.3) and v12 (4.4) exist; stay on v8 until
every developer and CI image has 4.3+.

## vcpkg manifest mode

- The base preset sets `"toolchainFile": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"`.
  Configure runs `vcpkg install` into `build/<preset>/vcpkg_installed/` (verified: gtest
  1.17.0 and cpp-httplib 0.51.0 from baseline `9e593bb1…`, tag 2026.07.29).
- `find_package(GTest CONFIG REQUIRED)` + `GTest::gtest_main`; `find_package(httplib CONFIG
  REQUIRED)` + `httplib::httplib`; `find_package(benchmark CONFIG REQUIRED)` +
  `benchmark::benchmark_main`. After `vcpkg install`, each port prints its exact CMake usage.
- **macOS needs `pkg-config`** on PATH for many ports (the gtest port calls
  `vcpkg_fixup_pkgconfig`, and the build fails without it).
- Bump the baseline deliberately (`vcpkg x-update-baseline`) in its own PR, and keep the CI
  `VCPKG_COMMIT` equal to it.

## Installing and exporting a library

The `lib-CMakeLists.txt` asset installs the target with its header file set, exports
`acmeTargets.cmake` under `lib/cmake/acme`, and writes `acmeConfig.cmake` (which re-finds
`Threads`) plus a `SameMajorVersion` version file. Verified: `cmake --install` followed by an
external project doing `find_package(acme 0.1 CONFIG REQUIRED)` +
`target_link_libraries(consumer PRIVATE acme::wordcount)` builds and runs. Set `EXPORT_NAME`
so the installed target is `acme::wordcount`, matching the in-tree `ALIAS`.

## Naming and file conventions

- Files `snake_case.hpp/.cpp`; one class or cohesive unit per pair. `.hpp` for C++ headers
  (`.h` signals C-compatible).
- Types `PascalCase`; functions and variables `snake_case`; private members with a trailing
  `_`; constants `kPascalCase`; macros `UPPER_CASE` (and rare). Enumerators `snake_case`
  inside `enum class`.
- Namespaces mirror directories (`acme::wordcount` ↔ `include/acme/wordcount/`). Put
  file-local helpers in an anonymous namespace, not `static` functions in headers.
- `#pragma once` in every header: all target compilers support it and it can't collide.
