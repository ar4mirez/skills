# C++ code review checklist

Report findings **ranked by severity**. Give each one a file and line, what's wrong, why it
matters (one sentence), and the concrete fix (code). Run `python3 scripts/audit.py <root>`
first; it finds the mechanical issues, so you can spend review time on lifetimes, ownership,
and design.

## Critical: memory safety and undefined behavior

- [ ] A view (`std::string_view`, `std::span`, a range view, an iterator, a reference) that
      outlives its owner: a view returned from a local, bound to a temporary, stored in a
      member, or captured by a lambda that runs later.
- [ ] A raw owning pointer member (`T*` that gets `delete`d or `free`d) in a copyable class:
      the implicit copy double-frees. Also, any naked `new`/`delete` or `malloc`/`free`.
- [ ] A polymorphic base without a virtual (or protected) destructor, deleted through a base
      pointer.
- [ ] Out-of-bounds access, including `operator[]` with an unchecked index from input, and
      signed/unsigned mix-ups in bounds checks.
- [ ] Data races: shared mutable state without a mutex or atomic; `volatile` as a
      synchronization flag; detached threads touching data that dies.
- [ ] Unsafe C string functions (`strcpy`, `sprintf`, `gets`), and user data used as a format
      string.
- [ ] Uninitialized variables, reads of moved-from objects, and signed overflow in size math.
- [ ] Exceptions escaping destructors, `noexcept` functions, thread entry points, or
      `extern "C"` functions.

## High: correctness and resource handling

- [ ] Manual `lock()`/`unlock()`, or a mutex held while calling unknown code.
- [ ] Error returns ignored: `std::expected`/error codes without `[[nodiscard]]`, or
      unchecked I/O results.
- [ ] A mutation that fails halfway, leaving the object half-updated (validate first, then
      commit).
- [ ] Member declaration order that destroys something threads or callbacks still use.
- [ ] A class that declares some special members but not all of them (Rule of Five), or
      non-`noexcept` moves in types stored in vectors.
- [ ] `using namespace std;` in a header, or macros that leak from headers.
- [ ] Signal handlers calling non-async-signal-safe functions (use `sigwait` on a thread).
- [ ] Unbounded input: no size cap on request bodies, files, or recursion depth.

## Medium: build, tooling, and portability

- [ ] Global CMake flags (`add_compile_options`, `include_directories`, `CMAKE_CXX_FLAGS`) instead
      of `target_*`; `file(GLOB)` sources; hard-coded `CMAKE_BUILD_TYPE`.
- [ ] No C++ standard set, extensions on (`gnu++`), or `cmake_minimum_required` below 3.5
      (a hard error in CMake 4).
- [ ] No `CMakePresets.json`, no sanitizer presets, or tests not wired into CTest.
- [ ] `vcpkg.json` without `builtin-baseline`; default features left on; dependencies vendored
      or fetched ad hoc.
- [ ] Warnings not enabled, `-Werror` unconditional, or `-ffast-math`/`-Ofast` global.
- [ ] Hardening missing from release builds (stdlib hardening mode, `_FORTIFY_SOURCE=3`,
      stack protector; RELRO/NOW on Linux).
- [ ] Features that aren't portable across the target toolchains (`std::generator`,
      `std::move_only_function`, `views::enumerate` on libc++; `import std` without a
      verified toolchain; `<bits/stdc++.h>`).
- [ ] A final Docker stage that ships a compiler image, or a glibc version mismatch between
      the build and runtime images.

## Low: idiom and style

- [ ] C-style casts, `NULL`, `std::endl` in loops, plain `enum`, `std::thread` where
      `std::jthread` fits.
- [ ] SFINAE where a concept would do; CRTP where deducing `this` would do.
- [ ] `shared_ptr` where `unique_ptr` or a reference suffices.
- [ ] Missing `#pragma once`, headers that don't include what they use.
- [ ] `std::stoi`/`atoi` instead of `std::from_chars` for untrusted input.
- [ ] Tests that sleep, test private details, or don't cover error paths.

## Output format

```
1. [critical] src/registry.cpp:32 — Registry::label() returns a string_view of the local
   `full`, which is destroyed on return → dangling read.
   Fix: return std::string (or store the label as a std::string member and return a view of it).
```
Group mechanical audit findings in one item per check ("naked new/delete: 6 sites → use
unique_ptr/containers") so the human-level issues stay visible.
