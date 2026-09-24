# Quality gate, security, and review

## Contents
- The gate (local and CI)
- gofmt, goimports, go vet, go fix
- golangci-lint v2
- govulncheck and dependency hygiene
- The CI workflow
- Secure coding checklist
- Review checklist (severity-ranked)

## The gate (local and CI)

Zero warnings; each step fails the build:

```bash
test -z "$(gofmt -l .)"                 # formatting
go mod tidy -diff                       # go.mod/go.sum tidy
go vet ./...                            # compiler-adjacent correctness checks
go fix -diff ./...                      # no pending modernizations (1.26+)
golangci-lint run                       # the lint set in .golangci.yml
go tool govulncheck ./...               # reachable known vulnerabilities
go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.31.1 diff   # generated SQL code is current
go test -race -shuffle=on ./...         # tests + data races
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" ./cmd/...   # release build
```

Also run the skill's structural audit: `go run scripts/audit.go . --fail-on medium`.

## gofmt, goimports, go vet, go fix

- **gofmt** is not negotiable. goimports adds import grouping (stdlib,
  third-party, then local with `local-prefixes`). golangci-lint v2 runs both
  as *formatters* (`golangci-lint fmt`).
- **go vet** catches printf mismatches, copied locks, unreachable code,
  misplaced `wg.Add` (`waitgroup`), `Sprintf` host:port (`hostport`),
  unkeyed composite literals of other packages, and, when run by `go test`,
  stdlib APIs newer than your `go` line (`stdversion`, 1.27).
- **go fix** (rebuilt in 1.26) applies modernizers: `forvar` (drop
  `v := v`), `rangeint`, `minmax`, `any`, `errorsastype`, `waitgroupgo`,
  `newexpr`, `omitzero`, `slicescontains`, `stringscut`,
  `stringsseq`, `testingcontext`, and more (`go tool fix help` lists them).
  Run `go fix ./...` after raising the `go` line, and `go fix -diff ./...` in
  CI.

## golangci-lint v2

Config (`assets/golangci.yml` → `.golangci.yml`), verified with
`golangci-lint config verify` and zero issues on the templates:

```yaml
version: "2"
linters:
  default: standard        # errcheck, govet, ineffassign, staticcheck, unused
  enable: [bodyclose, errorlint, gosec, misspell, modernize, noctx, nolintlint,
           rowserrcheck, sqlclosecheck, unconvert, usestdlibvars, usetesting]
  settings:
    govet: { enable-all: true, disable: [fieldalignment, shadow] }
    nolintlint: { require-explanation: true, require-specific: true }
  exclusions:
    generated: lax
    presets: [std-error-handling]
    rules:
      - { path: _test\.go, linters: [gosec, noctx] }
formatters:
  enable: [gofmt, goimports]
  settings:
    goimports: { local-prefixes: [github.com/acme/links] }
```

- Why these: `errorlint` enforces `%w`/`errors.Is`; `bodyclose`,
  `sqlclosecheck`, and `rowserrcheck` catch leaks; `noctx` forces
  context-aware network calls (it rejected the template's `net.Listen` in
  favor of `net.ListenConfig.Listen(ctx, ...)`); `gosec` finds injection,
  weak crypto, and overflow; `nolintlint` keeps suppressions honest.
- Don't enable everything (`default: all`). Style linters like
  `wsl`, `varnamelen`, and `exhaustruct` cost more review time than they save.
- Suppress narrowly, with a reason: `//nolint:gosec // jitter, not a secret`.
- Install a pinned **binary** (the golangci-lint docs don't support
  `go install`/`go tool`), with `golangci/golangci-lint-action@v9` in CI
  (`version: v2.14.0`), or `mise use golangci-lint@2.14`. Migrate a v1 config
  with `golangci-lint migrate`.
- Just staticcheck? `go run honnef.co/go/tools/cmd/staticcheck@2026.2.1 ./...`
  is a fine minimal alternative for tiny libraries.

## govulncheck and dependency hygiene

- `go get -tool golang.org/x/vuln/cmd/govulncheck@v1.8.0`, then
  `go tool govulncheck ./...`. It reports only vulnerabilities your code can
  **reach** through the call graph, so its findings are actionable. Run
  `-mode=binary ./bin/app` against release artifacts too.
- Every dependency is a liability. Before adding one, check that the stdlib
  (or `golang.org/x/...`) can't do it, that the project is maintained, and
  what it pulls in (`go mod graph | grep`). Prefer a few lines of code over
  a small library.
