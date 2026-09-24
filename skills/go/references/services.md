# Services: HTTP, JSON, logging, config, Postgres

The house shape for a network service, as built in the assets (`server.go`,
`http.go`, `link.go`, `postgres.go`, `db.go`, `main.go`). Everything here ran
against a real Postgres 18 during verification.

## Contents
- Routing with ServeMux
- Handlers: decode, call, map errors, encode
- Middleware
- The server: timeouts, shutdown, /up
- JSON with encoding/json/v2
- Logging with slog
- Configuration
- Postgres: pgxpool, sqlc, goose
- Transactions
- Outbound HTTP
- Security headers and CSRF

## Routing with ServeMux

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /up", health(db))
mux.HandleFunc("POST /api/links", h.create)
mux.HandleFunc("GET /api/links", h.list)
mux.HandleFunc("GET /{code}", h.redirect)          // r.PathValue("code")
mux.HandleFunc("GET /files/{path...}", h.file)     // rest of the path
mux.HandleFunc("GET /{$}", h.home)                 // exactly "/"
```

- Method patterns return 405 with an `Allow` header for other methods, and
  `GET` also serves `HEAD`.
- The most specific pattern wins, regardless of registration order.
  Patterns that overlap with neither more specific panic at registration,
  so conflicts surface at startup, in tests.
- Group routes per feature with a `Register(mux)` method. Mount a sub-tree
  with `mux.Handle("/admin/", http.StripPrefix("/admin", adminMux))`.
- Never register on `http.DefaultServeMux` (`http.HandleFunc`). Any imported
  package (pprof, expvar) can add routes to it.

## Handlers: decode, call, map errors, encode

```go
func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var req createRequest
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	if err := json.UnmarshalRead(r.Body, &req, json.RejectUnknownMembers(true)); err != nil {
		if _, tooBig := errors.AsType[*http.MaxBytesError](err); tooBig {
			h.writeJSON(w, http.StatusRequestEntityTooLarge, errorBody{Error: "request body too large"})
			return
		}
		h.writeJSON(w, http.StatusBadRequest, errorBody{Error: "invalid JSON body"})
		return
	}
	l, err := h.svc.Shorten(r.Context(), req.URL, req.Code)
	if err != nil {
		h.writeError(w, r, err)   // one place maps domain errors to status codes
		return
	}
	h.writeJSON(w, http.StatusCreated, l)
}
```

- One `writeError` maps `*ValidationError` → 422, `ErrNotFound` → 404,
  `ErrCodeTaken` → 409, and everything else → 500. The 500 path **logs** the
  error with `r.Context()` and returns a generic body. Never send
  `err.Error()` to clients; it leaks SQL, hostnames, and file paths.
- Set headers before `WriteHeader`, and call `WriteHeader` once. After the
  body starts, you can't change the status.
- Parse query parameters explicitly (`strconv.Atoi`) and treat a parse
  failure as a 422 for that field.
- The service layer never sees `http.Request`. It takes plain values and a
  `ctx`.

## Middleware

A middleware is `func(http.Handler) http.Handler`. Compose them explicitly in
`server.New`, outermost first: recover → log → CSRF → mux.

```go
type statusRecorder struct {
	http.ResponseWriter
	status int
}
func (r *statusRecorder) WriteHeader(code int)          { r.status = code; r.ResponseWriter.WriteHeader(code) }
func (r *statusRecorder) Unwrap() http.ResponseWriter   { return r.ResponseWriter } // keeps Flush/Hijack reachable
```

Put request-scoped values in the context with an unexported key type, and
only for request metadata (request ID, authenticated user), never for
optional parameters.

## The server: timeouts, shutdown, /up

```go
srv := &http.Server{
	Handler:           handler,
	ReadHeaderTimeout: 5 * time.Second,   // Slowloris
	ReadTimeout:       15 * time.Second,
	WriteTimeout:      30 * time.Second,  // longer than your slowest handler; per-route with http.ResponseController
	IdleTimeout:       120 * time.Second,
	ErrorLog:          slog.NewLogLogger(log.Handler(), slog.LevelWarn),
	BaseContext:       func(net.Listener) context.Context { return context.WithoutCancel(ctx) },
}
```

- `main` creates `ctx` with `signal.NotifyContext(ctx, os.Interrupt,
  syscall.SIGTERM)`. `server.Serve` runs `srv.Serve(ln)` in a goroutine,
  waits for `ctx.Done()`, then `srv.Shutdown` with a deadline (8s, under
  Docker's 10s kill), and finally treats `http.ErrServerClosed` as success.
- Listen with `net.ListenConfig{}.Listen(ctx, "tcp", addr)` and pass the
  listener in. Tests can then bind `127.0.0.1:0`.
- `BaseContext` uses `WithoutCancel` so in-flight requests aren't cancelled
  the instant SIGTERM arrives; `Shutdown` lets them finish.
- `/up` pings the database with a 2s timeout. kamal-proxy only routes to a
  new container once `/up` returns 200, so a bad `DATABASE_URL` fails the
  deploy instead of serving 500s.
- Streaming or long-poll routes: extend the deadline per request with
  `http.NewResponseController(w).SetWriteDeadline(...)`.

## JSON with encoding/json/v2

Import `"encoding/json/v2"` (package `json`); the module needs `go 1.27`.

| Behavior | v1 | v2 |
|---|---|---|
| Field name matching | case-insensitive | **case-sensitive** |
| Duplicate object keys | last wins | **error** |
| Invalid UTF-8 | replaced | **error** |
| nil slice / nil map | `null` | **`[]` / `{}`** |
| HTML characters (`<`, `&`) | escaped | not escaped |
| Unknown fields | ignored | ignored (`json.RejectUnknownMembers(true)` to reject) |
| `omitempty` | omits false/0/"" | omits only empty JSON (`""`, `[]`, `{}`, `null`); use **`omitzero`** for Go zero values |
| Streaming | `NewDecoder(r).Decode` | `json.UnmarshalRead(r, &v)`, `json.MarshalWrite(w, v)` |

- Low-level token work goes through `encoding/json/jsontext`.
- Mixing is fine during migration: v1 is implemented on v2, and
  `jsonv1 "encoding/json"` can coexist in one file.
- Tests in the assets prove unknown and duplicate keys produce 400.

## Logging with slog

- `slog.New(slog.NewJSONHandler(stdout, &slog.HandlerOptions{Level: lvl}))`
  in `main`, passed down as `*slog.Logger`. Don't call `slog.SetDefault` in
  libraries.
- Use the `...Context` methods (`log.ErrorContext(ctx, ...)`) so handlers can
  add trace or request IDs from the context.
- Log keys are `snake_case` and stable. `time.Duration` renders as integer
  nanoseconds in JSON, so log `duration_ms`.
- `slog.NewMultiHandler` (1.26) fans out to several handlers.
  `slog.DiscardHandler` silences logs in tests.
- Parse `LOG_LEVEL` with `slog.Level.UnmarshalText` (it accepts `debug`,
  `info`, `warn`, `error`).

## Configuration

Read the environment once, in `main`, into an unexported `config` struct:
`cmp.Or(getenv("PORT"), "8080")`, and required values error out
(`DATABASE_URL is required`). Pass `getenv` as a function so tests don't
touch the process environment. No config library, no global `viper`.
Secrets come from the environment (Kamal `env.secret`), never from flags or
files baked into the image.

## Postgres: pgxpool, sqlc, goose

**Pool:** `pgxpool.New(ctx, url)` once in `main`; `defer pool.Close()`. Tune
with URL parameters (`pool_max_conns=10`). The pool satisfies
`linkdb.DBTX`, so the same store works over a pool, a connection, or a
transaction.

**sqlc** (`sqlc.yaml`, version 2): `engine: postgresql`,
`sql_package: pgx/v5`, the schema read from the goose migrations directory
(sqlc ignores the `-- +goose Down` sections), `overrides` mapping
`timestamptz` to `time.Time`, and `rename` for initialisms. Queries are
annotated `-- name: GetLinkByCode :one` (`:one`, `:many`, `:exec`,
`:execrows`). Regenerate with `go generate ./db`, which runs
`go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.31.1 generate -f ../sqlc.yaml`.

**Store adapter:** convert rows to domain types (`Link(row)` works when the
field sets match exactly, so a schema change becomes a compile error) and map
errors:

```go
if pgErr, ok := errors.AsType[*pgconn.PgError](err); ok && pgErr.Code == "23505" {
	return Link{}, ErrCodeTaken          // unique_violation
}
if errors.Is(err, pgx.ErrNoRows) {
	return Link{}, ErrNotFound
}
```

**Migrations (goose as a library):** `//go:embed migrations/*.sql`,
`goose.NewProvider(goose.DialectPostgres, stdlib.OpenDBFromPool(pool),
fs.Sub(...))`, then `provider.Up(ctx)`. The binary's `migrate` subcommand runs
it, and Kamal's pre-deploy hook invokes that with the new image. Write
migrations **expand then contract**: add columns nullable or with defaults,
backfill, and deploy code that uses the new column before dropping the old
one, because the old version keeps serving during the deploy.

