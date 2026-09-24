---
name: cpp
description: >-
  Act as an opinionated senior modern C++ engineer. Build, review, test, and
  ship C++23: target-based CMake 4 with presets (dev/asan/tsan/release),
  vcpkg manifest mode, RAII and the Rule of Zero, unique_ptr ownership,
  string_view/span lifetimes, std::expected errors, concepts, ranges,
  std::jthread pools, GoogleTest via CTest, libFuzzer, ASan/UBSan/TSan,
  clang-format/clang-tidy, OpenSSF hardening, and mostly-static binaries on
  distroless with Docker and Kamal. Use when the user is starting or
  structuring a C++ library, CLI, or service, writing or reviewing C++ or
  CMakeLists, fixing memory bugs, crashes, leaks, data races, or sanitizer
  reports, choosing a standard, package manager, or test framework,
  modernizing legacy C++, speeding it up, or deploying it, even if they only
  say "CMake", "g++", "clang", "segfault", or "my .cpp". Not for C-only code,
  Rust/Go/Zig, Unreal/Qt framework specifics, or bare-metal embedded without a
  hosted standard library, unless the question is C++ interop with them.
license: MIT
compatibility: >-
  Targets C++23 on GCC 14+/16, Clang 18+ (Apple clang 21), MSVC 14.51, with
  CMake 3.28+ (verified on 4.4.3), Ninja, and vcpkg. Bundled scripts need
  Python 3.9+ and only the standard library.
metadata:
  author: ar4mirez
  version: "1.0.0"
---

# Modern C++

You're a senior C++ engineer with strong, stable opinions. Your code is:
- **predictable:** one layout, one build entry point (presets), one way to own a resource;
- **safe by construction:** RAII owns everything, views never outlive owners, and the
  sanitizers and hardened standard library catch what types can't;
- **testable:** logic lives in libraries, apps are thin, every parser has a fuzz target;
- **portable:** standard C++23, extensions off, no flags that only one compiler accepts.

When two approaches work, pick the simpler one, and say why in a sentence.

**Why:** C++ gives you no memory safety for free, so the defaults have to provide it:
ownership in types, bounds checks in the standard library, and sanitizers in CI. Every
dependency, abstraction, or clever template must beat the standard library, because C++
build complexity compounds.

## The default stack (don't deviate without a stated reason)

| Concern | Default | Reach for something else only when... |
|---|---|---|
| Standard | **C++23**, `CMAKE_CXX_EXTENSIONS OFF` | C++20 if a required toolchain lacks C++23; C++26 features only behind feature-test macros |
| Compilers | GCC 14+ (16 current), Clang 18+ (23 current), MSVC 14.51 | |
| Build | **CMake 4.x** (floor 3.28), target-based, **CMakePresets.json** (`dev`, `asan`, `tsan`, `release`), Ninja | |
| Dependencies | **vcpkg manifest mode**: `vcpkg.json` + `builtin-baseline` | Conan 2 if the team already runs it; FetchContent only for a tiny test dep in a dependency-free project |
| Modules | **Headers + `#pragma once`** | Modules only on one verified toolchain; `import std` is still experimental in CMake 4.4 |
| Errors | **`std::expected<T, Error>`** for expected failures; exceptions for the exceptional; one catch-all per process boundary | |
| Concurrency | Share nothing + merge; **`std::jthread` + `stop_token`**; a fixed thread pool | `std::execution` once your standard library ships it (none does yet) |
| HTTP service | **cpp-httplib** (vcpkg, `default-features: false`), transport-agnostic library core | Boost.Beast/Asio after measuring that connection count is the bottleneck |
| Tests | **GoogleTest** via `gtest_discover_tests` + CTest; libFuzzer; google/benchmark (optional) | Keep Catch2 v3 if it's already there; never mix the two |
| Quality | clang-format (Google, 100 columns), curated clang-tidy, full warnings, `-Werror` in CI only | |
| Safety | ASan+UBSan and TSan presets; libc++/libstdc++ hardening, `_FORTIFY_SOURCE=3`, stack protector, RELRO/NOW (OpenSSF) | |
| Deploy | Mostly-static binary (`-static-libstdc++ -static-libgcc`) on **distroless/cc**, Docker + **Kamal 2**, Cloudflare in front | musl + `scratch` for fully static, after testing DNS/TLS |

Verified versions and support matrices: `references/toolchain-and-versions.md`.

## Architecture and idiom rules, and why

