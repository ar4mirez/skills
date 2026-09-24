# Performance, data, and scale

**The rule: measure, then fix the biggest thing.** Rails apps are almost
never slow because of Ruby. They're slow because of queries, missing indexes,
missing caching, or work done in the request that belongs in a job.

## Contents
- Diagnose first
- Queries and N+1
- Indexes and constraints
- Safe migrations
- Caching
- Background jobs at scale
- Runtime: Puma, YJIT, memory
- Scaling the database
- Pagination, counting, and big tables

## Diagnose first

1. **In development:** use `rack-mini-profiler` (SQL count and time per
   request) and the log's `Completed ... ActiveRecord: Xms` line.
2. **In production:** use APM or `Rails.event` structured events plus log
   aggregation. Look at the p95 by endpoint, not averages.
3. **For a query,** run `Model.where(...).explain` (`explain(:analyze)` on
   PostgreSQL) and look for Seq Scan on large tables and bad row estimates.
4. Write the finding down: "`GET /invoices` p95 1.8s: 240 queries (N+1 on
   customer), no index on `invoices.account_id, status`."

## Queries and N+1

- **Make N+1 impossible by default:** set `strict_loading_by_default = true`,
  with `action_on_strict_loading_violation = :raise` in development and test.
  Alternatively, run `prosopite` in test. Fix a violation by preloading in the
  controller or scope, never by disabling it in the view.
- **Loading methods:**
  - `includes`: let Rails decide.
  - `preload`: separate queries.
  - `eager_load`: a JOIN, needed when filtering on the association.
  - `strict_loading`: per query or association.
- **Select less:** `pluck(:id, :name)` for data you won't treat as models,
  `select(:id, :title)` for wide tables, and `exists?` rather than `present?`
  on relations.
- **Counts:** use `size` on loaded associations and `count` for a fresh SQL
  count. Add `counter_cache: true` for displayed counts, and backfill with
  `reset_counters`.
- **Batches:** use `find_each` or `in_batches` for anything over about a
  thousand rows. Use `insert_all` and `upsert_all` for bulk writes, since they
  skip validations and callbacks, deliberately.
- **Aggregations belong in SQL:** `group(:status).sum(:amount)`, not Ruby
  `group_by` over loaded records.

## Indexes and constraints

- Index **every foreign key**: `t.references` does it by default, but check
  `add_column :x_id` migrations. `scripts/rails_audit.rb` flags missing ones.
- Composite indexes should match your query, with equality columns first,
  then range or sort columns: `[:account_id, :status, :created_at]`.
- Every `uniqueness` validation needs a **unique index**. The validation alone
  races.
- Use `null: false` and defaults for required columns, foreign keys
  (`foreign_key: true`), and check constraints (`add_check_constraint`) for
  invariants.
- On PostgreSQL, use partial indexes for hot subsets:
  `add_index :invoices, :due_on, where: "status = 'sent'"`.

## Safe migrations (zero downtime)

Use `strong_migrations` for PostgreSQL and MySQL apps. The patterns:
- **Add an index concurrently:** `disable_ddl_transaction!` plus
  `add_index ..., algorithm: :concurrently`.
- **Add a column with a default:** this is fine on modern PostgreSQL. For a
  NOT NULL constraint on a big table, add a check constraint `NOT VALID`,
  validate it, then change null.
- **Rename or remove a column:** first `self.ignored_columns += ["old"]` and
  deploy, then drop it in a later deploy. Never rename in place on a live
  app.
- **Change a column type:** add a new column, dual-write, backfill in batches
  (in a job, not the migration), switch reads, then drop the old one.
- **Backfills belong in jobs or `bin/rails runner` scripts,** using
  `in_batches`. Keep migrations fast and schema-only.
- Migrations must be reversible (`change`, or `up`/`down`). Don't reference
  app models inside them; define a lightweight model in the migration if you
  must.

## Caching

In order of payoff:
1. **HTTP caching:** `fresh_when @invoice` or `stale?` for show pages and
   APIs, which gives ETags and 304s for free.
2. **Fragment caching:** `<% cache invoice do %>`, and collection caching with
   `render partial: "invoice", collection: @invoices, cached: true`. Use
   `touch: true` on `belongs_to` for Russian-doll invalidation.
3. **Low-level caching:** `Rails.cache.fetch([account, :aging_report],
   expires_in: 1.hour) { ... }`, for expensive computations. Key on the
   records' `cache_key_with_version`.
4. **Solid Cache** is the store. Its disk-backed database cache gives large,
   cheap caches, which means long TTLs are fine. Redis or Memcached only if
   already operated.

Don't cache before fixing the queries. The cache hides the problem until it
misses.

## Background jobs at scale

- Keep request time under about 200 ms of real work. Push emails, webhooks,
  exports, image processing, and third-party calls to jobs.
- **Solid Queue:**
  - Run it in Puma (`SOLID_QUEUE_IN_PUMA`) for small apps, and as a dedicated
    `bin/jobs` role in Kamal once volume grows.
  - Configure workers, threads, and queues in `config/queue.yml`.
  - Use separate queues by latency class, such as `real_time`, `default`,
    and `low`, not by job type.
  - Use concurrency controls (`limits_concurrency to: 1, key: ->(account) {
    account }`) instead of locks.
  - Set recurring tasks in `config/recurring.yml`.
- **Sidekiq** is justified only for very high throughput (thousands of
  jobs/sec), or when Redis is already core infrastructure.
- **Idempotency:** jobs can run twice. Guard with state checks
  (`return if invoice.reminded?`) or unique keys.
- **Long jobs:** use `ActiveJob::Continuable` steps with cursors, so Kamal's
  30-second shutdown doesn't restart work.

## Runtime: Puma, YJIT, memory

- **Puma:** size threads (`RAILS_MAX_THREADS`, default 3) by I/O profile, and
  workers (`WEB_CONCURRENCY`) at about one per core. Make the database pool at
  least the thread count, plus Solid Queue threads if it runs in-process.
- **YJIT** is on via Rails defaults with Ruby 3.3+/4.0, and typically gives a
  15–30% speedup. It uses more memory, so budget for it. ZJIT isn't
  production-ready yet.
- **Memory:** watch for bloat from loading huge relations (`find_each`),
  string building in loops, and gems that monkey-patch. Consider jemalloc in
  the Docker image (`LD_PRELOAD`). The Rails 8 Dockerfile supports it.
- **Boot time:** Bootsnap is on by default. Don't load at require time what can
  be autoloaded.

## Scaling the database

Go in order:
1. Indexes and query fixes.
2. Caching.
3. A bigger instance.
4. Read replicas via multiple databases:
   `connects_to database: { writing: :primary, reading: :replica }` with
   automatic role switching (`config.active_record.database_selector`).
5. Separate databases for Solid Queue, Cache, and Cable (the Rails 8
   default), so that load is isolated.
6. Partitioning or archiving cold data.
7. Horizontal sharding (`connects_to shards:`) as a last resort, with a clear
   shard key (the tenant).

**SQLite in production** is valid for a single server: WAL mode (the default),
Litestream for continuous backup, and Solid Queue, Cache, and Cable on
separate SQLite files. Move to PostgreSQL when you need more than one app
server or heavy concurrent writes.

## Pagination, counting, and big tables

- Use `pagy`. For large or infinite lists, use keyset pagination (`pagy`
  keyset) instead of `OFFSET`.
- Avoid `COUNT(*)` on huge tables in hot paths. Use counter caches, cached
  counts, or "10,000+" approximations.
- Put large blobs in Active Storage (S3 or R2 with direct uploads), never in
  the database. Generate variants lazily and serve them through a CDN.