- Upgrade on a schedule: `go list -m -u all`, `go get -u=patch ./...`, and
  Dependabot or Renovate for `gomod` plus `github-actions`.
- `go.sum` is committed. `GOFLAGS=-mod=readonly` (the default outside
  `go get`) refuses to change it silently. `GOPROXY`/`GOSUMDB` defaults
  verify module integrity; set `GOPRIVATE` for private modules rather than
  disabling the checksum DB.
- Vendor (`go mod vendor`) only when builds must work with no network.

## The CI workflow

`assets/github-ci.yml`: `actions/checkout@v7`, `actions/setup-go@v7` with
`go-version-file: go.mod` (it caches modules and the build cache), a
Postgres 18 service container, and each gate command above as its own step
so failures are obvious. `-race` needs cgo on Linux (the runner has gcc),
so `CGO_ENABLED=0` is set only on the release build step. Add
`permissions: contents: read` at the top.

## Secure coding checklist

- **Input:** bound every body (`http.MaxBytesReader`), reject unknown JSON
  fields on write endpoints, validate with explicit rules (length, charset,
  scheme; see `link.NormalizeURL`), and fuzz the validators.
- **SQL:** placeholders only (sqlc guarantees it). Identifiers that must be
  dynamic go through an allowlist or `pgx.Identifier{...}.Sanitize()`.
- **Commands and paths:** `exec.CommandContext(ctx, "bin", args...)`, never
  `sh -c` with user input. Use `os.Root`/`os.OpenInRoot` (1.24+) or
  `filepath.IsLocal` for user-supplied paths.
- **Templates:** `html/template` (contextual escaping) for HTML, never
  `text/template`.
- **Crypto:** `crypto/rand` for tokens (`rand.Text()`), `crypto/subtle.ConstantTimeCompare`
  for secrets, `golang.org/x/crypto/argon2` or `bcrypt` for passwords,
  TLS defaults (don't set `MinVersion` lower, never `InsecureSkipVerify`).
  FIPS 140-3 mode exists (`GODEBUG=fips140=on`) when compliance needs it.
- **Secrets:** from the environment at startup; never in code, flags, logs,
  or error messages returned to clients. Log redaction: implement
  `slog.LogValuer` on secret-holding types.
- **Servers:** timeouts on every `http.Server`, CSRF protection for
  cookie-authenticated browsers, no pprof on the public listener (mount it on
  a private port), and a 500 path that never echoes `err.Error()`.
- **Integer conversions:** clamp before narrowing (`int32(min(max(n, 0), 1000))`),
  since gosec G115 flags unchecked ones.
- **Unsafe and cgo:** `unsafe` needs a written justification. cgo turns off
  the memory-safety guarantees for that code, and breaks static builds.

## Review checklist (severity-ranked)

Report findings as **High / Medium / Low**, each with the file:line, why it
matters, and the fix.

**High (fix before merge):** SQL built with `Sprintf`/`+`;
`InsecureSkipVerify`; hard-coded secrets; `http.ListenAndServe` or an
`http.Server` without timeouts; data races (shared maps or counters
mutated from goroutines); goroutine leaks (fire-and-forget work, sends
nobody receives); missing auth or tenant scoping; a static image with a
cgo binary; ignored errors on writes, commits, or `Close` of written files.

**Medium:** `%v` where `%w` belongs; `==` or type assertions on errors;
`err.Error()` sent to clients; `context.Background()` in request paths;
`ctx` stored in structs; `panic`/`log.Fatal`/`os.Exit` outside `main`;
default HTTP client or DefaultServeMux; pprof on the public mux; unbounded
bodies; `defer` in loops; no graceful shutdown; `wg.Add` inside the
goroutine; local `replace`; missing `go.sum`; unbounded fan-out;
`time.Sleep` for synchronization.

**Low:** `pkg/` and `util` packages; `GetX` getters; ctx not first; old
`go` line or `tools.go`; `io/ioutil`, `pkg/errors`, logrus, `lib/pq`, router
frameworks where ServeMux suffices; `time.Sleep` in tests; CI without
`-race`; missing `-trimpath`; stutter (`link.LinkService`); missing doc
comments on exports.

Use `scripts/audit.go --json` for the mechanical part, then read the
concurrency and error paths yourself: the audit can't see races or leaks.

Sources: https://golangci-lint.run/docs/configuration/file/,
https://go.dev/doc/security/best-practices, https://go.dev/doc/security/vuln/,
https://pkg.go.dev/cmd/vet, https://go.dev/blog/gofix
