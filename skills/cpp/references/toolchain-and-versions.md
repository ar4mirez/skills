# Toolchain and versions (verified September 2026)

## Contents
- Current releases
- Language level: C++23 by default
- C++23 library support you can rely on (and what's missing)
- C++26: what shipped and what didn't
- Modules and `import std`: the honest status
- CMake 4.x changes that bite
- Dependency management: vcpkg manifest mode
- Probing a toolchain before you trust it

## Current releases

| Tool | Version | Notes | Source |
|---|---|---|---|
| ISO C++ | C++23 published; **C++26 technically complete** (approved by WG21 on 2026-03-28, ISO publication pending) | Headline C++26 features: reflection, contracts, `std::execution`, erroneous behaviour for uninitialized reads | https://herbsutter.com/2026/03/29/c26-is-done-trip-report-march-2026-iso-c-standards-meeting-london-croydon-uk/ |
| GCC | **16.2** (16.1 released April 2026) | Default dialect is now `-std=gnu++20`; C++20 no longer experimental; libstdc++ gains `std::mdspan`, `inplace_vector`, `optional<T&>`, `function_ref`; experimental reflection (`-freflection`) and contracts | https://gcc.gnu.org/gcc-16/changes.html |
| LLVM/Clang | **23.1** (August 2026); 22.1 in March 2026 | libc++ 22 fixed `bitset::operator[]` to return `bool`; partial C++26 | https://releases.llvm.org/23.1.0/tools/clang/docs/ReleaseNotes.html |
| Apple clang | **21** (Xcode/CLT 2026) ships **libc++ 22** (`_LIBCPP_VERSION 220106`) | Different version numbers from upstream: always probe features, never map versions by hand | local probe |
| MSVC | Build Tools **14.51** (VS 2026 18.6, toolset v145) | Improved C++23 (`/std:c++23preview`), `<regex>` overhaul; binary compatible back to VS 2015 | https://devblogs.microsoft.com/cppblog/c23-support-in-msvc-build-tools-14-51/ |
| CMake | **4.4.3** | See "CMake 4.x changes" below | https://cmake.org/download/ |
| vcpkg | tool 2026-07-27, registry tag **2026.07.29** | Manifest mode + `builtin-baseline` | https://learn.microsoft.com/en-us/vcpkg/reference/vcpkg-json |
| GoogleTest | **1.18.0** (vcpkg baseline has 1.17.0) | Requires C++17 | https://github.com/google/googletest/releases |
| google/benchmark | 1.9.5 | | https://github.com/google/benchmark/releases |
| clang-format / clang-tidy | 23.1 / 22.1 (PyPI wheels `clang-format`, `clang-tidy`) | Pin the version in CI; formatting output changes between majors | https://pypi.org/project/clang-tidy/ |

## Language level: C++23 by default

Set `CMAKE_CXX_STANDARD 23`, `CMAKE_CXX_STANDARD_REQUIRED ON`, `CMAKE_CXX_EXTENSIONS OFF`,
and put `target_compile_features(<lib> PUBLIC cxx_std_23)` on libraries so consumers inherit
the requirement. **Why 23:** `std::expected`, `std::print`, `std::ranges::to`, deducing
`this`, `std::mdspan`, and `std::flat_map` remove whole classes of helper code, and every
current compiler supports the core of it. **Why extensions OFF:** `gnu++23` silently accepts
VLAs, statement expressions, and other non-portable code that breaks on MSVC.

Drop to C++20 only when a required platform toolchain lacks C++23 (for example, an old
embedded GCC). Don't jump to `-std=c++26` in production code yet: support is partial and
differs per vendor.

## C++23 library support you can rely on (and what's missing)

From cppreference's compiler-support table (https://en.cppreference.com/w/cpp/compiler_support/23)
plus a local probe on Apple clang 21:

| Feature | GCC/libstdc++ | Clang/libc++ | MSVC | Apple clang 21 (probed) |
|---|---|---|---|---|
| `std::expected` | 12 | 16 | 19.33 | yes |
| `std::print` / `println` | 14 | 18 | 19.37 | yes |
| deducing `this` | 14 | 18/19 | 19.32 (full 19.43) | yes |
| `std::mdspan` | **16** | 18 | 19.39 | yes |
| `std::ranges::to` | 15 (full) | 17 | 19.34 | yes |
| `std::flat_map` | 15 | 20/21 | 19.51 | yes |
| `views::zip` | 13 | 22 (full) | partial | yes |
| `views::enumerate` | 13 | **23** | 19.37 | **no** |
| `std::generator` | 14 | not yet | 19.43 | no |
| `std::move_only_function` | 12 | not yet | 19.32 | no |
| `std::stacktrace` | 14 | not yet | 19.34 | no |
| `import std` | 15 (partial) | 17 (partial) | partial | see modules |

**Consequence:** portable code (libc++ included) avoids `std::generator`,
`std::move_only_function`, `std::stacktrace`, and `views::enumerate`. Use a counted loop or
`views::zip(views::iota(0uz), r)` instead of `enumerate`, and `std::packaged_task<void()>`
(which accepts move-only callables) instead of `move_only_function` in task queues.

## C++26: what shipped and what didn't

Per cppreference's C++26 table (https://en.cppreference.com/w/cpp/compiler_support/26),
September 2026:
- **Usable today on GCC 15+/Clang 19+:** pack indexing, `= delete("reason")`, placeholder `_`
  variables (GCC 14, Clang 18), `#embed` (GCC 15, Clang 19).
- **GCC 16 only, experimental:** contracts (`pre`/`post`/`contract_assert`), reflection
  (`-freflection`), `std::inplace_vector`, `std::simd` (partial).
- **Not shipped in any standard library yet:** `std::execution` (P2300 senders/receivers),
  `std::hive`, `<linalg>`. The reference implementation of P2300 is NVIDIA's `stdexec`
  (https://github.com/NVIDIA/stdexec); treat it as a third-party dependency, not "the
  standard", until your vendor ships it.

Rule: write C++23. Adopt a C++26 feature only behind a `__cpp_*` / `__cpp_lib_*` check or when
every toolchain you ship on supports it.

## Modules and `import std`: the honest status

- GCC 16 still marks C++20 modules **experimental** (`-fmodules`), and adds
  `--compile-std-module`.
- CMake 4.4 supports named modules with the Ninja and Visual Studio generators, but
  **`import std` is still behind the experimental gate `CMAKE_EXPERIMENTAL_CXX_IMPORT_STD`**,
  works only with Ninja, and needs Clang 18.1.2+ with libc++/libstdc++, MSVC 14.36+, or GCC
  15+. Header units aren't supported at all
  (https://cmake.org/cmake/help/latest/manual/cmake-cxxmodules.7.html).
- Apple clang's `import std` isn't listed by cppreference.

**Default: headers + `#pragma once`.** Use modules only for a single-toolchain project whose
CI proves the build works, and never in a library other people consume with a different
compiler. Revisit when `import std` leaves CMake's experimental gate.

## CMake 4.x changes that bite

From https://cmake.org/cmake/help/latest/release/4.0.html:
- `cmake_minimum_required(VERSION <3.5)` is now a **hard error**. Old third-party projects
  can be configured with `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` as a stopgap; fix your own.
  Use a range: `cmake_minimum_required(VERSION 3.28...4.4)`.
- On macOS, `CMAKE_OSX_SYSROOT` now defaults to empty, so `compile_commands.json` has no
  `-isysroot`. Apple clang finds the SDK itself, but a non-Apple clang-tidy doesn't (see
  `quality-and-security.md`).
- 3.28 is the floor for this skill: presets v8, `FILE_SET HEADERS`, C++23 feature detection,
  and stable module scanning.

## Dependency management: vcpkg manifest mode

Default: `vcpkg.json` at the repo root with `"builtin-baseline"` pinned to a vcpkg registry
commit, and `CMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake` in the base
preset. `cmake --preset …` then installs dependencies into `build/<preset>/vcpkg_installed`
automatically. Details: `project-layout.md`.

- **Pin the baseline** (`vcpkg x-update-baseline --add-initial-baseline`), or versions float
  with whatever vcpkg checkout the machine has. Use `"overrides"` for an exact pin of one port.
- **Turn off default features you don't need** (`"default-features": false`). For example,
  cpp-httplib pulls in brotli by default.
- **Optional dependencies are features** (`"features": {"bench": ...}`), enabled with
  `-DVCPKG_MANIFEST_FEATURES=bench`.
- **Binary cache:** set `VCPKG_DEFAULT_BINARY_CACHE` to a cached directory in CI.
- Conan 2 is a fine alternative when a team already runs it. Don't mix both in one repo.
- `FetchContent` only for a tiny, header-only test dependency in a project that otherwise
  needs no package manager. It builds the dependency with *your* flags and warnings, and it
  re-downloads per build tree.

## Probing a toolchain before you trust it

Feature-test macros are the truth. Apple's versions don't map to upstream versions:

```bash
c++ -std=c++23 -dM -E -x c++ /dev/null -include version \
  | grep -E '_LIBCPP_VERSION|__GLIBCXX__|__cpp_lib_(expected|print|mdspan|generator|move_only_function|ranges_enumerate|execution)'
```

In code, guard optional features with `#if __cpp_lib_generator >= 202207L`.