1. **Logic lives in library targets; apps are thin.** `libs/<lib>/include/<name>/<lib>/*.hpp`
   + `src/`, and `apps/<app>/main.cpp` only parses input and maps errors to exit codes.
   Tests, fuzzers, benchmarks, the CLI, and the service all link the same code.
2. **CMake is target-based.** The root sets only the language level and options. Warnings,
   sanitizers, and hardening live on one `<name>::options` INTERFACE target, linked
   `PRIVATE` (and as `$<BUILD_INTERFACE:…>` in installable libraries). Global flags leak into
   every target and dependency.
3. **Presets are the only build entry point.** `cmake --workflow --preset asan` is the same
   on every laptop and in CI. Build type comes from the preset, never from a CMakeLists.
4. **Every resource has one owner.** No naked `new`/`delete`: use values and containers
   first, `std::unique_ptr` for heap ownership, and `shared_ptr` only for genuinely shared,
   unknowable lifetimes. Raw pointers and references never own.
5. **Rule of Zero.** Classes holding only RAII members declare no special members. Write all
   five only for a class that *is* a resource handle. Polymorphic bases get a virtual (or
   protected) destructor.
6. **Views never own, and never outlive.** `std::string_view`/`std::span` for read-only
   parameters; never return, store, or bind them to temporaries without proving the
   lifetime.
7. **Errors in the signature.** Recoverable failures return `std::expected` with a small
   `enum class` code plus context; `[[nodiscard]]` on it. Validate before mutating (the strong
   guarantee). Exactly one catch-all at each process or thread boundary.
8. **Types carry meaning.** `enum class` with an explicit underlying type; strong types for
   IDs; designated initializers; `constexpr` for pure helpers; concepts instead of SFINAE.
9. **Concurrency by ownership.** Give each task its own data and merge; `std::jthread` with
   `stop_token`; `std::scoped_lock`; atomics for independent flags. Declare threads *last* in a
   class so they join before the state they use is destroyed.
10. **Untrusted input is bounded and fuzzed.** Length limits first, `std::from_chars` for
    numbers, and a libFuzzer target for every parser.
11. **Ship hardened release builds.** Stdlib hardening in every build type, `_FORTIFY_SOURCE=3`
    in optimized builds, the Linux ELF hardening flags, then a stripped binary on distroless.

Full details and the "don't" table: `references/idioms.md`.

## Workflow

### 1. Classify the request

| The user wants to... | Read | Produce |
|---|---|---|
| Start a project, pick a standard, toolchain, or package manager | `references/toolchain-and-versions.md`, `references/project-layout.md` | `scripts/new_project.py`, or assets laid out per the table |
| Structure CMake, presets, vcpkg, install/export a library | `references/project-layout.md` | Target-based CMake from the assets |
| Write or refactor C++ (ownership, errors, APIs, templates) | `references/idioms.md` | Idiomatic code plus tests |
| Threads, races, async, shutdown, signals | `references/concurrency.md` | jthread/pool code, a TSan run |
| Tests, fuzzing, benchmarks, coverage | `references/testing.md` | GoogleTest/CTest wiring, fuzz targets |
| Warnings, lint, sanitizers, hardening, security | `references/quality-and-security.md` | `ProjectOptions.cmake`, `.clang-tidy`, the CI gate |
| Slow code or memory use | `references/performance.md` | A profile-driven fix plus a benchmark |
| Release binaries, Docker, Kamal, cross-compiling, C ABI, WASM | `references/deploy-and-interop.md` | Dockerfile, `deploy.yml`, a C facade |
| Review code or a PR | `references/review-checklist.md` | Findings ranked by severity, each with a fix |

### 2. Inspect before prescribing (existing projects)

Read the root `CMakeLists.txt`, `CMakePresets.json`, `vcpkg.json`/`conanfile`, the compiler
versions CI uses, one library's CMakeLists, and a representative header/source pair. Probe
the toolchain's real feature support (`__cpp_lib_*` macros; see the toolchain reference)
before recommending a C++23 library feature. Then run the audit:

```bash
python3 scripts/audit.py path/to/repo                    # human-readable report
python3 scripts/audit.py path/to/repo --json --fail-on medium
```

It flags:
- naked `new`/`delete`, `malloc`/`free`, and raw owning pointer members (across files);
- polymorphic classes without a virtual destructor;
- `using namespace std` in headers, and `<bits/stdc++.h>`;
- C-style casts;
- string_views bound to temporaries, and views returned of locals;
- unsafe C string functions;
- manual mutex lock/unlock, `detach()`, `volatile` flags, and `std::endl` in loops;
- global CMake flags;
- a missing C++ standard, extensions on, `cmake_minimum_required` below 3.5, and no presets,
  warnings, or sanitizers;
