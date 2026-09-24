# Eloquent and data

**The rule: the database enforces the truth, Eloquent expresses it, and
strict mode makes mistakes loud.**

## Contents
- Model conventions
- Strict mode (and what it doesn't catch)
- Queries and N+1
- Transactions and locking
- Indexes and constraints (Postgres)
- Migrations, safely
- Big tables and batches
- Money, time, and enums
- Postgres specifics: JSON, full-text, pgvector
- Multi-tenancy

## Model conventions

- Use attributes over properties in new code: `#[Fillable([...])]`,
  `#[Hidden([...])]`, `#[Table('legacy_flights', key: 'flight_id')]`,
  `#[Scope]` on protected scope methods, `#[UsePolicy]`, `#[UseFactory]`.
- Put casts in a `casts()` method: backed enums, `immutable_date`,
  `immutable_datetime`, `encrypted`, `AsCollection`, and custom casts for
  value objects.
- Type relations for Larastan: `/** @return BelongsTo<Account, $this> */`.
- Document columns with `@property` docblocks (or run Boost / IDE helper),
  so Larastan at max knows `$invoice->status` is an `InvoiceStatus`.
- Set defaults in `$attributes` *and* the migration's `->default()`, so a
  new model is valid before it's saved.
- Never `$guarded = []`, `#[Unguarded]`, or `Model::unguard()`.

## Strict mode (and what it doesn't catch)

```php
Model::shouldBeStrict(! $this->app->isProduction());
```

This turns on three guards outside production:
- **`preventLazyLoading`** throws `LazyLoadingViolationException` when a
  relation is lazy-loaded on a model that came from a collection. It
  doesn't throw for a single model fetched alone, which is intended.
- **`preventSilentlyDiscardingAttributes`** throws when `fill()` gets a key
  that isn't fillable, instead of dropping it silently.
- **`preventAccessingMissingAttributes`** throws when you read a column you
  didn't `select()`.

**Don't combine it with `Model::automaticallyEagerLoadRelationships()`.**
Automatic eager loading batches the lazy load for the whole collection, so
the violation never fires and N+1 bugs stay hidden until the batching
guess is wrong. (Verified: with both on, a loop over `$invoice->account`
ran 2 queries and threw nothing; with auto eager loading off, it threw.)
Use auto eager loading only as a stopgap on a legacy app you can't fix
yet.

In production, log violations instead of throwing:
`Model::handleLazyLoadingViolationUsing(fn ($model, $relation) => Log::warning(...))`
with `preventLazyLoading()` on.

## Queries and N+1

- Eager load in the query: `Invoice::with('account')->...`, and use
  `withCount('lines')` / `withSum('lines', 'amount_cents')` instead of
  counting in PHP.
- Use `whereBelongsTo($account)` or `where('account_id', ...)` for tenant
  filters. Use `whereRelation('customer', 'active', true)` over
  `whereHas` with a closure when it's one condition.
- Use `exists()` instead of `count() > 0`, `value('col')` for one column,
  and `pluck()` for lists.
- Aggregate in SQL (`groupBy('status')->selectRaw('status, sum(amount_cents) as total')`),
  never `->get()->groupBy()` over a large set.
- Use `toSql()` / `dumpRawSql()` while debugging, and `->explain()` to read
  plans (look for Seq Scan on big tables).
- Laravel Debugbar or Telescope locally; Pulse and Nightwatch in
  production for slow queries.

## Transactions and locking

- One transaction per action: `DB::transaction(fn () => ..., attempts: 3)`
  retries on deadlock.
- Read-then-write on a row: `->lockForUpdate()->findOrFail($id)` inside the
  transaction. Re-read the model, don't trust the one you were passed.
- **Postgres rejects `FOR UPDATE` with aggregates** ("FOR UPDATE is not
  allowed with aggregate functions"). To generate per-parent sequences,
  lock the parent row, then count or `max()`.
- Prefer atomic updates to read-modify-write:
  `Invoice::whereKey($id)->where('status', 'sent')->update([...])` and check
  the affected-row count; `increment()` for counters.
- Use `Cache::lock('key', 10)->block(5, fn () => ...)` for cross-request
  mutual exclusion that isn't a row.

## Indexes and constraints (Postgres)

- **Index every foreign key.** `foreignId('account_id')->constrained()`
  creates the constraint but **no index on Postgres** (MySQL/InnoDB adds one
  automatically). Write `->index()->constrained()`, or lead a composite
  index with the column. `scripts/laravel_audit.php` flags this.
- Composite indexes match the query: equality columns first, then range or
  sort columns (`['account_id', 'status', 'due_on']`).
- Every uniqueness rule has a unique index (`unique(['account_id', 'number'])`),
  because the validation rule alone races.
- Use `->nullable()` only when null means something. Add check constraints
  for invariants (`DB::statement('ALTER TABLE ... ADD CONSTRAINT ... CHECK (amount_cents > 0)')`).
- Use partial indexes for hot subsets:
  `DB::statement("CREATE INDEX ... ON invoices (due_on) WHERE status = 'sent'")`.

## Migrations, safely

Every deploy runs old code against the new schema for a moment. So:
- **Adding** a nullable column or a column with a default is safe.
- **Renaming or dropping** a column (`renameColumn`, `dropColumn`) breaks the
  running release. Expand/contract instead: add the new column, dual-write,
  backfill in a job, switch reads, deploy, then drop in a later release.
- **Changing a type** (`->change()`) can rewrite and lock the table. Use a new
  column plus a backfill instead.
- **Indexes on big Postgres tables:** create them concurrently in a
  migration with `public $withinTransaction = false;` and
  `DB::statement('CREATE INDEX CONCURRENTLY ...')`.
- Keep migrations schema-only. Data backfills go in jobs using `chunkById`.
- Write `down()` for dev convenience, but in production you roll forward,
  never back.
- `DB::prohibitDestructiveCommands($this->app->isProduction())` blocks
  `migrate:fresh`, `migrate:reset`, and `db:wipe` in production.
- Squash old migrations with `php artisan schema:dump --prune` once they
  slow down fresh installs.

## Big tables and batches

- `chunkById(1000, ...)` for updates while iterating (plain `chunk` skips
  rows when you modify the filter column). Use `lazyById()` for read-only
  streaming with low memory.
- `insert()` / `upsert()` for bulk writes. They skip events and casts, on
  purpose.
- `cursorPaginate()` instead of `OFFSET` for deep pagination.
- Avoid `count()` on huge tables in hot paths: cache it, or show "10,000+".

## Money, time, and enums

- **Money:** integer minor units (`amount_cents`) plus a currency column.
  Format with `Number::currency($cents / 100, in: $currency)`. Never
  floats or `decimal` arithmetic in PHP.
- **Time:** `Date::use(CarbonImmutable::class)` app-wide, `immutable_*`
  casts, UTC in the database, and convert to the user's zone only in
  views. `now()`, never `new DateTime()`, so tests can travel
  (`$this->travelTo(...)`).
- **Enums:** backed string enums cast on the model (`'status' =>
  InvoiceStatus::class`), validated with `Rule::enum(InvoiceStatus::class)`,
  and carrying behavior (`isPayable()`, `label()`). Store them as `string`
  columns, not database enums, which are painful to alter.

## Postgres specifics: JSON, full-text, pgvector

- **JSON:** use `jsonb` (`$table->jsonb('settings')`), cast with
  `AsArrayObject` / `AsCollection`, and query with
  `where('settings->notifications->email', true)`. Add a GIN index when you
  filter on it.
- **Full-text:** `$table->fullText(['title', 'body'])` plus
  `whereFullText([...], $terms)`. It covers most search needs before Scout.
- **Vectors (Laravel 13):** `$table->vector('embedding', dimensions: 1536)->index()`
  (pgvector), embeddings from the AI SDK (`Str::of($text)->toEmbeddings()`),
  and `whereVectorSimilarTo('embedding', $query, minSimilarity: 0.4)`, which
  orders by similarity. Generate embeddings in a queued job, never in the
  request.

## Multi-tenancy

- Default to a **single database, with `account_id` on every tenant table**,
  scoped queries, and policies. It's simple and indexable, and backups and
  migrations stay single.
- A global scope (`#[ScopedBy(AccountScope::class)]`) is acceptable as a
  safety net. Still write the explicit scope in queries and keep policies:
  global scopes silently disappear in `withoutGlobalScopes()`, raw queries,
  and queued jobs with no authenticated user.
- Queued jobs carry the tenant explicitly (the model, or an `account_id`)
  and use `Context::add('account_id', ...)` for logs.
- Database-per-tenant (stancl/tenancy) only for hard isolation or
  compliance requirements. It multiplies every operational task.
