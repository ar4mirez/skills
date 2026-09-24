# Toolchain and versions

Verified on 2026-09-24 against go.dev release notes, the module proxy, and
a local Go 1.27.1 toolchain.

## Contents
- Versions to target
- Release policy
- What's new: Go 1.27, 1.26, and 1.25
- go.mod: the go, toolchain, tool, and ignore lines
- Everyday commands
- Sources

## Versions to target

| Thing | Version (Sept 2026) | Notes |
|---|---|---|
| Go | **1.27.1** (1.27 shipped Aug 2026) | 1.26 still gets security fixes; 1.25 and older don't |
| golangci-lint | **v2.14.0** | Install a binary or use the CI action; don't `go install` it |
| staticcheck | 2026.2.1 (module v0.8.1) | Already inside golangci-lint's `standard` set |
| govulncheck | golang.org/x/vuln v1.8.0 | Pin it with the go.mod `tool` directive |
| pgx | v5.11.0 | Use `pgxpool` for services |
| sqlc | v1.31.1 | Needs cgo to build; run it with `go run ...@v1.31.1` |
| goose | v3.28.0 | Used as a library: `goose.NewProvider` + `embed.FS` |
| golang.org/x/sync | v0.23.0 | `errgroup` |
| testcontainers-go | v0.44.0 | Optional; see `testing.md` |
| Kamal | 2.x | `proxy.app_port`, `/up` health path |
| distroless | `static-debian13:nonroot` | Debian 13 is the current base |

Look up a module's latest version without guessing:
`curl -s https://proxy.golang.org/<module>/@latest`, or `go list -m -versions <module>`.

## Release policy

A major Go release ships every six months (February and August). Each
release gets security and bug fixes until two newer majors exist, so only the
two newest releases are supported. A `go` line older than the previous release
means running unsupported code. Upgrade by raising the `go` line, then
running `go fix ./...` so the modernizers rewrite old idioms.

## What's new

**Go 1.27 (August 2026)**
- **Generic methods:** methods may declare their own type parameters, but
  interface methods still can't.
- Struct literal keys may be field selectors; function type inference now
  works in every assignment context.
- **`encoding/json/v2` and `encoding/json/jsontext` are GA.** v1 is now
  implemented on top of v2. Opt out with `GOEXPERIMENT=nojsonv2`.
- New packages: `uuid` (`uuid.New`, `NewV4`, `NewV7`, `Parse`),
  `crypto/mldsa` (post-quantum signatures), and experimental `simd`
  (`GOEXPERIMENT=simd`).
- `net/http/httptest.NewTestServer(t, h)` runs a test server on an
  in-memory network. `testing/synctest.Sleep` was added.
- The `goroutineleak` profile is GA: `runtime/pprof` and
  `/debug/pprof/goroutineleak`.
- Small allocations are about 30% cheaper (size-specialized malloc).
- `go test` now runs the `stdversion` vet check. `go doc` accepts
  `pkg@version`. `go mod tidy` enforces a two-block `require` layout.
  `go fix` gains `atomictypes`, `embedlit`, `slicesbackward`, and
  `unsafefuncs`, and renames `waitgroup` to `waitgroupgo`.
- `strings.CutLast` and `bytes.CutLast`; `url.URL.Clone`; `math/big`
  `Int.Divide` with rounding modes; `database/sql.ConvertAssign`.
- macOS 13+ is required.

**Go 1.26 (February 2026)**
- `new(expr)`: `p := new(42)` and `Age: new(yearsSince(born))`.
- `errors.AsType[E](err) (E, bool)`: the generic, type-safe `errors.As`.
- **`go fix` was rebuilt around modernizers** (`go fix -diff ./...` exits
  non-zero when anything would change, so it works as a CI gate).
  `//go:fix inline` directives let library authors ship API migrations.
- The Green Tea GC is on by default (10-40% less GC overhead).
- `slog.NewMultiHandler`; `T.ArtifactDir()` with `-artifacts`;
  `signal.NotifyContext` cancels with a cause naming the signal.
- `b.Loop()` no longer prevents inlining. `crypto` APIs ignore
  caller-supplied randomness (use `testing/cryptotest.SetGlobalRandom` in
  tests). `cmd/doc` was removed; use `go doc`.
- `ServeMux` trailing-slash redirects use 307, not 301.

**Go 1.25 (August 2025)**
- Container-aware `GOMAXPROCS`: it respects cgroup CPU limits and updates
  when they change.
- `testing/synctest` graduated. `sync.WaitGroup.Go(f)` was added.
- `http.CrossOriginProtection`: CSRF defense from `Sec-Fetch-Site`/`Origin`,
  with no tokens.
- `go vet` gained `waitgroup` (misplaced `wg.Add`) and `hostport`
  (`Sprintf("%s:%d")` addresses).
- `runtime/trace.FlightRecorder`; the `ignore` directive in go.mod;
  `go doc -http`; DWARF 5.

Earlier features you should use by default: per-iteration loop variables,
`range` over ints, and ServeMux patterns (1.22); iterators, `iter`, and
range-over-func (1.23); the `tool` directive, `os.Root`, `b.Loop`,
`t.Context`, `crypto/rand.Text`, and `omitzero` (1.24).

## go.mod

```
module github.com/acme/links

go 1.27.0                 // the language version and minimum toolchain

require (...)

tool golang.org/x/vuln/cmd/govulncheck
```

- **`go` line:** write it as `go 1.27.0`. It gates language features and
  stdlib APIs: a generic method or a json/v2 call under `go 1.26.0` fails
  `go vet`/`go test`. Check the line after `go mod init`, since the default
  depends on your toolchain.
- **`toolchain` line:** add one only to force a newer toolchain than the `go`
  line. With `GOTOOLCHAIN=auto` (the default), an older local Go downloads the
  required toolchain automatically. CI's `setup-go` reads `go-version-file:
  go.mod`.
- **`tool` directive (1.24+):** `go get -tool golang.org/x/vuln/cmd/govulncheck@v1.8.0`
  records it, and `go tool govulncheck ./...` runs it, pinned by go.sum. Tool
  dependencies share the module graph, so keep this to small tools. Run heavy
  ones as `go run pkg@version` (sqlc, via `//go:generate`) or with their
  official installer (golangci-lint).
- **`ignore` (1.25+):** `ignore ./node_modules` keeps `./...` out of
  non-Go trees.
- **`replace`:** never commit `=> ../local` paths. Use `go.work` locally
  (see `layout.md`).

## Everyday commands

```bash
go mod tidy                     # add missing and drop unused requirements
go mod tidy -diff               # CI: fail if go.mod/go.sum aren't tidy
go get example.com/mod@v1.2.3   # add or upgrade one dependency
go get -u=patch ./...           # patch-level upgrades only
go list -m -u all               # show available upgrades
go mod why -m example.com/mod   # why a dependency is here
go doc -http                    # local docs server (1.25+)
go doc pkg@v1.2.3 Symbol        # docs for a specific version (1.27+)
go fix ./...                    # apply modernizers after raising the go line
go version -m ./bin/app         # embedded module and build info of a binary
```

## Sources
- https://go.dev/doc/go1.27, https://go.dev/doc/go1.26, https://go.dev/doc/go1.25
- https://go.dev/doc/devel/release (release policy)
- https://go.dev/doc/toolchain (GOTOOLCHAIN, go and toolchain lines)
- https://go.dev/ref/mod (go.mod reference, tool and ignore directives)
- https://golangci-lint.run/docs/welcome/install/local/ (install guidance)
