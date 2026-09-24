# Packaging, deploy, cross-compilation, and interop

## Contents
- Release binaries: mostly static by default
- Docker: multi-stage onto distroless
- Kamal 2 and Cloudflare
- Cross-compilation
- Distributing a library
- C ABI and FFI
- WebAssembly

## Release binaries: mostly static by default

**Default for Linux services: "mostly static"**, meaning `-static-libstdc++ -static-libgcc`
with glibc linked dynamically. It runs on `gcr.io/distroless/cc-debian13`.
- **Why not fully static with glibc:** `getaddrinfo`, NSS (users, DNS), and `dlopen` load
  shared glibc pieces at runtime, so a `-static` glibc binary breaks DNS resolution or warns
  at link time. For a fully static binary, build against musl (Alpine's toolchain, or
  `zig c++ -target x86_64-linux-musl`), then test DNS and TLS yourself, because musl's
  allocator and DNS resolver behave differently.
- **Match glibc versions:** build on the same Debian release as the runtime image
  (`gcc:16-trixie` → `distroless/cc-debian13`, both trixie). A binary built against a newer
  glibc won't start on an older one.
- Strip release binaries (`strip`, or `-s` at link time) and keep an unstripped copy or a
  separate debug file (`objcopy --only-keep-debug`) for symbolizing crashes.
- On macOS, system libraries (libc++, libSystem) are always dynamic, and that's fine: the
  verified release `wc-server` links only system frameworks.

## Docker: multi-stage onto distroless

`assets/Dockerfile` (written carefully but **not built in verification**; Docker wasn't
available):
1. **Build stage** `gcc:16-trixie`: install ninja, pkg-config, git, curl, zip/unzip/tar (vcpkg
   prerequisites); install CMake 4.4.3 from Kitware's release tarball (Debian ships 3.31);
   clone vcpkg at the pinned `VCPKG_COMMIT` and bootstrap it; then `cmake --preset release &&
   cmake --build --preset release --target acme_wc_server`. A BuildKit cache mount on
   `/root/.cache/vcpkg` keeps vcpkg's binary archives between builds.
2. **Runtime stage** `gcr.io/distroless/cc-debian13:nonroot`: glibc + libgcc, no shell, no
   package manager, non-root user. Copy only the stripped binary.

`.dockerignore` excludes `build/` and `.git/`, so the host's build trees (with host-specific
absolute paths in CMake caches) never reach the image.

For a musl fully static binary, the runtime can be `scratch`, but then you must also copy CA
certificates (`/etc/ssl/certs`) if the binary makes TLS calls.

## Kamal 2 and Cloudflare

`assets/deploy.yml` → `config/deploy.yml`:
- `proxy.app_port: 8080` (kamal-proxy defaults to 80) and `healthcheck.path: /up` (the
  default path). The service answers `GET /up` with `200 ok`.
- **Graceful stop:** Kamal stops the old container with `SIGTERM`; the service's `sigwait`
  thread calls `Server::stop()` so in-flight requests finish (verified locally: exit code 0
  after `SIGTERM`).
- **Cloudflare in front:** proxied DNS record, SSL mode Full (strict), and either
  `proxy.ssl: true` (Let's Encrypt, single host) or an Origin CA certificate
  (`ssl.certificate_pem`/`private_key_pem`) when Cloudflare terminates TLS for several hosts.
  Restrict the origin's firewall to Cloudflare's IP ranges.
- Config comes from `env.clear`/`env.secret`; the binary reads `PORT` once at startup.
- distroless has no shell: `kamal app exec` needs a `:debug` image variant, or ship a
  `--version`/`--check-config` flag in the binary.
- **cpp-httplib's default socket options include `SO_REUSEPORT`** (verified in its source).
  A second instance on the same port starts "successfully" and silently shares traffic. The
  service template replaces the default with `SO_REUSEADDR` only, so a port clash fails fast
  (verified: the second instance exits 1).

## Cross-compilation

- **vcpkg triplets** select the target: `--triplet arm64-linux` or
  `-DVCPKG_TARGET_TRIPLET=arm64-linux`, plus `VCPKG_CHAINLOAD_TOOLCHAIN_FILE` pointing to a
  CMake toolchain file that sets `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR`, and the cross
  compilers. Mark build-time tools `"host": true` in `vcpkg.json` so they're built for the
  build machine.
- **Docker buildx** with `--platform linux/amd64,linux/arm64` is the simplest route for
  services: each platform compiles natively under emulation (slow but correct), and the
  Dockerfile maps `TARGETARCH` to Kitware's CMake tarball name.
- **Zig as a cross C++ compiler** (`zig c++ -target aarch64-linux-gnu.2.36`) can target a
  specific glibc version from any host; useful for release artifacts outside Docker. Verify
  C++23 library support for the libc++ that Zig bundles.
- Never run test binaries at build time in a cross build: `gtest_discover_tests(...
  DISCOVERY_MODE PRE_TEST)` defers that to `ctest`, which you run under emulation or on the
  target.

## Distributing a library

- Ship it as a vcpkg port (overlay port or private registry) or a Conan recipe, with the
  CMake package config the template installs (`find_package(acme CONFIG)`,
  `acme::wordcount`).
- Headers must compile cleanly under consumers' warnings: the template's CI builds with
  `-Werror` and the full warning set.
- Don't leak your build flags: warnings, sanitizers, and hardening sit behind
  `$<BUILD_INTERFACE:…>`.
- ABI: a C++ ABI is stable only for one compiler, standard library, and flag set. Ship
  source or header-only, or put a C ABI in front for binary distribution. Note that libstdc++
  in GCC 16 changed the ABI of several C++20 components (atomic wait, `std::format` args,
  some range adaptors), so don't mix objects compiled as C++20 by GCC 15 and 16.

## C ABI and FFI

For calling from C, Rust, Go, Python, or Swift, expose an `extern "C"` facade:
```cpp
extern "C" {
typedef struct acme_counter acme_counter;                 // opaque handle
acme_counter* acme_counter_new(void);
void acme_counter_free(acme_counter*);                    // NULL-safe
int acme_counter_add(acme_counter*, const char* text, size_t len);  // 0 ok, <0 error code
}
```
- Opaque handles + create/free pairs; the C++ side wraps them in `std::unique_ptr` with a
  deleter.
- **No exceptions across the boundary:** every `extern "C"` function catches everything and
  returns an error code (`noexcept` on the definition makes an escape `std::terminate`
  instead of undefined behavior).
- Only C types in the signatures: pointers + lengths, fixed-width integers, and POD structs
  with a version/size field for evolution. Document who frees every buffer.
- Build it as a separate `SHARED` target with `-fvisibility=hidden`
  (`CXX_VISIBILITY_PRESET hidden`, `VISIBILITY_INLINES_HIDDEN ON`) and an export macro, so only
  the C API is exported.
- Rust: `bindgen` over the C header; Python: `ctypes`/`cffi` or nanobind/pybind11 for a
  C++-native binding (a dependency, justify it).

## WebAssembly

- **Emscripten** (`emcmake cmake --preset …` or its CMake toolchain file) is the mature
  C++-to-WASM toolchain for browsers and Node; **WASI SDK** (Clang targeting
  `wasm32-wasip1`/`wasip2`) for server-side runtimes (Wasmtime, WasmEdge).
- vcpkg has `wasm32-emscripten` community triplets; header-only dependencies are easiest.
- Threads need `SharedArrayBuffer` (cross-origin isolation) in browsers; exceptions need
  `-fwasm-exceptions`. Keep the WASM surface to the C ABI above.
- Verify versions for your toolchain; nothing in this skill's verification built WASM.
