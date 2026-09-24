# Quality gate, hardening, and security

## Contents
- The gate (what CI enforces)
- Warnings
- clang-format
- clang-tidy
- Sanitizers
- Hardening flags (OpenSSF)
- Linux-only flags and what was verified on macOS
- Input handling
- Dependency hygiene and vulnerability scanning
- Secrets

## The gate (what CI enforces)

`assets/github-ci.yml` runs on every push and PR, with zero warnings:
1. `clang-format --dry-run -Werror` on every tracked `.cpp`/`.hpp`.
2. `clang-tidy -p build/dev` on every translation unit (`.clang-tidy` has
   `WarningsAsErrors: '*'`).
3. Build and test with the `asan` (ASan+UBSan) and `tsan` presets, and build `release`, all
   with `-DACME_WARNINGS_AS_ERRORS=ON`.
4. A 60-second libFuzzer run.
5. `python3 scripts/audit.py . --fail-on medium` is a cheap extra step for repos that adopt
   this skill.

Pin tool versions (`clang-format==23.1.1`, `clang-tidy==22.1.8`, `cmake==4.4.3` from PyPI),
because formatter output and tidy checks change between major versions.

## Warnings

GCC/Clang set (in `ProjectOptions.cmake`): `-Wall -Wextra -Wpedantic -Wconversion
-Wsign-conversion -Wshadow -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual
-Wcast-align -Wnull-dereference -Wdouble-promotion -Wformat=2 -Wimplicit-fallthrough`.
MSVC: `/W4 /permissive- /utf-8 /Zc:__cplusplus` plus a few off-by-default warnings.
- `-Wconversion -Wsign-conversion` are noisy on old code but catch real truncation bugs; fix
  them with `static_cast` at the boundary where the range is known.
- `-Werror` only in CI (via the option), never hard-coded (OpenSSF guidance for
  distributed source).
- Warnings apply to your targets only (through the options target), not to vcpkg
  dependencies, which are consumed as `SYSTEM` includes.

## clang-format

`assets/clang-format.yaml` → `.clang-format`: Google base style, 100 columns, left-aligned
pointers, include blocks regrouped (standard library, C/system, third-party, project), with
the matching header first. Formatting isn't a code-review topic: run `clang-format -i` and
move on.

## clang-tidy

`assets/clang-tidy.yaml` → `.clang-tidy` enables `bugprone-*`, `concurrency-*`,
`cppcoreguidelines-*`, `modernize-*`, `performance-*`, and selected `misc-*`/`readability-*`
checks, with each disable justified in a comment:
- `bugprone-easily-swappable-parameters` and `cppcoreguidelines-avoid-magic-numbers` fire on
  almost every function.
- `cppcoreguidelines-pro-bounds-avoid-unchecked-container-access` (new in LLVM 21/22) flags
  every `operator[]`. The hardened standard library already bounds-checks it, so the check
  adds noise, not safety.
- `readability-implicit-bool-conversion` fights the idiomatic `if (!expected)`.
- `modernize-use-trailing-return-type` is style; `modernize-use-nodiscard` is applied
  deliberately instead.

