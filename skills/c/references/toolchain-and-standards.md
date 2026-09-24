# Toolchain and standards

Verified against primary sources in September 2026. Check the compiler that CI
actually uses (`cc --version`, `cmake --version`) before relying on a feature.

## Contents
- Current versions
- Which `-std`, and why C23
- C23 features: use, avoid, minimum compilers
- Library-level gaps (the libc, not the compiler)
- Falling back to C17
- C2y: what's coming, and why not to use it yet

## Current versions

| Tool | Version (2026-09) | Notes |
|---|---|---|
| ISO C | **C23** = ISO/IEC 9899:2024, published 2024-10-31 | Working drafts for C2y (the next revision, expected around 2029) continue; N3886 dated 2026-05 |
| GCC | **16.1** (2026-04-30); 15.x still common | GCC 15 changed the C default to `-std=gnu23`. GCC 16 adds `counted_by` on pointer members, `_Maxof`/`_Minof`, more C2y, and a faster `-fanalyzer` |
| LLVM/Clang | **23.1.0** (2026-08-25); 22.1 before it | Default C mode is still **gnu17**. 22 added named loops and `if` declarations (C2y), plus `-fdefer-ts` (experimental defer TS). 23 adds C23 `wN`/`wfN` printf length modifiers and `constexpr` struct member access |
| Apple clang | **21** (Xcode / Command Line Tools) | Its version number doesn't match LLVM's. Default is gnu17. No libFuzzer runtime, no MSan, `ld64` linker |
| CMake | **4.4.3** | 4.0 removed compatibility with `cmake_minimum_required` < 3.5. Presets schema v12 (4.4); use v6 (3.25) for portability |
| Ninja | 1.13 | Default generator in the presets |
| zig (as `zig cc`) | 0.16.0 | Cross-compiler with bundled musl/glibc headers; see `deploy-and-interop.md` |

Sources:
- GCC 15 changes: https://gcc.gnu.org/gcc-15/changes.html
- GCC 16 changes: https://gcc.gnu.org/gcc-16/changes.html
- Clang 22 notes: https://releases.llvm.org/22.1.0/tools/clang/docs/ReleaseNotes.html
- Clang 23 notes: https://releases.llvm.org/23.1.0/tools/clang/docs/ReleaseNotes.html
- WG14 project status: https://www.open-std.org/jtc1/sc22/wg14/www/projects
- Compiler support table: https://en.cppreference.com/w/c/compiler_support/23
- CMake 4.0 release notes: https://cmake.org/cmake/help/latest/release/4.0.html

## Which `-std`, and why C23