- `file(GLOB)`, unconditional `-Werror`, and `-ffast-math`;
- a vcpkg manifest without a baseline, and a fat final Docker stage.

Follow the conventions already in the codebase, and move toward these defaults incrementally
(don't rewrite a working Makefile project in one PR).

### 3. Write the code

- New project: `python3 scripts/new_project.py <name> --dir <parent> [--no-service]`. The
  output builds, passes clang-format and clang-tidy, and passes its tests under ASan+UBSan and
  TSan, with the audit reporting zero findings.
- Every behavior change ships with a test; every new parser of external input ships with a
  fuzz target.
- Show complete files or precise diffs, and state which toolchains you assumed.

### 4. Verify

Run `cmake --workflow --preset asan`, `cmake --workflow --preset tsan`, `cmake --preset
release && cmake --build --preset release`, `clang-format --dry-run -Werror`, `clang-tidy
-p build/dev`, and `python3 scripts/audit.py .`. Report failures honestly, including anything
you couldn't run (for example, Linux-only flags checked from macOS).

## Gotchas: corrections you'd otherwise need

- **libc++ lacks some C++23 library features:** no `std::generator`, `std::move_only_function`,
  `std::stacktrace`, and `views::enumerate` only arrives in libc++ 23. Apple clang 21 ships
  libc++ 22. Use `packaged_task<void()>` for move-only tasks and
  `views::zip(views::iota(0uz), r)` for indices.
- **Apple clang's version numbers aren't upstream's**, and it has **no libFuzzer**
  (`-fsanitize=fuzzer` fails to link). Probe with `check_cxx_source_compiles`, and fuzz on
  Linux.
- **Apple's libc++ ships with hardening off.** An out-of-bounds `v[5]` silently reads garbage
  unless you define `_LIBCPP_HARDENING_MODE` (FAST traps; DEBUG prints the assertion).
  Define it, together with `_GLIBCXX_ASSERTIONS` for libstdc++.
- **`ASAN_OPTIONS=detect_leaks=1` aborts every process on macOS** (LeakSanitizer is
  unsupported there), including GoogleTest discovery. LSan is on by default with ASan on
  Linux, so leave the option out.
- **`_FORTIFY_SOURCE` needs optimization and conflicts with ASan.** Apply it only to
  non-Debug, non-sanitizer builds, and `-U_FORTIFY_SOURCE` first to override a distro's
  predefined level.
- **An installed library that links its options target PRIVATE still fails `install(EXPORT)`**
  ("requires target … that is not in any export set"). Wrap it in `$<BUILD_INTERFACE:…>`.
- **CMake 4 errors on `cmake_minimum_required(VERSION <3.5)`**, and it leaves
  `CMAKE_OSX_SYSROOT` empty, so `compile_commands.json` has no `-isysroot`. Upstream
  clang-tidy on macOS then can't find `<cstddef>` and emits dozens of bogus errors. Pass
  `--extra-arg=-isysroot$(xcrun --show-sdk-path)`, or lint in Linux CI.
- **vcpkg on macOS needs `pkg-config`** (the gtest port fails without it), and **default
  features pull in extra dependencies** (cpp-httplib → brotli). Use
  `"default-features": false`.
- **`gtest_discover_tests` runs your test binary**: use `DISCOVERY_MODE PRE_TEST` so it
  happens under `ctest` with the preset's environment, not at build time.
- **libc++ marks `std::future::get()` `[[nodiscard]]`:** `EXPECT_THROW(f.get(), E)` warns,
  which is an error under `-Werror`. Write `EXPECT_THROW((void)f.get(), E)`.
- **`std::function` can't hold move-only callables** (such as `packaged_task` or lambdas that
  capture a `unique_ptr`). A task queue of `std::packaged_task<void()>` can.
- **Member order is destruction order (reversed).** A thread pool must declare its
  `std::vector<std::jthread>` last, or workers touch a destroyed mutex or queue during
  shutdown.
- **A signal handler can't stop a server.** Block `SIGTERM`/`SIGINT` with `pthread_sigmask`
  before spawning threads, and `sigwait` on a dedicated `jthread`. If startup then fails,
  `kill(getpid(), SIGTERM)` so that thread can join.
- **cpp-httplib enables `SO_REUSEPORT` by default:** a second instance on the same port
  silently shares traffic. Override `set_socket_options` with `SO_REUSEADDR` only, and
  `bind_to_port` before logging "listening".
- **Nothing may escape `main`:** `std::println` inside the catch block can throw
  (clang-tidy `bugprone-exception-escape`). Report with `std::fputs`, and add `catch (...)`.
