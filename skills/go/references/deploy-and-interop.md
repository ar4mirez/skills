# Deploy and interop

One static binary per service, a distroless image, Kamal 2 on a VM, and
Cloudflare in front. The build commands below were run on Go 1.27.1. The
Dockerfile and Kamal files follow the official docs but weren't executed
during verification (no Docker daemon was available).

## Contents
- Release builds
- Cross-compilation
- Versioning the binary
- Dockerfile
- Kamal 2
- Migrations during deploys
- Cloudflare in front
- Runtime settings
- Interop: cgo and the C ABI
- Interop: WebAssembly

## Release builds

```bash
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$(git rev-parse --short HEAD)" -o dist/links ./cmd/links
```

- `CGO_ENABLED=0`: a pure-Go, statically linked binary (`file` reports
  "statically linked"). `net` and `os/user` fall back to their pure-Go
  implementations. Needed for scratch and distroless/static.
- `-trimpath`: strips local paths, which makes builds reproducible and hides
  your filesystem layout.
- `-ldflags="-s -w"`: drops the symbol table and DWARF (the template's
  binary is 12 MB for linux/amd64). Keep an unstripped build if you use
  a debugger on production cores.
- `go version -m dist/links` shows the embedded module versions and build
  settings. govulncheck can scan it (`-mode=binary`).

## Cross-compilation

`GOOS`/`GOARCH` are all you need for pure-Go code: no toolchain per target.

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -o dist/links-linux-arm64 ./cmd/links
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o dist/links.exe ./cmd/links
go tool dist list        # every supported GOOS/GOARCH pair
```

`GOAMD64=v3` (or `GOARM64=v8.x`) targets newer CPU features when you control
the hardware. In Docker, build on `$BUILDPLATFORM` and set
`GOOS=$TARGETOS GOARCH=$TARGETARCH`, which is native-speed with no QEMU.
Go 1.27 requires macOS 13+ on Darwin.

## Versioning the binary

`var version = "dev"` in `main`, set with `-X main.version=...`. Builds from
a git checkout also embed VCS info (`debug.ReadBuildInfo()`, `vcs.revision`),
but Docker contexts usually exclude `.git`, so pass the version as a build
argument. The Kamal template does this with ERB:
`VERSION: <%= `git rev-parse --short HEAD`.strip %>`.

## Dockerfile

`assets/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.27-trixie AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
ARG TARGETOS TARGETARCH VERSION=dev
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/links ./cmd/links

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/links /links
EXPOSE 8080
CMD ["/links", "serve"]
```

- `distroless/static-debian13:nonroot`: CA certificates, tzdata,
  `/etc/passwd`, and UID 65532. There's no shell and no package manager.
  Pin the `-debian13` suffix, and pin digests in production.
- `scratch` works too, but you must copy CA certs (and tzdata, or
  `import _ "time/tzdata"`) yourself.
- Use `CMD` with an absolute path and no `ENTRYPOINT`, so `kamal app exec
  "/links migrate"` runs another subcommand from the same image.
- Copy `go.mod`/`go.sum` before the source for layer caching.
  `.dockerignore` excludes `.git`, `dist`, and local artifacts.
- Never ship the `golang` image as the runtime (hundreds of MB, compiler
  and shell included).

## Kamal 2

`assets/deploy.yml` → `config/deploy.yml`. The essentials:

```yaml
service: links
image: <github_user>/links
builder:
  arch: amd64
  args:
    VERSION: <%= `git rev-parse --short HEAD`.strip %>
servers:
  web:
    hosts: [<server_ip>]
proxy:
  host: <links.example.com>
  app_port: 8080          # kamal-proxy defaults to 80
  healthcheck:
    path: /up             # kamal-proxy's default path; 200 only when the DB answers
    interval: 3
  ssl: true
env:
  clear: { PORT: 8080, LOG_LEVEL: info }
  secret: [DATABASE_URL]