Schema rules: `bigint GENERATED ALWAYS AS IDENTITY` or `uuid` (v7 from the
1.27 `uuid` package) keys, `NOT NULL` by default, `CHECK` constraints for
invariants, `timestamptz`, and an index for every foreign key and filter
column.

## Transactions

```go
tx, err := pool.Begin(ctx)
if err != nil { return err }
defer tx.Rollback(ctx)                    // no-op after Commit
q := linkdb.New(tx)
// ... several queries ...
return tx.Commit(ctx)
```

For a helper, use `pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error { ... })`.
Behind PgBouncer in transaction mode, set `default_query_exec_mode=exec` or
`simple_protocol` in the connection string (pgx v5 supports both),
and run migrations on a direct connection.

## Outbound HTTP

One shared `*http.Client{Timeout: 10 * time.Second}` per dependency
(clients are safe for concurrent use and pool connections). Every request
is `http.NewRequestWithContext(ctx, ...)`. Always `defer resp.Body.Close()`
and check `resp.StatusCode` before decoding. Retry only idempotent calls,
with backoff and jitter (`retry.Do` in the assets). Never use `http.Get`
(the default client has no timeout).

## Security headers and CSRF

`http.NewCrossOriginProtection().Handler(mux)` (1.25+) rejects cross-site
unsafe-method browser requests using `Sec-Fetch-Site`/`Origin`, and lets
non-browser clients through. Add trusted origins with
`AddTrustedOrigin`. For HTML responses, also set CSP,
`X-Content-Type-Options: nosniff`, and `Referrer-Policy`. Cloudflare can add
HSTS at the edge.

Sources: https://pkg.go.dev/net/http#ServeMux, https://go.dev/blog/routing-enhancements,
https://pkg.go.dev/encoding/json/v2, https://go.dev/blog/jsonv2-exp,
https://pkg.go.dev/log/slog, https://pkg.go.dev/github.com/jackc/pgx/v5,
https://docs.sqlc.dev/en/stable/reference/config.html, https://pressly.github.io/goose/
