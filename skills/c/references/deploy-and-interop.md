# Packaging, deploy, and interop

## Contents
- Release builds
- Static binaries with musl
- Cross-compiling with zig cc
- Containers: Alpine build, distroless runtime
- Kamal 2 + Cloudflare for services
- Shared libraries and the C ABI
- FFI from other languages
- WebAssembly

## Release builds

```bash
cmake --workflow --preset ci-release        # hardened Release, tests run, -Werror
strip build/release/kvstore-server          # or keep symbols separately (below)
```
- Ship `Release` or `RelWithDebInfo`, never `Debug`. CMake's `Release`
  already adds `-DNDEBUG`, so your `assert`s disappear. That's fine as long
  as they have no side effects (the audit checks for that).
- To keep debugging possible after stripping: on Linux, run
  `objcopy --only-keep-debug app app.debug && objcopy --strip-debug
  --add-gnu-debuglink=app.debug app`. On macOS, use `dsymutil app`. Upload
  the debug files to your crash reporter, not into the image.
- Embed the version from `project(VERSION ...)` with
  `target_compile_definitions(app PRIVATE APP_VERSION="${PROJECT_VERSION}")`
  and print it on `--version`.

## Static binaries with musl

Services ship as **one static binary** on a runtime image with no libc.
- Build on **Alpine** (musl) with `-DKVSTORE_STATIC=ON`. The template links
  `-static-pie` when the linker supports it, which keeps ASLR, and falls
  back to `-static` without PIE otherwise.
- Why musl and not static glibc: glibc's NSS (`getaddrinfo` for hostnames,
  `getpwnam`) needs `dlopen` at runtime, and statically linked glibc warns
  about it and can break. musl is designed for static linking.
- musl caveats:
  - its `malloc` is slower under heavy multithreaded allocation (measure;
    arenas help);
  - its default thread stack is small (128 KiB), so set it with
    `pthread_attr_setstacksize` if threads recurse or use big buffers;
  - its DNS resolver doesn't do everything glibc's does. That's rarely an
    issue in containers.

## Cross-compiling with zig cc

`assets/zig-toolchain.cmake` (it goes in `cmake/`) turns `zig cc` into a
CMake cross toolchain. zig bundles clang plus musl and glibc headers, so a
macOS laptop builds Linux binaries:
```bash
cmake -S . -B build/linux-x64 -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/zig-toolchain.cmake \
      -DZIG_TARGET=x86_64-linux-musl -DCMAKE_BUILD_TYPE=Release -DKVSTORE_STATIC=ON
cmake --build build/linux-x64
file build/linux-x64/kvstore-server   # ELF 64-bit ... static-pie linked
```
Verified with zig 0.16.0 for `x86_64-linux-musl`, `aarch64-linux-musl`
(static-pie), and `x86_64-linux-gnu.2.39` (dynamic, pinned glibc version),
all with `-Werror`. The flag probes pick `-fcf-protection` on x86_64 and
`-mbranch-protection` on aarch64 automatically.

Two gotchas, both handled in the file:
- `CMAKE_C_COMPILER` may be a list (`zig cc -target ...`), but `CMAKE_AR`
  may not. Without the generated `zig ar`/`zig ranlib` wrappers, CMake uses
  the host's Apple `ranlib`. That prints "not a mach-o file" and produces
  archives that lld can't read, so links fail with "undefined symbol".
- You can't run cross-compiled tests on the host. Build for the host
  (presets) to test, and cross-compile only the artifacts.

## Containers: Alpine build, distroless runtime

`assets/Dockerfile`:
1. `FROM alpine:3.24 AS build`: install `build-base cmake samurai
   linux-headers` (Alpine's cmake is 4.2.x; `samurai` provides `ninja`, so
   verify that on your image). Then `cmake --preset release
   -DKVSTORE_STATIC=ON`, build, **run ctest inside the build**, and strip.
