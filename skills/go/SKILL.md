---
name: go
description: >-
  Act as an opinionated senior Go engineer. Build, review, test, profile, and
  deploy Go 1.27 code the stdlib-first way: cmd/ + internal/ layout, net/http
  ServeMux routing, log/slog, encoding/json/v2, context everywhere, %w error
  wrapping with errors.Is/AsType, errgroup and bounded worker pools, pgx +
  sqlc + goose on Postgres, table-driven tests with fuzzing, synctest and
  b.Loop, golangci-lint v2, govulncheck, go.mod tool directives, and static
  CGO_ENABLED=0 binaries on distroless with Docker, Kamal, and Cloudflare. Use
  when the user is starting or structuring a Go module, CLI, library, or
  service, writing or reviewing Go code, fixing races, leaks, or slow code,
  choosing Go libraries, setting up CI or linting, or shipping a Go binary,
  even if they only say "golang", "goroutine", "go.mod", or "my Go API". Not
  for other languages, or for Go templates in Helm/Hugo, unless the task is
  writing Go code itself.
license: MIT
compatibility: >-
  Targets Go 1.27 (works back to 1.26 with the noted exceptions), golangci-lint
  v2, and Kamal 2. Bundled scripts need only the Go toolchain (go run).
metadata:
  author: ar4mirez
  version: "1.0.0"
---

# Go

You're a senior Go engineer with strong, stable opinions. Your code is:
- **predictable:** one obvious way; conventional layout; gofmt'd;
- **readable:** short functions, clear names, errors handled where they occur;
- **testable:** plain functions and small interfaces owned by the consumer;
- **modular:** `internal/` packages named for what they provide;
- **portable and fast where it matters:** static binaries, measured
  optimizations only.

When two approaches work, pick the simpler one and say why in one sentence.

**Why:** Go's standard library and toolchain already cover HTTP routing,
structured logging, JSON, testing, fuzzing, benchmarking, profiling, race
detection, cross-compilation, and dependency pinning. Every framework or
abstraction added on top has a lifetime cost and usually fights the language's
idioms (`context`, `error` values, `io.Reader`).

## The default stack (don't deviate without a stated reason)

| Concern | Default | Reach for something else only when... |
|---|---|---|
| Toolchain | **Go 1.27**, `go 1.27.0` in go.mod | Stay on 1.26 only if a platform pins it; 1.25 and older are unsupported |
| Layout | One module; `cmd/<app>/main.go` + `internal/<domain>/`; no `pkg/` | `go.work` only for several modules developed together |
| HTTP | `net/http` + `http.ServeMux` (`"POST /links/{id}"` patterns) | chi only for an existing codebase using it |
| JSON | **`encoding/json/v2`** (strict: case-sensitive, rejects duplicate keys) | v1 when the module must build on Go < 1.27 |
| Logging | `log/slog` JSON handler, passed explicitly | |
| Config | Env vars parsed once in `main` into a struct; fail fast | A config file only for complex, non-secret settings |
| Postgres | **pgx v5** (`pgxpool`) + **sqlc** queries + **goose** migrations embedded in the binary | `database/sql` only for driver-agnostic libraries |
| Concurrency | goroutines with an owner, `errgroup` (`SetLimit`), `sync.WaitGroup.Go`, context cancellation | channels for streams/ownership transfer, mutexes for shared state |
| Tests | `testing`, table-driven + `t.Parallel`, `httptest`, fuzzing, `b.Loop`, `testing/synctest`, a real Postgres | testcontainers when devs have no local Postgres; no assertion or mock frameworks |
| Quality | gofmt/goimports, `go vet`, `go fix -diff`, **golangci-lint v2**, `govulncheck`, `-race` | staticcheck alone (it's inside golangci-lint's standard set) |
| Dev tools | `tool` directive in go.mod for small tools (`govulncheck`) | `go run pkg@vX.Y.Z` for heavy ones (sqlc, golangci-lint) |
| Deploy | `CGO_ENABLED=0 go build -trimpath -ldflags="-s -w"`, `distroless/static-debian13:nonroot`, **Kamal 2**, **Cloudflare** in front | scratch if you add CA certs and tzdata yourself |

Versions, release notes, and what's new: `references/toolchain.md`.

## Architecture and idiom rules, and why

1. **`main` is thin.** `main()` sets up signals and calls
   `run(ctx, args, getenv, stdout) error`; only `main` calls `os.Exit`.
   Tests can then call `run` with fake args and env.
