# Packaging, deploy, and interop

Primary sources: rustc platform support (https://doc.rust-lang.org/rustc/platform-support.html),
the official Rust images (https://github.com/rust-lang/docker-rust), cargo-chef
(https://github.com/LukeMathWalker/cargo-chef), distroless
(https://github.com/GoogleContainerTools/distroless), Kamal 2 (https://kamal-deploy.org),
the Rustonomicon FFI chapter (https://doc.rust-lang.org/nomicon/ffi.html), and
wasm-bindgen (https://github.com/wasm-bindgen/wasm-bindgen).

**Not verified here:** Docker isn't available on the machine that built this
skill, so `assets/Dockerfile` was written carefully against the image tags and
the rustup setup of the official images, but it hasn't been built. Cross
compilation to Linux wasn't run either. Build both once in CI before relying on
them.

## Contents
- Release artifacts
- glibc vs musl
- Cross-compilation
- Docker: cargo-chef + distroless
- Kamal 2 and Cloudflare
- CLI distribution
- FFI and the C ABI
- WebAssembly

## Release artifacts

- `cargo build --release --locked -p <bin>`; the binary is
  `target/release/<bin>`. Strip symbols (`strip = "symbols"` in the release
  profile) and keep a separate profiling build for debugging.
- Embed a version: `env!("CARGO_PKG_VERSION")` (clap's `#[command(version)]`
  does it for you). Add a git SHA with a `build.rs` only if you need it.
- `cargo auditable build` (cargo-auditable) embeds the dependency list in the
  binary so scanners can audit shipped artifacts. Worth it for distributed
  CLIs.

## glibc vs musl

| | glibc (`x86_64-unknown-linux-gnu`) | musl (`x86_64-unknown-linux-musl`) |
|---|---|---|
| Linking | Dynamic libc | Fully static by default (Tier 2 targets) |
| Runtime image | `gcr.io/distroless/cc-debian13:nonroot` | `gcr.io/distroless/static-debian13:nonroot` or `scratch` |
| Allocator | Fast | Slow under multi-thread contention: add mimalloc |
| DNS/NSS, locale | Full | Simplified |
| Default for | **Services** | **Distributed CLIs** (one file that runs anywhere) |

Services default to glibc on distroless/cc: there are no allocator surprises,
and the image is still small (about 25 MB plus the binary). A rustls-only
dependency graph (no OpenSSL) keeps both options open.

Never copy a glibc binary into an Alpine image: it fails at start with a
confusing "not found" error, because the glibc loader is missing.

## Cross-compilation

- Add the target: `rustup target add x86_64-unknown-linux-musl` (or
  `aarch64-unknown-linux-gnu`, and so on).
- Pure-Rust crates with rustls cross-compile with just a linker. The easiest
  linker is Zig through **cargo-zigbuild** (0.23):
  `cargo zigbuild --release --target x86_64-unknown-linux-musl`. It can also pin
  a glibc floor: `--target x86_64-unknown-linux-gnu.2.28`.
- C dependencies (`*-sys` crates) need a C cross toolchain. Avoid them, or
  build inside a container of the target platform.
- Build Docker images on a runner of the target architecture. Emulated (QEMU)
  Rust builds are 5-20x slower, so the Kamal config pins `builder.arch: amd64`
  (use a remote builder or an arm64 runner for ARM hosts).
- macOS universal binaries: build both Apple targets and join them with
  `lipo -create`.

## Docker: cargo-chef + distroless

`assets/Dockerfile`:
1. `chef` stage: `lukemathwalker/cargo-chef:0.1.78-rust-1.98.1-slim-trixie`,
   the same Rust version as `rust-toolchain.toml`.
2. `planner`: `cargo chef prepare` writes `recipe.json` (the dependency graph).
3. `builder`: `cargo chef cook --release --locked` builds only dependencies.
   This layer is cached until `Cargo.toml`/`Cargo.lock` change. Then it copies
   the sources and runs `cargo build --release --locked -p acme-api` with
   `SQLX_OFFLINE=true` (the committed `.sqlx/` data, so no database is needed).
4. Runtime: `gcr.io/distroless/cc-debian13:nonroot` (libc, libgcc, CA
   certificates, and tzdata; no shell; runs as a non-root user). Copy the
   binary, set `ENTRYPOINT`.

Gotchas:
- The official Rust images install with rustup's **minimal** profile (no
  rustfmt or clippy). A `rust-toolchain.toml` listing components makes rustup
  try to download them during `docker build`. The Dockerfile sets
  `ENV RUSTUP_TOOLCHAIN=1.98.1` to use the image's toolchain as-is; keep it in
  sync with the pin.
- `.dockerignore` must exclude `target/` (gigabytes of build context) and
  `.git/`.
- There's no shell or curl in distroless, so a Docker `HEALTHCHECK` can't
  curl `/up`. Kamal's proxy does the HTTP health check from outside.
- Use `ENTRYPOINT ["/usr/local/bin/app"]` in exec form, so the binary is PID 1
  and receives SIGTERM directly.

## Kamal 2 and Cloudflare

`assets/deploy.yml` (Kamal 2):
- `proxy.app_port: 3000` (kamal-proxy defaults to 80) and
  `proxy.healthcheck.path: /up`. The new container gets traffic only after
  `/up` returns 200.
- Secrets (`DATABASE_URL`) in `env.secret`, sourced from `.kamal/secrets`.
- Postgres 18 as an accessory: mount `/var/lib/postgresql`. The postgres:18
  image moved `PGDATA` to `/var/lib/postgresql/18/docker` and the volume to
  `/var/lib/postgresql`, so an old `.../data` mount silently loses data on
  container replacement.
- Migrations run at boot (`sqlx::migrate!`, under an advisory lock). Keep them
  backward compatible, because old and new containers overlap during a
  rollout.

Cloudflare in front:
- DNS proxied (orange cloud). SSL mode **Full (strict)**, with a Cloudflare
  **Origin CA certificate** on kamal-proxy (`proxy.ssl.certificate_pem` and
  `private_key_pem` as secrets) instead of Let's Encrypt. Origin CA
  certificates are long-lived and don't depend on ACME challenges passing
  through Cloudflare, and they're also the way to run several hosts behind
  one name.
- The client IP arrives in `CF-Connecting-IP`. Trust it only if the origin
  firewall accepts traffic from Cloudflare's IP ranges alone.
- Put caching, compression, WAF, and rate limiting at Cloudflare; the app stays
  simple.

## CLI distribution

- Build static musl binaries for Linux (x86_64 and aarch64) and native
  binaries for macOS (both architectures) and Windows (MSVC) in a CI matrix on
  release tags, and attach them to a GitHub release with checksums.
- `cargo install --locked <crate>` for Rust users. `cargo-dist` automates
  installers and release CI (verify its current version before adopting it).
- Set `panic = "abort"` for CLIs if binary size matters.

## FFI and the C ABI

Exposing Rust to C (a `cdylib` or `staticlib`):
```toml
[lib]
crate-type = ["cdylib", "staticlib"]
```
```rust
/// # Safety
/// `data` must point to `len` readable bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn acme_checksum(data: *const u8, len: usize) -> u32 {
    // SAFETY: the caller guarantees `data` is valid for `len` bytes (see # Safety).
    let bytes = unsafe { std::slice::from_raw_parts(data, len) };
    checksum(bytes)
}
```
- Edition 2024 syntax: `#[unsafe(no_mangle)]`, `unsafe extern "C"` blocks
  for imports, and explicit `unsafe {}` inside `unsafe fn`.
- Only FFI-safe types cross the boundary: `#[repr(C)]` structs, integers,
  raw pointers, and `Option<&T>`/`Option<NonNull<T>>`. Never `String`, `Vec`,
  `&str`, or trait objects.
- Panics must not unwind into C: use `extern "C"` (a panic across it aborts),
  or catch with `std::panic::catch_unwind` and return an error code.
- Ownership crosses explicitly: whoever allocates frees. Export
  `acme_free_x(ptr)` that rebuilds the `Box` with `Box::from_raw`.
- Generate the C header with **cbindgen** (0.29). Consume C libraries with
  **bindgen** (0.73) in a `*-sys` crate, compiling C sources with the **cc**
  crate (1.4). Wrap the raw bindings in a safe crate: raw `-sys`, safe
  wrapper on top.
- Keep FFI in its own crate, the one place `unsafe_code` isn't `forbid`, and
  run its tests under Miri where possible plus sanitizers (see
  `testing.md`).

## WebAssembly

- **Browser / JS:** target `wasm32-unknown-unknown` with **wasm-bindgen**
  (0.2.128; the project now lives in the `wasm-bindgen` GitHub org) and
  **wasm-pack** (0.15) to build npm-ready packages. Keep the wasm crate thin,
  wrapping the pure `core` crate, which should already avoid threads, the file
  system, and system time.
- **Server-side / WASI:** `wasm32-wasip2` (Tier 2) for components run by
  wasmtime and similar runtimes. `wasm32-wasip1` is the older preview 1
  target (the name `wasm32-wasi` was removed).
- Size: `opt-level = "z"`, `lto = true`, `codegen-units = 1`, and
  `panic = "abort"` in a dedicated profile, then `wasm-opt -Oz` (binaryen).
- `getrandom` and time need target-specific features on
  `wasm32-unknown-unknown` (for example the JS backend). Check each
  dependency's wasm support before promising a port.