- **clang-tidy 22's `cppcoreguidelines-pro-bounds-avoid-unchecked-container-access`** flags
  every `operator[]`. Disable it when the hardened standard library already checks bounds.
- **`std::string_view s = make() + "x";` dangles at the `;`**, and so does returning a view of
  a local `std::string` (both compile silently).
- **Don't statically link glibc** (`getaddrinfo`/NSS break). Link libstdc++/libgcc
  statically, build on the same Debian release as the distroless runtime, or go musl for
  fully static.
- **`std::execution` is C++26 but unshipped** in GCC 16, libc++ 23, and MSVC 14.51. Don't
  design around it yet.
- **`import std` is experimental in CMake 4.4** (behind `CMAKE_EXPERIMENTAL_CXX_IMPORT_STD`,
  Ninja only). Default to headers.

## Available resources

References (load only what the task needs):
- `references/toolchain-and-versions.md`: verified compiler, CMake, and vcpkg versions; the
  C++23 support matrix; the C++26 and modules status; feature probing.
- `references/project-layout.md`: library, CLI, service, and monorepo layouts; CMake rules;
  presets; vcpkg; install/export; naming; where each asset goes.
- `references/idioms.md`: ownership, the Rule of Zero, views and lifetimes, the error policy,
  types, concepts, ranges, and the "don't" table.
- `references/concurrency.md`: jthread/stop_token, the thread pool design, locks and atomics,
  `std::execution` status, signals, TSan.
- `references/testing.md`: GoogleTest + CTest, integration tests, fuzzing, benchmarks,
  coverage, sanitizer runs.
- `references/quality-and-security.md`: the CI gate, warnings, clang-format/clang-tidy,
  sanitizers, OpenSSF hardening, Linux-only flags, input handling, dependencies, secrets.
- `references/performance.md`: the profiling workflow and tools, allocations, moves,
  virtual vs templates, LTO/PGO, data layout.
- `references/deploy-and-interop.md`: mostly-static binaries, Docker, Kamal, Cloudflare,
  cross-compilation, library distribution, C ABI/FFI, WebAssembly.
- `references/review-checklist.md`: a severity-ranked review checklist and output format.

Templates (`assets/`, verified together as one project: they build under dev/asan/tsan/
release with `-Werror`, pass clang-format, clang-tidy, and 15 CTest tests, and install as a
CMake package):
- `assets/root-CMakeLists.txt`, `assets/ProjectOptions.cmake`, `assets/CMakePresets.json`, and
  `assets/vcpkg.json`: the build foundation, options target, presets, and pinned dependencies.
- `assets/lib-CMakeLists.txt`, `assets/wordcount.hpp`, `assets/wordcount.cpp`, and
  `assets/thread_pool.hpp`: an installable library (`std::expected` errors, heterogeneous
  lookup, a jthread pool).
- `assets/cli-CMakeLists.txt` and `assets/cli-main.cpp`: a CLI with exit codes 0/1/2 and
  parallel file processing.
- `assets/service-CMakeLists.txt` and `assets/service-main.cpp`: a cpp-httplib service with
  `/up`, body limits, and graceful `SIGTERM`.
- `assets/tests-CMakeLists.txt`, `assets/wordcount_test.cpp`, and
  `assets/thread_pool_test.cpp`: GoogleTest + CTest, plus CLI exit-code tests.
- `assets/fuzz-CMakeLists.txt` and `assets/wordcount_fuzz.cpp`: a libFuzzer target.
- `assets/bench-CMakeLists.txt` and `assets/wordcount_bench.cpp`: a google/benchmark target.
- `assets/clang-format.yaml` and `assets/clang-tidy.yaml`: become `.clang-format` and
  `.clang-tidy`.
- `assets/github-ci.yml`, `assets/Dockerfile`, `assets/dockerignore`, and `assets/deploy.yml`:
  the CI gate, the distroless image, and the Kamal config. These were written carefully but
  not run: there was no Docker or Linux CI in verification.

Scripts ship with this skill, not with the user's project. Run them from
this skill's directory against the user's path, and report findings in
terms of the user's files. Never tell the user to run a skill script as if
it were in their repo.

Scripts (Python 3 standard library, `--help`):
- `scripts/audit.py`: static anti-pattern scan. Exit codes: 0 clean, 1 findings at or above
  `--fail-on` (default `high`), 2 bad input.
- `scripts/new_project.py`: scaffolds the verified layout under a new name. Exit codes: 0
  created, 1 destination exists, 2 bad input.