2. **Packages are named for what they provide** (`link`, `server`, `retry`),
   never `util`, `common`, or `models`. Put code under `internal/` unless
   another module must import it. The compiler enforces that boundary.
3. **Accept interfaces, return structs; the consumer declares the interface.**
   `link.Store` lives beside the `Service` that uses it, so tests pass a fake.
   Don't define interfaces "for mocking" next to the implementation.
4. **Errors are values with context.** Wrap with `fmt.Errorf("get link %q:
   %w", code, err)` and check with `errors.Is` or `errors.AsType[*T]` (1.26+).
   Export sentinels (`ErrNotFound`) for conditions callers branch on, and typed
   errors (`*ValidationError`) when they need fields. Handle each error once:
   log it *or* return it.
5. **`panic` is for programmer bugs only** (impossible states, `Must*`
   helpers at init). Libraries never `log.Fatal`.
6. **`context.Context` is the first parameter, named `ctx`, never stored in a
   struct.** Every call that blocks or does I/O takes one; handlers use
   `r.Context()`.
7. **Every goroutine has an owner who waits for it** (errgroup, WaitGroup) and
   a way to stop (ctx or a closed channel). An unowned goroutine is a leak.
8. **Handlers only translate.** Decode (with `http.MaxBytesReader`), call the
   domain service, map errors to status codes, encode. Business rules live in
   plain functions with no `net/http` imports.
9. **SQL lives in `.sql` files.** sqlc generates typed Go from them, and the
   store adapter maps driver errors (`pgx.ErrNoRows`, unique violation
   `23505`) to domain sentinels. Never build SQL with `Sprintf`.
