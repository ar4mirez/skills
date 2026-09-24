# Project layout

One module, conventional directories, and packages named for what they
provide. The layouts below follow go.dev's "Organizing a Go module" guide;
the service layout is exactly what `scripts/scaffold.go` produces.

## Contents
- Rules that apply to every layout
- (a) Library
- (b) CLI
- (c) Network service (the template)
- (d) Several modules: monorepo and go.work
- Package design
- Asset-to-path map

## Rules that apply to every layout

- **One `go.mod` per repository** unless parts are versioned and released
  separately. Several modules in one repo mean several version tags,
  several `go.sum` files, and `replace` pain.
- **`internal/` for everything that isn't public API.** The compiler stops
  other modules from importing it, so you can refactor freely.
- **No `pkg/`.** It adds a path segment and says nothing. Public packages
  of a library go at the module root, or in directories named for the
  package.
- **No `util`, `common`, `helpers`, `models`, or `types` packages.** Name a
  package for what it provides, so call sites read well (`link.Service`,
  `retry.Do`). A helper used by one package lives in that package.
- **Tests sit beside the code** (`x_test.go`). Fixtures go in `testdata/`,
  which the go tool ignores.
- **Generated code is committed** and marked `// Code generated ... DO NOT
  EDIT.` so linters and the audit skip it.

## (a) Library

```
retry/
  go.mod              module github.com/acme/retry
  retry.go            package doc comment + API
  retry_test.go       black-box tests (package retry_test)
  example_test.go     runnable Examples: they show up in go doc and run in go test
  .golangci.yml
```

- The import path is the API. For `v2+`, change the module path
  (`github.com/acme/retry/v2`), not just the tag.
- Keep the exported surface small: one type and a few functions beat an
  interface-heavy "framework". Every export is a compatibility promise.
- No global state, no `init()` side effects, no logging (return errors;
  accept a `*slog.Logger` option if you truly must log).
- Tag releases `vX.Y.Z` from the module root. For a subdirectory module, the
  tag is `dir/vX.Y.Z`.

## (b) CLI

```
tool/
  go.mod
  main.go             or cmd/tool/main.go if the repo holds more than the CLI
  main_test.go        tests call run(...) directly
  internal/...        the real logic
```

```go
func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdin, os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "tool:", err)
		os.Exit(1)
	}
}
```

- Use `flag.NewFlagSet(name, flag.ContinueOnError)` inside `run`, not the
  global `flag` package, so tests can parse args repeatedly.
  `errors.Is(err, flag.ErrHelp)` means the user asked for `-h`: exit 0.
- Subcommands: `switch args[0]` with one `FlagSet` each. Reach for cobra
  only when you need nested command trees, completions, and generated docs.
- Exit codes are part of the interface: document them, and keep
  `os.Exit` in `main` only.
- Read input from `io.Reader` and write to `io.Writer` parameters. That makes
  the CLI a pure function under test.

## (c) Network service (the template)

```
links/
  go.mod  go.sum  sqlc.yaml  .golangci.yml  Dockerfile  .dockerignore
  cmd/links/main.go               run(): config, logger, pool, subcommands (serve, migrate, version)
  internal/server/server.go       root handler: /up, middleware, CSRF protection, Serve(ctx, ln, ...)
  internal/link/link.go           domain: types, sentinel and typed errors, Store interface, Service
  internal/link/http.go           Handler.Register(mux): decode, call Service, map errors, encode
  internal/link/postgres.go       PostgresStore: sqlc queries, driver errors mapped to sentinels
  internal/link/linkdb/           sqlc output (generated, committed)
  db/db.go                        //go:embed migrations + Migrate(ctx, pool) via goose
  db/migrations/00001_*.sql       goose files (-- +goose Up / Down)
  db/queries/*.sql                sqlc input
  config/deploy.yml               Kamal 2
  .kamal/hooks/pre-deploy         runs `/links migrate` with the new image
  .github/workflows/ci.yml
```

Dependency direction: `cmd/links` → `internal/server`, `internal/link`, `db`.
`internal/link` imports nothing from `server`. Only `postgres.go` knows
about pgx, and only `http.go` knows about `net/http`. A second domain is a
sibling package (`internal/billing`) with the same four files. Domains talk
through exported functions or interfaces declared by the caller, never
through each other's database tables.

To add a feature: write the SQL in `db/queries/`, run `go generate ./db`,
extend the `Store` interface and `PostgresStore`, add the service method,
test it with the fake, then add the route and an HTTP test.

## (d) Several modules: monorepo and go.work

Split into modules only when the parts have **different release cadences
or consumers** (for example, a public SDK and a private service). Then:

```
repo/
  go.work             go 1.27.0 / use ./sdk ./service   (NOT committed for libraries)
  sdk/go.mod          module github.com/acme/sdk
  service/go.mod      module github.com/acme/service  (require github.com/acme/sdk v1.4.0)
```

- `go work init ./sdk ./service` lets local edits to `sdk` show up in
  `service` without `replace`.
- CI should test each module **without** the workspace too
  (`GOWORK=off go test ./...` in each dir), because that's how consumers
  build it.
- Services in one repo that always deploy together belong in **one module**
  with several `cmd/` entrypoints, not in several modules.

## Package design

- A package is a unit of **understanding**, not of file count. Several files
  per package is normal. Split when a subset has a different dependency set
  or a clear sub-concept.
- Avoid import cycles by moving shared types down into the lower package,
  not by adding an interface package.
- Package-level variables are acceptable for immutable things (sentinel
  errors, compiled regexps, lookup tables), never for mutable
  configuration or clients. Pass those in.
- The file named after the package holds its doc comment:
  `// Package link implements ...`.

## Asset-to-path map

`go run scripts/scaffold.go --module M DIR` copies these for you and
rewrites `github.com/acme/links` (or `github.com/acme/retry`) to `M`:

| Asset | Path in the service |
|---|---|
| `go.mod.tmpl`, `go.sum.tmpl` | `go.mod`, `go.sum` |
| `main.go`, `main_test.go` | `cmd/links/` |
| `server.go`, `server_test.go` | `internal/server/` |
| `link.go`, `link_test.go`, `http.go`, `http_test.go`, `postgres.go`, `postgres_test.go`, `fake_test.go` | `internal/link/` |
| `linkdb-db.go`, `linkdb-models.go`, `linkdb-links.sql.go` | `internal/link/linkdb/db.go`, `models.go`, `links.sql.go` |
| `db.go` | `db/db.go` |
| `00001_create_links.sql` | `db/migrations/` |
| `queries-links.sql` | `db/queries/links.sql` |
| `sqlc.yaml`, `Dockerfile` | repo root |
| `golangci.yml`, `dockerignore` | `.golangci.yml`, `.dockerignore` |
| `deploy.yml` | `config/deploy.yml` |
| `kamal-pre-deploy` | `.kamal/hooks/pre-deploy` (executable) |
| `github-ci.yml` | `.github/workflows/ci.yml` |
| `retry.go`, `retry_test.go`, `retry_example_test.go` | library root (`--kind library`; the example becomes `example_test.go`) |

After scaffolding, rename `cmd/links` and the `links` binary name in the
Dockerfile, `deploy.yml`, and the hook.

Source: https://go.dev/doc/modules/layout, https://go.dev/ref/mod#workspaces
