# Services: axum, tower, tracing, sqlx

Primary sources: axum docs and CHANGELOG (https://docs.rs/axum/0.8.9), tower-http
(https://docs.rs/tower-http/0.7.1), tracing-subscriber
(https://docs.rs/tracing-subscriber), and sqlx
(https://docs.rs/sqlx/0.9.0, https://github.com/launchbadge/sqlx/blob/main/sqlx-cli/README.md).
Every snippet here comes from the verified `assets/api-*.rs` files.

## Contents
- Shape of a service
- axum 0.8: routes, extractors, state
- Errors and responses
- The middleware stack (tower-http 0.7)
- Configuration
- Telemetry with tracing
- sqlx: pool, queries, migrations, offline data
- Transactions
- Health, readiness, and shutdown
- Outbound HTTP
- Service checklist

## Shape of a service

`src/main.rs` wires the process (config, telemetry, pool, migrations, listener,
shutdown). `src/lib.rs` exposes `AppState` and `app(state, ..) -> Router`, so
integration tests build the exact router production runs. Each feature module
(`links.rs`) owns its routes, request/response types, and queries.

Don't add layers "for architecture": no repository traits, service traits, or
DI containers until there are two real implementations. The handler calls
sqlx directly; the domain crate holds the rules that are worth unit testing.

## axum 0.8: routes, extractors, state

- **Path syntax is `/{param}` and `/{*rest}`.** axum 0.8 upgraded matchit and
  **panics at router construction** on the 0.7 forms `/:param` and `/*rest`,
  so a stale tutorial compiles and then crashes on boot.
- Extractors run in argument order. The body extractor (`Json<T>`, `Form<T>`,
  `String`, `Bytes`) consumes the request and must be **last**.
- `State<AppState>`: `AppState` is `Clone` and holds cheap handles (`PgPool`,
  `reqwest::Client`, config values). Don't use `Extension` for app state; it's
  untyped and fails at runtime instead of compile time.
- Sub-routers are `Router<AppState>`, merged with `.merge()` or `.nest()`, and
  `.with_state(state)` is called once at the top.
- `#[serde(deny_unknown_fields)]` on request bodies catches client typos.
- `Option<Path<T>>` and `Option<Query<T>>` no longer swallow errors in 0.8;
  optional extractors implement `OptionalFromRequestParts`.
- `FromRequestParts` impls use native `async fn` (no `#[async_trait]`).
- The `Host` extractor moved to `axum-extra`.
- Handlers must be `Send + Sync`. If you get "`Handler` is not implemented",
  add `#[axum::debug_handler]` (the `macros` feature) to see which value is
  `!Send`; it's usually a std guard or an `Rc` held across `.await`.

## Errors and responses

One `ApiError` enum per service (`assets/api-error.rs`):
- variants map to statuses in `IntoResponse`: `NotFound` 404, `Invalid` 422,
  `Conflict` 409, `Database` 500;
- `#[from] sqlx::Error` lets handlers use `?`;
- 500s log the detail with `tracing::error!` and return a generic body. Never
  leak SQL, driver messages, or stack traces;
- map specific database errors deliberately (a unique violation becomes 409
  with `db.is_unique_violation()`), not by matching message strings.

Return `Result<impl IntoResponse, ApiError>` or a concrete tuple like
`(StatusCode, Json<T>)`. Response types derive `Serialize`; use newtypes
(`ShortCode`, `Slug`) in them so invalid values can't be serialized.

## The middleware stack (tower-http 0.7)

From `assets/api-lib.rs` (layers added later wrap the earlier ones, so the
last `.layer` runs first on the request):

```rust
.layer(RequestBodyLimitLayer::new(64 * 1024))
.layer(TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, request_timeout))
.layer(CatchPanicLayer::new())
.layer(TraceLayer::new_for_http())
.layer(PropagateRequestIdLayer::x_request_id())
.layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))
```

- `TimeoutLayer::new` is deprecated since 0.6.7; use `with_status_code`.
- axum already applies a 2 MB `DefaultBodyLimit` to its body extractors; set a
  smaller explicit limit that fits the API.
- `CatchPanicLayer` turns handler panics into 500s (with `panic = "unwind"`).
- CORS (`tower_http::cors::CorsLayer`) only for browser clients on another
  origin. List the origins; don't combine `Any` with credentials.
- Rate limiting belongs at the edge (Cloudflare) first. In-process, use
  `tower::limit::ConcurrencyLimitLayer` for back-pressure.
- tower-http 0.7 adds CSRF protection middleware (`csrf` feature) for
  cookie-authenticated browser forms.

## Configuration

`assets/api-config.rs` is the pattern: a typed `Config` struct, read **once**
at startup from the environment with defaults and precise errors, then passed
down. There's no config crate: `std::env::var` plus `parse()` covers
twelve-factor config, and every dependency costs you.

- `from_lookup(get: impl Fn(&str) -> Option<String>)` makes it testable
  without touching the process environment. `std::env::set_var` is `unsafe` in
  edition 2024, and in tests it races other threads.
- Hand-write `Debug` to redact secrets, then log the config at startup.
- Reach for `figment` or `config` only for layered file + env configuration
  that a CLI or desktop app needs.
- Local development: export variables, or use a `.env` file with your shell or
  `mise`. Don't load `.env` from the binary in production.

## Telemetry with tracing

- `tracing` for events and spans, `tracing-subscriber` with `json()` and
  `EnvFilter` (`RUST_LOG=info,tower_http=warn`) in services. Use the pretty
  (default) format for CLIs and local development.
- Structured fields, not formatted strings: `tracing::info!(user_id = %id, "created")`.
  `%` uses `Display`, `?` uses `Debug`.
- `#[tracing::instrument(skip(state), fields(code = %code))]` on functions whose
  duration matters. Always `skip` large or secret arguments.
- Libraries emit `tracing` events but never install a subscriber.
- For OpenTelemetry export, add `tracing-opentelemetry` and an OTLP exporter
  when there is a collector to send to. Verify the current crate versions
  (they move together), and don't add them speculatively.

## sqlx: pool, queries, migrations, offline data

- **Pool:** `PgPoolOptions::new().max_connections(n).connect(url)`. The pool is
  an `Arc` inside; clone it. Size it to the database's budget divided by the
  replicas (Postgres defaults to 100 connections total). Behind PgBouncer in
  transaction mode, disable the statement cache
  (`PgConnectOptions::statement_cache_capacity(0)`).
- **Compile-time checked queries are the default:** `sqlx::query!`,
  `query_as!`, and `query_scalar!` check SQL, parameter types, and result
  nullability against a real schema at compile time.
  - Nullable columns come back as `Option<T>`. Override with
    `SELECT col AS "col!"` (non-null) or `"col?"` (nullable) only when you know
    better than the inference.
  - Dev and CI need either `DATABASE_URL` (a migrated database) or committed
    offline data: `cargo sqlx prepare --workspace` writes `.sqlx/` at the
    workspace root. Builds without a database set `SQLX_OFFLINE=true`, and CI
    runs `cargo sqlx prepare --workspace --check` so the data can't go stale.
- **sqlx 0.9:** all `query*()` functions take `impl SqlSafeStr`. A
  `&'static str` works; a runtime `String` must be wrapped in `AssertSqlSafe(..)`.
  That wrapper is an assertion you are making, not sanitization. Build dynamic
  SQL with `QueryBuilder` and `push_bind`, never with `format!`.
- **Migrations:** `crates/<api>/migrations/<timestamp>_<name>.sql`, created
  with `cargo sqlx migrate add -r <name>` for reversible migrations or without
  `-r` for forward-only ones. Embed them with `sqlx::migrate!()` (the path is
  relative to the crate's `Cargo.toml`) and run them at boot; sqlx takes a
  Postgres advisory lock, so concurrent boots are safe.
- Deploy with **expand, then contract**: add columns as nullable (or with
  defaults), deploy code that writes both, backfill, then drop the old column
  in a later release. The old and new versions run side by side during a
  Kamal rollout.
- Constraints live in SQL (`NOT NULL`, `UNIQUE`, `CHECK`, and foreign keys):
  the database is the last line of defense, and the app won't be the only
  writer forever.

## Transactions

```rust
let mut tx = state.db.begin().await?;
sqlx::query!("UPDATE accounts SET balance = balance - $1 WHERE id = $2", amount, from)
    .execute(&mut *tx).await?;
sqlx::query!("UPDATE accounts SET balance = balance + $1 WHERE id = $2", amount, to)
    .execute(&mut *tx).await?;
tx.commit().await?;
```
If the future is dropped (client disconnect, timeout) or `?` returns early, the
transaction rolls back when `tx` drops. That's what makes handlers
cancellation-safe. Don't hold a transaction open across calls to other
services.

## Health, readiness, and shutdown

- `GET /up` returns `200 ok` without touching the database. kamal-proxy uses it
  to decide when a new container can take traffic. Deploy-time problems like a
  bad `DATABASE_URL` or a failed migration already fail at boot, before `/up`
  answers, because `main` connects and migrates first.
- Add a separate readiness check (`SELECT 1`) only if an orchestrator uses it
  to shed traffic. Don't make liveness depend on the database, or a database
  blip restarts every replica.
- Graceful shutdown on SIGTERM and Ctrl-C: see `async-and-concurrency.md` and
  `assets/api-main.rs`.

## Outbound HTTP

`reqwest` 0.13 with rustls: build one `Client` at startup (it pools
connections), put it in `AppState`, set `timeout` and `connect_timeout`, and
treat every response status explicitly (`error_for_status()`). Retries use
backoff with jitter and only apply to idempotent requests.

## Service checklist

- [ ] Routes use `{param}` syntax, and the body extractor is last.
- [ ] One `ApiError`; 500s are logged, not leaked.
- [ ] Body limit, timeout, panic catcher, tracing, and request id layers.
- [ ] Config parsed once into a typed struct; secrets redacted in `Debug`.
- [ ] `query!` macros, `.sqlx/` committed, `prepare --check` in CI.
- [ ] Migrations embedded, forward-compatible, and run at boot.
- [ ] Multi-statement writes in a transaction.
- [ ] `/up` route, SIGTERM handling, and `pool.close()` on shutdown.
- [ ] HTTP tests with `#[sqlx::test]` and `oneshot` (see `testing.md`).