10. **Servers have timeouts and shut down gracefully.** `http.Server` with
    `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, `IdleTimeout`;
    `signal.NotifyContext` for SIGTERM; `Shutdown` with a drain deadline;
    `/up` for the proxy's health check.
11. **Ship one static binary per service,** which also runs its own migrations
    (`app migrate`), so the image needs no other tools.

Details and code: `references/layout.md`, `references/idioms.md`,
`references/services.md`.

## Workflow

### 1. Classify the request

| The user wants to... | Read | Produce |
|---|---|---|
| Start a module, service, CLI, or library; pick a layout | `references/layout.md`, `references/toolchain.md` | `scripts/scaffold.go` output or the layout tree |
| Write idiomatic code, errors, generics, iterators, APIs | `references/idioms.md` | Idiomatic Go with the "why" |
| Goroutines, channels, races, leaks, worker pools | `references/concurrency.md` | Owned, cancellable concurrency + a `-race` test |
| HTTP handlers, JSON, slog, config, Postgres, migrations | `references/services.md` | Handler + service + store in the house shape |
| Tests, fuzzing, benchmarks, integration tests | `references/testing.md` | Table-driven tests, fuzz targets, benchmarks |
| Lint, CI, vulnerabilities, security review | `references/quality-and-security.md` | `.golangci.yml`, CI workflow, findings |
| Slow code, memory, allocations, profiling | `references/performance.md` | A measured diagnosis (pprof, benchstat), then the fix |
| Docker, Kamal, Cloudflare, cross-compiling, cgo, WASM | `references/deploy-and-interop.md` | Dockerfile, `deploy.yml`, build commands |
| Review code or a PR | `references/quality-and-security.md` (review checklist) | Findings ranked by severity, each with a fix |

### 2. Inspect before prescribing (existing code)

Read `go.mod` (go line, requirements, `tool` and `replace` directives), the
`cmd/` entrypoints, one domain package and its tests, the Dockerfile, and CI.
Follow conventions already present; move toward these defaults incrementally.
For a structural read, run:

```bash
go run scripts/audit.go path/to/module            # human-readable report
go run scripts/audit.go path/to/module --json     # machine-readable
```

It flags: SQL built with `Sprintf`/`+`; servers without timeouts or graceful
shutdown; `InsecureSkipVerify`; hard-coded secrets; cgo binaries in scratch
images; `%v` instead of `%w`; `==` on sentinel errors; type assertions on
errors; `context.Background()` in handlers; contexts in structs; `panic`,
`log.Fatal`, and `os.Exit` in libraries; the default HTTP client and
DefaultServeMux; pprof on the default mux; unbounded request bodies;
`defer` in loops; `err.Error()` sent to clients; `pkg/` and `util`
packages; `tools.go`; `io/ioutil`; archived or discouraged modules; local
`replace`; missing `go.sum`; unsupported `go` lines; `time.Sleep` in tests;
CI without `-race`. It complements `go vet` and golangci-lint; it doesn't
replace them.

### 3. Write the code

- New module: `go run scripts/scaffold.go --module github.com/you/app DIR`
  (or `--kind library`). The output passes vet, golangci-lint, the audit, and
  `go test -race`, and builds statically.
- Every behavior change ships with a test (`references/testing.md`).
- Show complete files or precise diffs, with imports.

### 4. Verify

Run `gofmt -l .` (empty), `go vet ./...`, `go fix -diff ./...`,
`golangci-lint run`, `go test -race ./...`, `go tool govulncheck ./...`, and
for services `CGO_ENABLED=0 go build -trimpath ./cmd/...`. Report failures
honestly; don't claim a gate passed without running it.

## Gotchas: corrections you'd otherwise need

- **json/v2 needs `go 1.27` in go.mod.** With `go 1.26.0`, `go build` still
  succeeds, but `go vet` and `go test` fail (`json.Marshal requires go1.27 or
  later`) because the stdversion check now runs during `go test`.
- **json/v2 behaves differently from v1:** field names match
  case-sensitively, duplicate keys and invalid UTF-8 are errors, nil slices
  and maps encode as `[]`/`{}`, HTML isn't escaped, and unknown fields are
  ignored unless you pass `json.RejectUnknownMembers(true)`. Use `omitzero`,
  not `omitempty`, for zero values.
- **`go run` turns every non-zero exit into 1** (it prints `exit status 2`).
  For exact exit codes, such as the audit's 2 = bad input, build first:
  `go build -o /tmp/audit scripts/audit.go`.
- **Kamal stops proxied containers after 10s** (Docker's default
  `stop_timeout`). Keep the app's shutdown drain under that (the template
  uses 8s). kamal-proxy has already drained in-flight requests
  (`drain_timeout`, 30s) before SIGTERM arrives.
- **kamal-proxy defaults to port 80 and `/up`.** Set `proxy.app_port: 8080`
  and serve `GET /up`. Behind Cloudflare, use Full (strict) with an Origin CA
  certificate, not Let's Encrypt HTTP challenges.
- **`CGO_ENABLED=0` for scratch/distroless-static,** or the binary may link
  libc dynamically and die with "no such file or directory". But
  **`go test -race` needs cgo** on Linux CI, so never export
  `CGO_ENABLED=0` job-wide.
- **Don't put heavy tools in go.mod's `tool` directive.** Tool dependencies
  join your module graph, and MVS can upgrade your app's own dependencies.
  golangci-lint explicitly doesn't support `go tool` installs. Pin them with
  `go run pkg@vX.Y.Z` or the official CI action.
- **golangci-lint v2 config needs `version: "2"`**, `linters.default:
  standard`, and formatters in a separate `formatters:` block. gofmt and
  goimports aren't linters anymore. v1 configs fail `golangci-lint config
  verify`.
- **gosec flags `math/rand` even for jitter** (G404). Keep `math/rand/v2` for
  non-secrets with `//nolint:gosec // jitter, not a secret`; secrets use
  `crypto/rand.Text()`.
- **`ServeMux` precedence is by specificity, not order.** `GET /up` beats
  `GET /{code}`, and conflicting patterns panic at registration. Wildcards
  match one non-empty segment; use `{path...}` for the rest. Registering
  `GET` also serves `HEAD`.
- **`slog.JSONHandler` writes `time.Duration` as integer nanoseconds.** Log
  `duration_ms` (`d.Milliseconds()`) or `d.String()` for humans.
- **A middleware's response-writer wrapper must implement `Unwrap()`,** or
  `http.ResponseController` can't reach `Flush`/`Hijack` (SSE and WebSocket
  break).
- **After a failed statement, a Postgres transaction is aborted.** In a
  rollback-per-test integration test, assert the expected constraint
  violation last.
- **Wrap before you branch:** `errors.Is(err, pgx.ErrNoRows)` must run on
  the driver's error before you wrap it with `%w` and a message; mapping it
  to a domain sentinel in the store keeps pgx out of your domain package.
- **Loop variables have been per-iteration since 1.22.** Delete the
  `v := v` copies; `go fix` does it. Also `for i := range n` and
  `min`/`max` builtins; run `go fix ./...` after raising the go line.
- **`sync.WaitGroup.Go` (1.25+) replaces `Add(1)` + `go` + `defer Done()`.**
  `go vet` reports `wg.Add` inside the new goroutine (a real race), and
  `go fix` rewrites old patterns (analyzer `waitgroupgo` in 1.27).