Checks that caught real issues in the reference project: `bugprone-exception-escape` (a
`std::println` inside `main`'s catch block can itself throw; use `std::fputs`),
`bugprone-implicit-widening-of-multiplication-result` (`1024 * 1024` computed in `int`),
and `cppcoreguidelines-init-variables` (`sigset_t signals;`).

**Running clang-tidy on macOS:** CMake 4 no longer puts `-isysroot` in
`compile_commands.json`, so an upstream clang-tidy (PyPI or Homebrew) can't find
`<cstddef>`, and then it reports dozens of bogus follow-on errors. Pass the SDK:
```bash
SDK=$(xcrun --show-sdk-path)
clang-tidy -p build/dev --extra-arg=-isysroot"$SDK" --extra-arg=-isystem"$SDK/usr/include/c++/v1" file.cpp
```
or run clang-tidy only in Linux CI. Suppress individual lines with
`// NOLINT(check-name): reason`, never a bare `NOLINT`.

## Sanitizers

| Preset | Sanitizers | Catches |
|---|---|---|
| `asan` | `address;undefined` | out-of-bounds, use-after-free/return/scope, double free, leaks (Linux), signed overflow, misaligned access, bad casts, null deref |
| `tsan` | `thread` | data races, lock-order inversions |

- Built with `-fno-omit-frame-pointer -fno-sanitize-recover=all`.
- ASan and TSan are mutually exclusive, and `_FORTIFY_SOURCE` conflicts with ASan; the
  options target handles both.
- Test env: `ASAN_OPTIONS=abort_on_error=1:detect_stack_use_after_return=1`,
  `UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1`, `TSAN_OPTIONS=halt_on_error=1`.
- MSVC supports `/fsanitize=address` only.

## Hardening flags (OpenSSF)

Source: OpenSSF *Compiler Options Hardening Guide for C and C++* (updated 2026-08-20),
https://best.openssf.org/Compiler-Hardening-Guides/Compiler-Options-Hardening-Guide-for-C-and-C++.html

| Flag / macro | Where the template applies it | Why |
|---|---|---|
| `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST` (Release), `…_DEBUG` (Debug) | all non-MSVC | libc++ bounds and precondition checks; `FAST` is the low-overhead mode most projects ship |
| `-D_GLIBCXX_ASSERTIONS` | all non-MSVC | the libstdc++ equivalent (defining both is harmless: each library ignores the other's macro) |
| `-fstack-protector-strong` | all non-MSVC | stack canaries |
| `-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3` | optimized, non-sanitizer builds | checked libc buffer functions; needs `-O1`+ and conflicts with ASan; `-U` first because some distros predefine level 2 |
| `-ftrivial-auto-var-init=zero` | optimized, non-sanitizer builds | uninitialized stack reads become zero instead of leaking data |
| `-fstack-clash-protection` | Linux | stack clash attacks |
| `-fcf-protection=full` | Linux x86_64 | CET indirect branch tracking and shadow stack |
| `-mbranch-protection=standard` | Linux AArch64 | PAC/BTI |
| `-Wl,-z,relro -Wl,-z,now -Wl,-z,noexecstack` | Linux (ELF) | read-only relocations, non-executable stack |
| `-Wl,--as-needed -Wl,--no-copy-dt-needed-entries` | Linux | no stray DT_NEEDED |
| PIE (`CMAKE_POSITION_INDEPENDENT_CODE ON` + `check_pie_supported()`) | everywhere | full ASLR |

**Apple's libc++ ships with hardening off** (`_LIBCPP_HARDENING_MODE_DEFAULT` is
`_LIBCPP_HARDENING_MODE_NONE`). Verified: `v[5]` on a 2-element vector returns garbage with
no flag, traps (exit 133, SIGTRAP) with `FAST`, and prints `libc++ Hardening assertion __n <
size() failed` with `DEBUG`. Don't assume the vendor protected you.

Not in the template, deliberately: GCC's `-fhardened` (GCC 14+, bundles many of the above but
is GCC-only), `-fno-strict-overflow`/`-fno-strict-aliasing`/`-fno-delete-null-pointer-checks`
(OpenSSF lists them for production C code; they cost optimization, and UBSan finds the bugs
they paper over), and `-fzero-call-used-regs` (measure first). Add them per project after
benchmarking.

## Linux-only flags and what was verified on macOS

The reference project was built and tested on macOS (Apple clang 21, arm64). There the
template applies the stdlib hardening macros, `-fstack-protector-strong`,
`_FORTIFY_SOURCE=3`, `-ftrivial-auto-var-init=zero`, and PIE, and they compile warning-free.
The Linux branch (`-fstack-clash-protection`, `-fcf-protection=full`,
`-mbranch-protection=standard`, the `-z` linker flags, `--as-needed`, and `-static-libstdc++
-static-libgcc` for the service) **was not exercised on macOS**, and the Dockerfile and CI
workflow were not run. Check them on the first Linux CI run with `checksec --file=<binary>`
or `readelf -d` / `readelf -l`.

## Input handling

- Treat every byte from the network, files, argv, and env as hostile: validate length first,
  then content, then act. `Limits` in the reference library bounds word length; the service
  caps request bodies with `set_payload_max_length` (1 MiB, which returns 413).
- Parse numbers with `std::from_chars` (no locale, no exceptions, reports range errors), not
  `atoi`/`stoi`.
- Every parser of untrusted input gets a fuzz target.
- Never build shell commands, SQL, or paths by string concatenation with user data; use
  argument vectors, parameterized queries, and `std::filesystem::path` with a checked root.
- Format strings are compile-time checked with `std::format`/`std::print`; never pass user
  data as a `printf` format (`-Wformat=2 -Werror=format-security`).

## Dependency hygiene and vulnerability scanning

- Every dependency is a port in `vcpkg.json`, pinned by `builtin-baseline`: no vendored
  copies, no `curl | sh`, no Git submodules of random forks.
- `"default-features": false` plus explicit features, so you don't pull in compression or TLS
  stacks you don't use.
- Scanning: C/C++ has no `cargo audit`. Generate an SBOM from the vcpkg install (vcpkg writes
  SPDX files to `vcpkg_installed/<triplet>/share/<port>/vcpkg.spdx.json`) and scan it with
  your usual tool (for example, `osv-scanner` or `grype`). Also run GitHub's dependency
  review. Verify your scanner reads SPDX from vcpkg before relying on it.
- Update the baseline at least monthly, and immediately for a CVE in something you ship.

## Secrets

- Read secrets from the environment at startup (Kamal `env.secret` → container env), validate
  them once, and never log them.
- Never compile secrets into the binary; `strings` finds them.
- Zero sensitive buffers you control with `explicit_bzero`/`memset_s` (plain `memset` before
  free can be optimized away), and keep secret lifetimes short.