Default: **C23, strict** (`C_STANDARD 23`, `C_STANDARD_REQUIRED ON`,
`C_EXTENSIONS OFF`). Why:
- C23 removes whole bug classes by construction. `nullptr` has a real type
  (so `NULL`'s int-vs-pointer ambiguity in varargs disappears),
  `<stdckdint.h>` gives checked arithmetic, `constexpr` gives typed constants
  instead of macros, and prototypes are mandatory: `f()` finally means
  `f(void)`, and K&R definitions are gone.
- Strict mode (`-std=c23`, not `gnu23`) keeps code portable. GNU extensions
  have to be asked for explicitly.
- Set it per target, never through `CMAKE_C_FLAGS`. CMake 4.4 emits
  `-std=c2x` for AppleClang and older GCC and Clang. That's the same mode
  (`__STDC_VERSION__` is `202311L`), just the pre-publication spelling.

**Strict mode hides POSIX on glibc.** With `C_EXTENSIONS OFF`, glibc only
declares ISO C. Code that needs POSIX (`sigwait`, `poll`, `fdopen`,
`clock_gettime`) must define a feature-test macro on that target:
`target_compile_definitions(srv PRIVATE _POSIX_C_SOURCE=200809L)`. Do this in
CMake, not in a `#define` at the top of a file. clang-tidy flags that
`#define` as a reserved identifier, and it's easy to put after an include by
mistake.

## C23 features: use, avoid, minimum compilers

Minimum versions are from the cppreference support table and the release
notes above. "verify" means no primary source was checked for that row.

| Feature | GCC | Clang | House rule |
|---|---|---|---|
| `nullptr`, `nullptr_t` | 13 | 16 | **Use** in implementation files instead of `NULL` |
| `bool`/`true`/`false` as keywords | 13 | 15 | **Use**; drop `<stdbool.h>` in C23-only code |
| `constexpr` objects | 13 | 19 | **Use** for typed constants (`static constexpr size_t MAX = 64;`). Scalars only in practice |
| `[[nodiscard]]` (and the other standard attributes) | 10 | 9 | **Use** `[[nodiscard]]` on every function returning a status or an owned pointer |
| `typeof`, `typeof_unqual` | 13 | 16 | Use in macros only |
| `<stdckdint.h>` (`ckd_add`, `ckd_sub`, `ckd_mul`) | 14 | 18 | **Use** for every size computation from untrusted or unbounded input |
| `#embed` | 15 | 19 | Use for binary blobs (certs, fixtures). Clang's `-MD` tracks the embedded file, so Ninja rebuilds on change |
| `static_assert` without a message, as a keyword | 9 | 9 | Use for layout and ABI assumptions |
| `alignas`/`alignof` as keywords | C23 mode (verify) | C23 mode (verify) | Use (`alignas(max_align_t)` in the arena; verified on Apple clang 21) |
| `unreachable()` (`<stddef.h>`) | verify | verify (present in Apple clang 21) | After an exhaustive `switch` only. It's UB if reached, so never use it for "can't happen" input |
| Digit separators `1'000'000`, `0b` literals | 12 / 11 | 13 / 9 | Fine |
| `auto` type inference | 13 | 18 | **Avoid** outside macros. It hides types in a language where the exact integer type matters |
| Empty initializer `= {}` | 13 | 16 (partial) | Fine for locals |
| Enums with a fixed underlying type | 13 | 20 (partial) | Avoid in public headers until your oldest compiler supports it |
| `_BitInt(N)` | 14 (partial) | 15 | Niche (crypto, FPGA). Avoid in APIs |

**Public headers stay C11-compatible.** Consumers may compile with an older
`-std`, so the header uses `NULL`-free signatures, `(void)` parameter lists,
an `enum { MAX = 64 };` instead of `constexpr`, and attributes through a
macro (`KVSTORE_NODISCARD`, see `assets/kvstore.h`). The template's installed
header was verified to compile under `-std=c11 -Wpedantic -Werror` in a
consumer project.

## Library-level gaps (the libc, not the compiler)

The compiler can support a C23 feature that the C library doesn't have yet.
These were verified on the macOS 27 SDK with Apple clang 21:
- `<stdbit.h>` is **missing**. Use `__builtin_popcount` and friends behind a
  small wrapper.
- `<threads.h>` is **missing**, and so is C11 `thrd_*`. Use pthreads on POSIX
  (see `concurrency-and-performance.md`).
- `memset_explicit` is **missing**. Use `memset_s` (macOS) or
  `explicit_bzero` (glibc, the BSDs) behind one wrapper.
- `<stdckdint.h>` is present (the compiler ships it). So are `unreachable()`
  and `strdup`/`strndup` (standard in C23).

glibc and musl have `<threads.h>`. For `<stdbit.h>` and `memset_explicit`,
check your glibc and musl versions before using them.

## Falling back to C17

Use C17 only when a supported platform's compiler predates the table above.
Examples are RHEL 8/9 system GCC, embedded vendor toolchains, and ubuntu-24.04
runners (GCC 13 has no `<stdckdint.h>` or `#embed`, and Clang 18 has no
`constexpr`). To fall back:
- Set `C_STANDARD 17`.
- Replace `nullptr` with `NULL`, and `constexpr` with `enum` or `#define`.
- Replace `ckd_*` with `__builtin_*_overflow`. That's what `stdckdint.h`
  wraps on GCC and Clang.
- Keep `(void)` everywhere.

Don't write `#if __STDC_VERSION__` ladders through the implementation. Pick
one standard per project.

## C2y: what's coming, and why not to use it yet

GCC 15/16 and Clang 22/23 implement pieces of C2y under `-std=c2y`:
- named loops (`break outer;`);
- `if` declarations (`if (int n = f(); n > 0)`);
- case ranges;
- static assertions in expressions.

The standard isn't expected until around 2029, and the features differ
between compilers. Don't use them in production code. `defer` (a TS, behind
Clang's `-fdefer-ts`) is experimental, so keep using `goto cleanup`.
