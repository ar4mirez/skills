# Packaging and deploy

The house style for services is a static binary in a minimal image, deployed with
**Docker + Kamal 2**, with **Cloudflare** in front. The binaries and cross builds below
were produced with 0.16.0. The Dockerfile follows the same commands, but it wasn't built
here (no Docker on the verification host), so build it once before relying on it.

## Contents
- Release builds and cross-compilation
- Static binaries: musl vs glibc
- Container image
- Kamal 2
- Cloudflare in front
- Runtime behavior (signals, logs, health)
- CLI releases

## Release builds and cross-compilation

```bash
zig build -Dtarget=x86_64-linux-musl  -Doptimize=ReleaseSafe -Dstrip=true
zig build -Dtarget=aarch64-linux-musl -Doptimize=ReleaseSafe -Dstrip=true
zig build -Dtarget=x86_64-macos       -Doptimize=ReleaseSafe
zig build -Dtarget=x86_64-windows     -Doptimize=ReleaseSafe
```

Every target is available from every host, with no toolchain or sysroot to install.
Output lands in `zig-out/bin/`. Build one target per invocation (or `--prefix` per target)
so the artifacts don't overwrite each other.

## Static binaries: musl vs glibc

- **A pure-Zig program that doesn't link libc is static on Linux no matter the ABI
  suffix.** Verified: `tallyd` for `x86_64-linux-gnu` and for `x86_64-linux-musl` both came
  out "statically linked". The suffix matters once something sets `link_libc` (C sources,
  `std.c`, `c_allocator`).
- With libc: `-linux-musl` gives a static binary (runs on scratch or distroless/static).
  `-linux-gnu` gives a dynamic binary that needs glibc at runtime (distroless/base or
  Debian). Pick the glibc floor explicitly: `-Dtarget=x86_64-linux-gnu.2.31`.
- Default to **musl + ReleaseSafe + strip** for services: a ~300 KB–few MB self-contained
  file.

## Container image

`assets/Dockerfile`:
1. The build stage runs on `$BUILDPLATFORM` (`debian:trixie-slim`). It downloads the
   official Zig tarball and **checks its SHA-256** from `ziglang.org/download/index.json`,
   then cross-compiles for `$TARGETARCH`. Multi-arch images need no QEMU, because Zig
   cross-compiles.
2. `COPY build.zig build.zig.zon` + `zig build --fetch` before copying sources, so the
   dependency download is a cached layer.
3. `zig build -Dtarget=<arch>-linux-musl -Doptimize=ReleaseSafe -Dstrip=true`.
4. The runtime is `gcr.io/distroless/static-debian13:nonroot`: no shell, a non-root
   user, and CA certificates plus tzdata (needed for outbound TLS). `FROM scratch` is
   fine for a binary that makes no TLS calls; add `USER 65532:65532`.

The image holds one binary and nothing else. Don't install a shell "for debugging". Run
the binary locally or use `kamal app exec` against a debug image when needed.

## Kamal 2

`assets/deploy.yml` → `config/deploy.yml`:
- `proxy.app_port: 3000` (kamal-proxy defaults to 80) and `proxy.healthcheck.path: /up`
  (the service answers `200 ok`; `/up` is also kamal-proxy's default path).
- `proxy.buffering.requests: true` with `max_request_body` matching the service limit.
  kamal-proxy then absorbs slow or oversized clients, which matters because
  `std.http.Server` has no per-connection read timeouts.
- `builder.arch: amd64` (or `[amd64, arm64]`). The Dockerfile cross-compiles, so both are
  cheap.
- Config through `env.clear` (PORT) and secrets through `env.secret`. The service reads
  them once in `main` from `init.environ_map`.
- Deploy: `kamal setup` once, then `kamal deploy`. Roll back with `kamal rollback <version>`.

## Cloudflare in front

- DNS is proxied (orange cloud), with SSL/TLS mode **Full (strict)**. On the origin, use a
  Cloudflare **Origin CA certificate** in `proxy.ssl.certificate_pem`/`private_key_pem`,
  or Let's Encrypt (`ssl: true`) for a single host.
- Firewall the origin so it accepts 80/443 only from Cloudflare ranges. The service itself
  listens only on the Docker network (port 3000, not published).
- Get the client IP from `CF-Connecting-IP` (or `X-Forwarded-For` with
  `forward_headers: true`), and only trust it behind the proxy.

## Runtime behavior (signals, logs, health)

- **Logs:** `std.log` writes to stderr, and Docker and Kamal collect them. Keep one event
  per line. For JSON logs, override `std_options.logFn` in the root file. Default log
  level is `.info` in release builds.
- **Shutdown:** on SIGTERM the process exits (default disposition). For a stateless HTTP
  service behind kamal-proxy, that's acceptable: the proxy drains the old container before
  stopping it. For graceful in-flight completion, handle the signal and cancel the accept
  loop (`listener` + `Io.Group.cancel`). Signal handling goes through `std.posix`; verify
  the exact API for your version.
- **Health:** `/up` returns 200 without touching dependencies. Keep deep checks
  (database) on a separate route, so a flaky dependency doesn't fail deploys.
- **Crashes:** ReleaseSafe panics print a stack trace to stderr (symbolized if not
  stripped). Keep an unstripped copy of each release binary, or build without
  `-Dstrip`, if you want readable traces from production.

## CLI releases

- Build a matrix of `{x86_64,aarch64}-{linux-musl,macos}` and `x86_64-windows` in
  ReleaseSafe with `-Dstrip=true`, archive each (`tar.gz`, `zip` for Windows), and
  publish checksums (`sha256sum`) next to them.
- Embed the version with a build option (`b.option([]const u8, "version", ...)` passed through `b.addOptions()`,
  or `exe.version`) rather than a hand-edited constant.
- macOS binaries may need signing and notarization for distribution outside Homebrew.
  That's outside Zig; do it in CI with Apple tooling.