```

- kamal-proxy polls `/up` during a deploy and switches traffic only when it
  returns 200 (default deploy timeout 30s), which gives you zero-downtime
  cutover.
- **Shutdown timing:** kamal-proxy drains in-flight requests
  (`drain_timeout`, default 30s) and then stops the old container. Docker's
  stop timeout for proxied roles is 10s (`stop_timeout` to change it), so the
  app's own shutdown drain must be shorter (the template uses 8s).
- Secrets go in `.kamal/secrets` (reading from env or a password manager),
  never in `deploy.yml`.
- A worker process from the same image is another role with a different
  `cmd` (for example `cmd: /links worker`). Proxy it only if it serves HTTP.
- Postgres as a Kamal accessory (`postgres:18`) is fine for small setups.
  Managed Postgres is simpler once backups and failover matter.

## Migrations during deploys

`assets/kamal-pre-deploy` → `.kamal/hooks/pre-deploy` (executable):

```sh
kamal app exec --primary --roles=web --version="$KAMAL_VERSION" "/links migrate"
```

Kamal builds and pushes the image, then runs `pre-deploy` (a non-zero exit
aborts the deploy), then boots the new containers. So migrations run from
the new image, once, before it takes traffic, while the old version still
serves. That's why migrations must be backward compatible (expand, then
contract). `--version` is a global Kamal option; check `kamal app exec
--help` on your version.

## Cloudflare in front

- DNS record **proxied** (orange cloud); SSL mode **Full (strict)**.
- Origin certificate: a Cloudflare **Origin CA** cert installed via
  `proxy.ssl.certificate_pem`/`private_key_pem`, since Let's Encrypt HTTP-01
  challenges don't pass through a proxied record reliably. Lock the
  firewall to Cloudflare's IP ranges.
- Client IP: Cloudflare sends `CF-Connecting-IP`. With `ssl: true`, set
  `proxy.forward_headers: true` so kamal-proxy keeps `X-Forwarded-For`, and
  trust these headers only because the origin accepts traffic from
  Cloudflare alone.
- Cache static assets at the edge; send `Cache-Control: no-store` on
  authenticated API responses.

## Runtime settings

- `GOMEMLIMIT` at ~90% of the container memory limit.
- `GOMAXPROCS` is automatic from cgroups (1.25+).
- `GODEBUG` settings default from the `go` line of the main module. Pin
  behavior changes with `//go:debug` lines or a `godebug` block in go.mod
  when an upgrade changes defaults you rely on.
- Log to stdout as JSON; Kamal and Docker collect it.

## Interop: cgo and the C ABI

- Calling C from Go: `import "C"` with a preamble. cgo needs a C toolchain
  on every build machine, disables static builds, makes cross-compilation
  need a cross C compiler, and costs roughly tens of ns per call (1.26 cut
  that about 30%). Prefer a pure-Go library, or run the C tool as a
  subprocess.
- Exposing Go to C: `//export Name` on functions in `package main`, then
  `go build -buildmode=c-archive` (a `.a` plus a generated `.h`) or
  `-buildmode=c-shared` (`.so`/`.dylib`). Verified: a C program linked with
  the `c-archive` output and called `Add(2, 3)`. On macOS, link the
  `CoreFoundation` and `Security` frameworks.
- Rules: C must not keep Go pointers after the call returns (see the cgo
  pointer-passing rules); pass `C.CString` copies and free them; use
  `runtime.Pinner` if C must hold a pointer temporarily.

## Interop: WebAssembly

- **WASI:** `GOOS=wasip1 GOARCH=wasm go build -o app.wasm ./cmd/app` runs
  under wasmtime or wazero.
- **Exports:** `//go:wasmexport add` on a function (1.24+), built with
  `-buildmode=c-shared` for a reactor module that a host calls repeatedly.
  Verified to build a 1.9 MB module. `//go:wasmimport` imports host functions.
- **Browser:** `GOOS=js GOARCH=wasm` with `syscall/js` and the
  `wasm_exec.js` shim from `$(go env GOROOT)/lib/wasm/`. Binaries are
  multi-MB; TinyGo produces much smaller ones but supports a subset of Go.

Sources: https://go.dev/doc/install/source#environment, https://pkg.go.dev/cmd/cgo,
https://go.dev/wiki/WebAssembly, https://github.com/GoogleContainerTools/distroless,
https://kamal-deploy.org/docs/configuration/proxy/, https://kamal-deploy.org/docs/hooks/overview/,
https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/
