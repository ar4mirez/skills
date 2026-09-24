# Performance and scale

**The rule: measure, then fix the biggest thing.** Laravel apps are almost
never slow because of PHP. They're slow because of queries, missing
indexes, missing caching, work in the request that belongs in a queue, or
boot overhead that `optimize`, OPcache, and Octane remove.

## Contents
- Diagnose first
- The cheap wins (every app)
- Queries
- Caching
- Octane + FrankenPHP
- Octane safety rules
- Scaling out
- Frontend payloads

## Diagnose first

1. **Locally:** Debugbar or Telescope (query count and time per request),
   and `DB::listen` for ad-hoc checks. Strict mode already throws on N+1.
2. **In production:** Nightwatch or Pulse (slow requests, slow queries,
   slow jobs, and the endpoints behind them), plus your APM. Look at p95
   by route, not averages.
3. **For a query:** `->explain()` (on Postgres, `EXPLAIN ANALYZE` in psql),
   looking for Seq Scan on large tables and bad row estimates.
4. Write down the finding before fixing it: "`GET /invoices` p95 1.4 s:
   180 queries (N+1 on account), no index on `(account_id, status)`."

## The cheap wins (every app)

- **`php artisan optimize` at boot in production.** It caches config,
  routes, events, and views; the entrypoint in `assets/docker-entrypoint.sh`
  runs it with the real runtime env.
- **OPcache on, with `validate_timestamps=0`** in containers (the code
  never changes inside a running image), plus a big realpath cache. See
  `assets/php-production.ini`.
- **`composer dump-autoload --classmap-authoritative --no-dev`** in the
  image.
- **Queue anything slow** (see `queues-and-realtime.md`).
- **Database indexes** on every FK and every filter or sort column.

## Queries

See `eloquent-and-data.md`. The usual suspects:
- N+1: eager load with `with()` in the query, and `withCount()` /
  `withSum()` for aggregates.
- Over-fetching: `select()` the columns a list needs, and `paginate()` or
  `cursorPaginate()` always.
- Aggregates in PHP over large sets: move them into SQL.
- Missing composite indexes for the actual `where` + `orderBy`.
- Chatty caches or sessions on the database under heavy load: move them to
  Redis once measured.

## Caching

In order of payoff:
1. **HTTP caching** for public or shared responses: `Cache-Control`,
   ETags (`$response->setEtag()` / `isNotModified()`), and Cloudflare cache
   rules for assets and public pages.
2. **Query/result caching** with keys you can reason about:
   `Cache::remember("account:{$id}:aging", now()->addMinutes(10), fn () => ...)`.
3. **`Cache::flexible($key, [300, 900], fn () => ...)`**, stale-while-revalidate:
   fresh for 5 minutes, then served stale for up to 15 while it refreshes
   in the background. It's the right default for dashboards.
4. **`Cache::touch($key, 3600)`** (Laravel 13) extends a TTL without
   re-fetching the value.
5. **`once(fn () => ...)`** memoizes within a request or object lifetime,
   and `Cache::memo()` memoizes cache reads within a request.

Invalidate by versioned keys (`"account:{$id}:v{$version}:aging"`) or by
tagging (Redis only). Don't cache before fixing the query: the cache hides
the problem until it misses.

## Octane + FrankenPHP

Octane boots the app once per worker and serves many requests from memory,
cutting framework boot (often most of a simple request's time).
FrankenPHP is the default server: a single Go binary (Caddy) with PHP
embedded, HTTP/2 and 3, early hints, and compression.

- Start: `php artisan octane:frankenphp --host=0.0.0.0 --port=8080 --max-requests=1000`
  (`--workers=auto` by default, one per CPU).
- **`--max-requests`** recycles workers to contain slow leaks. Keep it.
- Behind Kamal/Cloudflare, TLS terminates upstream, so the "HTTP/2 skipped
  because it requires TLS" warning is expected.
- `octane:install --server=frankenphp` downloads a ~160 MB `frankenphp`
  binary into the project for local use. Keep it out of git and the
  image; the official Docker image already includes FrankenPHP.
- Octane extras: `Octane::concurrently([...])` for parallel work in a
  request, the Octane cache and tables (Swoole only), and ticks.

## Octane safety rules

The app, the container, and service providers live across requests, so:
- **No static state holding request data.** `static array $cache` in a
  service grows forever and leaks between users.
  `scripts/laravel_audit.php` flags static properties when Octane is
  installed.
- **Don't inject the request, the authenticated user, or config values into
  singletons' constructors.** The first request's values get reused.
  Resolve per call (`request()` inside the method), inject a closure, or
  bind with `$this->app->scoped()`, which resets per request.
- Services registered with `singleton()` must be stateless. Anything
  per-request uses `scoped()` or `Context`.
- Package compatibility: most first-party and major packages are
  Octane-safe. Test anything that keeps static caches.
- Load-test before switching (k6 or `hey`) and watch worker memory over
  thousands of requests.
- If the codebase isn't Octane-safe yet, ship PHP-FPM + nginx first (or
  FrankenPHP in classic, non-worker mode), then migrate.

## Scaling out

Go in this order:
1. Query and index fixes.
2. Caching.
3. Octane.
4. More web containers (stateless: sessions and cache in the database or
   Redis, files on S3 or R2).
5. A bigger Postgres, then read replicas (`'read' => [...], 'write' => [...]`
   in `config/database.php`, with `'sticky' => true` so a user reads their
   own writes).
6. Redis for cache, sessions, and queues (plus Horizon) once the database
   drivers show up in the profile.
7. PgBouncer in transaction mode when connections pile up (many workers
   times many hosts). Laravel turns PDO prepare emulation *off*, so real
   server-side prepared statements are used: either run PgBouncer ≥ 1.21
   with `max_prepared_statements` set, or add
   `'options' => [PDO::ATTR_EMULATE_PREPARES => true]` to the pgsql
   connection. Don't rely on session-level `SET`, advisory locks, or
   `LISTEN/NOTIFY` through it, and run migrations over a direct
   connection.
8. Partitioning or archiving cold data.

## Frontend payloads

- Livewire: keep public properties small (computed properties aren't
  serialized), use `@island` or lazy components for slow parts, and
  `wire:model.live.debounce` rather than per-keystroke requests.
- Inertia: defer expensive props, use partial reloads, and never pass whole
  models.
- Serve built assets with long cache headers (Vite hashes filenames), via
  Cloudflare.
