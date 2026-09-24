# Security and hardening

## Contents
- Threat model in one paragraph
- Compiler and linker hardening (OpenSSF), with platform reality
- Input handling
- Memory safety practices
- Secrets
- Processes, files, and privileges
- Dependencies

Primary source: OpenSSF, *Compiler Options Hardening Guide for C and C++*
(revision dated 2026-08-20):
https://best.openssf.org/Compiler-Hardening-Guides/Compiler-Options-Hardening-Guide-for-C-and-C++.html

## Threat model in one paragraph

In C, every byte from outside the process (network, files, argv, env,
another library's callbacks) can become memory corruption, and memory
corruption is code execution. Defense has three layers:
1. **Write code that can't overflow**: bounded APIs, checked arithmetic,
   explicit lengths, opaque types.
2. **Find the bugs that slip through**: sanitizers, fuzzing, and static
   analysis in CI.
3. **Make the survivors hard to exploit**: hardening flags, PIE/RELRO, a
   non-root distroless runtime, and a proxy in front.

Hardening flags are layer 3. They never substitute for 1 and 2.

## Compiler and linker hardening (OpenSSF), with platform reality

Release builds in the template carry these flags. Each one is **probed**, not
assumed. The "Apple clang 21" column is what the probe found on arm64 macOS;
the "zig cc (Linux)" column is x86_64/aarch64 musl through lld.

| Flag | Purpose | Min | Apple clang 21 | zig cc (Linux) |
|---|---|---|---|---|
| `-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3` | Bounds checks in libc calls (compile time plus runtime) | GCC 12, Clang 9 | accepted | accepted, but musl itself has no FORTIFY; Alpine adds it through its `fortify-headers` package (verify for your image) |
| `-fstack-protector-strong` | Stack canaries | GCC 4.9, Clang 6 | ✓ | ✓ |
| `-fstack-clash-protection` | Probes large stack allocations | GCC 8, Clang 11 | **ignored with a warning** (probe fails under -Werror) | ✓ |
| `-fcf-protection=full` | Intel CET (IBT + shadow stack) | GCC 8, Clang 7; **x86_64 only** | **error** on arm64 | ✓ x86_64 / ✗ aarch64 |
| `-mbranch-protection=standard` | PAC + BTI | GCC 9, Clang 8; **AArch64 only** | ✓ | ✗ x86_64 / ✓ aarch64 |
| `-fstrict-flex-arrays=3` | Only `[]` is a flexible array (better FORTIFY and bounds checks) | GCC 13, Clang 16 | ✓ | ✓ |
| `-ftrivial-auto-var-init=zero` | Zero uninitialized locals | GCC 12, Clang 8 | ✓ | ✓ |
| `-fno-delete-null-pointer-checks -fno-strict-overflow -fno-strict-aliasing` | Keep NULL checks; define overflow; no aliasing-based optimization | old | ✓ | ✓ |
| PIE (`-fPIE` + `-pie`) | ASLR for executables | | ✓ (ld64 default) | ✓ (static-pie with `KVSTORE_STATIC`) |
| `-Wl,-z,relro -Wl,-z,now` | Read-only GOT after startup | binutils 2.15 | **ld64 rejects `-z`** | ✓ |
| `-Wl,-z,noexecstack` | Non-executable stack | | ✗ | ✓ |
| `-Wl,-z,nodlopen` | Mark the object as not dlopen-able | | ✗ | **✗ with lld** (GNU ld only) |
| `-fzero-init-padding-bits=all`, `-fhardened` | Zero padding; GCC's one-flag hardening bundle | GCC 15 / GCC 14 | ✗ unknown | ✗ |

The OpenSSF guide also recommends these:
- `-Wl,--as-needed -Wl,--no-copy-dt-needed-entries` for dynamic Linux
  builds (ld64 rejects `--as-needed`);
- `-fzero-call-used-regs=used-gpr` on x86_64/AArch64;
- `-fexceptions` for threaded C.

Add them if you ship dynamic Linux binaries.

Rules that follow from the table:
- **Probe; don't branch on the OS.** `check_c_compiler_flag` under
  `CMAKE_REQUIRED_FLAGS=-Werror`, and `check_linker_flag`, handle every row
  correctly. `if(APPLE)` ladders go stale.
- **`_FORTIFY_SOURCE` needs `-O1` or higher** and conflicts with ASan. The
  template applies it only to optimized, non-sanitizer builds, and prefixes
  it with `-U_FORTIFY_SOURCE` because distro GCC often predefines level 2.
- **`-fno-strict-overflow` silences UBSan's signed-overflow check.** The
  template drops it from sanitizer builds (verified).
- **`-Werror` in development and CI only.** OpenSSF says the same thing:
  distributed build files must not fail on a newer compiler's warnings.
- On GCC ≥ 14 you *can* use `-fhardened` instead of listing flags, but it's
  GCC-only and its contents change between releases. The explicit, probed
  list works identically across GCC and Clang.

## Input handling

- Treat everything external as bytes with a length. Validate at the boundary
  (`key_ok()`: an allowed charset and a max length), convert once, and pass
  validated types inward.
- **Set limits everywhere:**
  - maximum input size: the CLI refuses more than 1 MiB;
  - maximum key and value length: in the header as `KVSTORE_MAX_*`;
  - request size: 8 KiB;
  - socket timeouts: `SO_RCVTIMEO`/`SO_SNDTIMEO` of 5 s, so a slow client
    can't hold a worker forever.
- Reject, don't "fix up", malformed input. Report where it failed.
- Parse numbers with `strtol` + `errno` + end-pointer + range checks.
- Never build shell commands: `system()` and `popen()` are banned. Use
  `posix_spawn()` with an argv array.
- Every parser gets a fuzz target (see `testing-and-fuzzing.md`).

## Memory safety practices

- Use bounded APIs only (see `idioms-and-api-design.md`). The audit enforces
  the banned list.
- Use `ckd_add`/`ckd_mul` (`<stdckdint.h>`) for every size derived from
  input, and `calloc(n, size)` rather than `malloc(n * size)`.
- Write out-params only on success, and zero-initialize structs (`= {}` in
  C23, or `calloc`).
- NULL-safe destroy functions, plus a single `goto out` cleanup path, keep
  error paths leak-free (`-fanalyzer` and ASan confirm it).
- C has no bounds checking. Carry `(ptr, len)` together, prefer
  `sizeof buf` over repeated literals, and use `static_assert` for size
  relationships.
- GCC 16 extends `__attribute__((counted_by(len)))` to pointer members, and
  Clang supports it on flexible array members. It lets FORTIFY and the
  bounds sanitizer check accesses. Consider it for new structs if all your
  compilers support it (verify for your version).

## Secrets

- Don't log secrets, and don't put them in argv (visible in `ps`). Read them
  from the environment or from a file mounted by the orchestrator (Kamal
  `env.secret`).
- Zero secret buffers with a call the optimizer can't remove. C23's
  `memset_explicit` is **not in the macOS SDK** (verified). Use a wrapper:
  `memset_s` on Apple, `explicit_bzero` on glibc, musl, and the BSDs. Plain
  `memset` before `free` is dead-store-eliminated.
- Use `getrandom()` (Linux) or `arc4random_buf()` for keys, tokens, and
  nonces. Never use `rand()`.
- Compare secrets in constant time (loop over all bytes, OR the differences).
  Never use `memcmp` for this.

## Processes, files, and privileges

- Run as a non-root user (the distroless `:nonroot` image is uid 65532) with
  a read-only config mount.
- Open files with `O_CLOEXEC` (or the `"e"` mode flag in glibc `fopen`) in
  programs that spawn children.
- Ignore `SIGPIPE` in servers, and check every `send`/`write` return value.
- Don't `chdir`/`umask` in libraries. That's process-global state.

## Dependencies

Every C dependency is part of your attack surface, and C has no universal
advisory database hookup. Keep the list short and pinned by hash, and scan
the shipped image. Prefer libraries that fuzz themselves (in OSS-Fuzz) and
publish advisories. Update on their advisories, not on a calendar.