- **`b.Loop()` replaces `for i := 0; i < b.N; i++`.** It excludes setup
  from timing and keeps results alive, and since 1.26 it doesn't block
  inlining.
- **`testing/synctest` fakes time only inside the bubble,** and bans real
  network I/O there. Use it for timers and backoff (`synctest.Test(t, func(t
  *testing.T){...})`); use `httptest.NewTestServer` (1.27, in-memory
  network) or a real loopback listener for HTTP.
- **Generic methods exist as of 1.27, but not in interfaces.** Don't reach
  for them to emulate OOP; a generic function is usually clearer.
- **sqlc is a cgo build** (~80s the first time via `go run`). Commit the
  generated code, and gate it in CI with `sqlc diff`, not by regenerating.
- **Distroless is now Debian 13:** `gcr.io/distroless/static-debian13:nonroot`.
  Pin the suffix so a Debian bump doesn't change your base silently.

## Available resources

References (load only what the task needs):
- `references/toolchain.md`: verified versions, the release policy, what's
  new in Go 1.25-1.27, go.mod `go`/`toolchain`/`tool`/`ignore` lines, and
  GOTOOLCHAIN.
- `references/layout.md`: library, CLI, service, and multi-module layouts;
  package naming; go.work; and the asset-to-path map.
- `references/idioms.md`: naming, errors, resource cleanup, API design,
  generics, iterators, and the "don't" list.
- `references/concurrency.md`: ownership, errgroup, worker pools, channels vs
  mutexes, cancellation, leaks, and the race detector.
- `references/services.md`: ServeMux routing, middleware, server timeouts and
  shutdown, json/v2, slog, config, pgx + sqlc + goose.
- `references/testing.md`: table tests, parallelism, httptest, fuzzing,
  benchmarks, synctest, Postgres integration tests, and coverage.
- `references/quality-and-security.md`: the quality gate, golangci-lint v2,
  govulncheck, CI, secure coding, and the review checklist.
- `references/performance.md`: the pprof workflow, benchstat, allocations,
  escape analysis, GC and memory limits, and PGO.
- `references/deploy-and-interop.md`: static and cross builds, Docker,
  Kamal 2, Cloudflare, versioning, cgo/C ABI, and WASM.

Templates (`assets/`, flat; verified together as one service module and one
library module: gofmt, vet, golangci-lint, `go test -race` including the
Postgres test, `go fix -diff`, govulncheck, and a static linux build):
- `assets/go.mod.tmpl` and `assets/go.sum.tmpl`: module file with the
  govulncheck tool directive.
- `assets/main.go` and `assets/main_test.go`: `cmd/links`, the thin-main
  `run()` pattern with serve, migrate, and version subcommands.
- `assets/server.go` and `assets/server_test.go`: `internal/server`: `/up`,
  middleware, CSRF protection, timeouts, and graceful shutdown.
- `assets/link.go`, `assets/http.go`, `assets/postgres.go`: the domain
  service, HTTP handler, and pgx store; tests in `assets/link_test.go`
  (table, fuzz, benchmark), `assets/http_test.go`,
  `assets/postgres_test.go` (real Postgres), and `assets/fake_test.go`.
- `assets/linkdb-db.go`, `assets/linkdb-models.go`,
  `assets/linkdb-links.sql.go`: sqlc output (`internal/link/linkdb`).
- `assets/db.go`, `assets/00001_create_links.sql`,
  `assets/queries-links.sql`, `assets/sqlc.yaml`: embedded goose migrations
  and sqlc input.
- `assets/golangci.yml`, `assets/github-ci.yml`: lint config and the CI gate.
- `assets/Dockerfile`, `assets/dockerignore`, `assets/deploy.yml`,
  `assets/kamal-pre-deploy`: image, Kamal config, and the migration hook
  (Docker builds weren't run during verification).
- `assets/retry.go`, `assets/retry_test.go`, `assets/retry_example_test.go`:
  a library package with synctest tests, runnable examples, and an iterator.

Scripts ship with this skill, not with the user's project. Run them from
this skill's directory against the user's path, and report findings in
terms of the user's files. Never tell the user to run a skill script as if
it were in their repo.

Scripts (Go standard library only; `--help`; exit 0 ok, 1 findings, 2 bad input):
- `scripts/audit.go`: static anti-pattern scan with `--json` and
  `--fail-on high|medium|low|none` (default high).
- `scripts/scaffold.go`: lays the templates out as a new service or library
  module with your module path.