2. `FROM gcr.io/distroless/static-debian13:nonroot`: no shell, no libc, no
   package manager, uid 65532. Distroless is Debian 13 based now; its
   README lists only `-debian13` images. `scratch` also works, but
   distroless/static adds CA certificates, `/etc/passwd`, and tzdata for
   free.
3. Use `ENTRYPOINT ["/usr/local/bin/app"]` in exec form, so `SIGTERM`
   reaches your process (there's no shell to swallow it).

There's no shell in the runtime image. Debug with the `:debug-nonroot` tag,
or with `docker cp` plus a local run. The Dockerfile wasn't built during
verification (no Docker here), but the same CMake flags were verified through
zig's musl target.

## Kamal 2 + Cloudflare for services

`assets/deploy.yml` → `config/deploy.yml`:
- `proxy.app_port: 8080`: kamal-proxy defaults to port 80. The health check
  is `GET /up` and must return 200, and `http_handle()` serves it.
- `proxy.ssl: true` for Let's Encrypt. Behind **Cloudflare**, use Full
  (strict) mode with a Cloudflare Origin CA certificate in
  `proxy.ssl.certificate_pem`/`private_key_pem` (required for multiple
  hosts), and set `forward_headers: true` if you log client IPs.
- Config comes in through `env.clear` and `env.secret`; data files through
  read-only `volumes`.
- `SIGTERM` handling must finish within Kamal's stop timeout (see
  `concurrency-and-performance.md`).
- Keep TLS, HTTP/2, compression, and rate limiting in kamal-proxy and
  Cloudflare. A C service should speak minimal HTTP/1.1 on a private port,
  and anything richer belongs in the proxy.

Reference: https://kamal-deploy.org/docs/configuration/proxy/

## Shared libraries and the C ABI

- Build static by default (`add_library(x ...)` honors
  `BUILD_SHARED_LIBS`). Ship a shared library only when third parties link
  against it at runtime.
- Keep hidden visibility on (`C_VISIBILITY_PRESET hidden`) and export the
  public API explicitly: `include(GenerateExportHeader)` and
  `generate_export_header(x)`, then mark prototypes `X_EXPORT`. This keeps
  the symbol table small, speeds up loading, and stops internal functions
  from becoming ABI.
- Set `VERSION` and `SOVERSION` on the target, and bump `SOVERSION` on every
  ABI break.
- ABI stability rules:
  - opaque types only;
  - never change the meaning of an existing enum value, and only append new
    ones;
  - never change a public function's signature (add `x_foo2` instead);
  - no public struct fields without a leading `size` field or a reserved
    area.
- Wrap public headers in `#ifdef __cplusplus extern "C" { #endif` (the
  template does), so C++ can include them.

## FFI from other languages

A C library with opaque handles, status codes, and explicit lengths is
already the ideal FFI surface:
- **Rust:** `bindgen` on the public header, or hand-written `extern "C"`
  blocks. Wrap `create`/`destroy` in a type with `Drop`.
- **Go:** cgo (`#include <kvstore/kvstore.h>`, `C.kvstore_get`). Copy
  borrowed strings with `C.GoString` before the next call that could
  invalidate them.
- **Python:** `ctypes` or `cffi` against the shared library.
- **Zig:** `@cImport` the header directly.

Rules: never let a foreign runtime free memory your library allocated (expose
`x_free` if callers must release buffers), never pass callbacks that can
unwind (Rust panics, C++ exceptions) through C frames, and document thread
safety per function.

## WebAssembly

- **WASI** (a command-line or server-side sandbox):
  `zig cc -target wasm32-wasi -std=c23 -O2 ...`. The reference library and
  its tests compiled and ran under Node's `node:wasi` (verified). But
  **`pthread_create` fails at runtime on single-threaded wasm32-wasi**
  (EAGAIN), even though it links. Keep threaded tests behind a CMake option,
  or behind a `__wasi__` check.
- **Browser:** Emscripten (`emcc`, which provides a CMake toolchain file via
  `emcmake cmake`). Export functions with `-sEXPORTED_FUNCTIONS`, and pass
  buffers through the module heap. Keep the API byte-oriented (pointer +
  length), as the template's API already is.
