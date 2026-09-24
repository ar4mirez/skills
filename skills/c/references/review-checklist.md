# Review checklist (severity-ranked)

## Contents
- How to review
- Critical: exploitable or crashes
- High: undefined behavior, leaks, wrong results
- Medium: build and gate hygiene
- Low: style, portability, performance
- Output format

## How to review

1. Run `python3 scripts/audit.py <repo> --json`. It covers the mechanical
   patterns (banned functions, unchecked allocations, CMake hygiene). Read
   every hit in context: it's heuristic.
2. Then read by hand for what regexes can't see: ownership, lifetimes, error
   paths, and concurrency.
3. If the project builds, run the `asan` and `tsan` presets and the fuzz
   target. A sanitizer report beats any amount of reading.

## Critical: exploitable or crashes

- [ ] `gets`, `strcpy`, `strcat`, `sprintf`, or `scanf("%s")` on data the
      caller doesn't control.
- [ ] A format string from input: `printf(buf)`, `syslog(prio, msg)`.
- [ ] Size arithmetic from input without an overflow check:
      `malloc(n * size)`, `len + 1` near `SIZE_MAX`.
- [ ] A returned pointer to a stack buffer (`char out[512]; ... return out;`).
- [ ] Use-after-free: freeing a struct, then its members; or a borrowed
      pointer used after the owner changed.
- [ ] Double free on an error path.
- [ ] `system()`/`popen()` with interpolated data (shell injection).
- [ ] Missing length checks before `memcpy` into fixed buffers.

## High: undefined behavior, leaks, wrong results

- [ ] An allocation result used without a NULL check.
- [ ] `p = realloc(p, n)`, which leaks on failure.
- [ ] Leaks on early returns. Use one `goto out` cleanup path.
- [ ] `volatile` used as a thread flag, or unsynchronized shared mutable
      state (should be `<stdatomic.h>` or a mutex). Look for any non-const
      global touched by threads.
- [ ] Signal handlers calling `printf`/`malloc`/locks (use `sigwait` or a
      `volatile sig_atomic_t` flag).
- [ ] `atoi`/`atof`, or `strtol` without `errno = 0` plus end and range
      checks.
- [ ] `assert` with side effects (vanishes under `NDEBUG`).
- [ ] Signed overflow, shifts ≥ width, or signed/unsigned comparisons on
      input-derived values.
- [ ] Implicit function declarations or K&R (old-style) definitions (both
      errors in C23), or `void main` (not portable: hosted `main` returns
      `int`; compilers warn rather than error).
- [ ] Ignored return values of `fread`, `fclose` (writes), `snprintf`
      (truncation), or `pthread_create`.

## Medium: build and gate hygiene

- [ ] `cmake_minimum_required` < 3.5 (fails on CMake 4), or < 3.21 (no
      `C_STANDARD 23`).
- [ ] Global flags: `set(CMAKE_C_FLAGS ...)`, `add_compile_options`,
      `include_directories`, `add_definitions`, or `link_libraries(pthread)`
      (use `Threads::Threads`).
- [ ] No warnings policy (`-Wall -Wextra -Wpedantic -Wconversion -Wshadow
      -Wformat=2 -Wimplicit-fallthrough`).
- [ ] No hardening in release builds (FORTIFY 3, stack protector, PIE,
      RELRO), or hardening flags that aren't probed (breaks macOS or ARM).
- [ ] No tests registered with CTest, no sanitizer preset, or no fuzz target
      for parsers.
- [ ] Headers without include guards, or public headers that require C23
      (consumers may use C11/C17).
- [ ] Ownership not documented on pointer-returning or pointer-taking public
      functions.
- [ ] `<threads.h>` in code that must build on macOS.

## Low: style, portability, performance

- [ ] `-Werror` hard-coded in CMakeLists (move it to the CI preset).
- [ ] `file(GLOB)` sources, no `CMakePresets.json`, or no C standard set.
- [ ] `strncpy`/`strtok`, `rand()` for anything but simulations.
- [ ] `strlen` in loop conditions, repeated `realloc` by small increments.
- [ ] Unprefixed public symbols, non-`static` internal functions, or
      `#define` constants where `enum`/`constexpr` works.
- [ ] Runtime container is a full distro, or runs as root.

## Output format

Group findings by severity, most severe first. For each finding give:
`file:line`, the problem in one sentence, *why* it matters (the exploit or
UB), and the concrete fix, as code when it's short. End with the three
changes to make first.
