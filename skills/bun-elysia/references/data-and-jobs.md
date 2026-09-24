# Data and background jobs

## Contents
- Drizzle on Bun SQL
- Schema conventions
- Queries and transactions
- Migrations
- Drizzle ↔ TypeBox
- PgBouncer and connection sizing
- Jobs with pg-boss
- Cron
- Redis, S3, and other Bun built-ins
- SQLite

## Drizzle on Bun SQL

`assets/db-client.ts`:

```ts
import { SQL } from 'bun'
import { drizzle } from 'drizzle-orm/bun-sql'
import * as schema from './schema'

const client = new SQL({ url: env.DATABASE_URL, max: 10, prepare: env.DATABASE_PREPARE })
export const db = drizzle({ client, schema, casing: 'snake_case' })
export type Db = typeof db
export type Tx = Parameters<Parameters<Db['transaction']>[0]>[0]
```

- **Bun SQL** is Bun's native Postgres, MySQL, and SQLite client: a pool,
  prepared statements, and pipelining, with no `pg` dependency.
  `drizzle-orm/bun-sql` is the driver.
- Pool size: `max` per process ≈ the CPU cores' worth of concurrency the
  database can handle, divided across all processes (see PgBouncer below).
- **One `db` per process,** imported by services. Never create clients per
  request.

## Schema conventions

`assets/db-schema.ts`:
- Use **one file per domain** (`schema/billing.ts`), re-exported from
  `schema/index.ts`. Table names carry the domain prefix
  (`billing_invoices`).
- Primary keys are `uuid().defaultRandom()`. Use UUIDv7 via
  `$defaultFn(() => Bun.randomUUIDv7())` when index locality matters.
- **Constraints:**
  - `notNull()` on everything required;
  - foreign keys (`.references(() => accounts.id, { onDelete: 'cascade' })`);
  - unique indexes that match business rules (`[accountId, number]`);
  - `check()` constraints for invariants;
  - an index on every foreign key and every filter or sort column.
- Store money as integer cents, time as `timestamp({ withTimezone: true })`,
  and enums as `pgEnum` (or text with a check constraint).
- Derive types: `typeof invoices.$inferSelect` and `$inferInsert`.

## Queries and transactions

- **Always scope by tenant:** `where(and(eq(t.accountId, accountId), ...))`.
  Put the tenant id in every composite index, first.
- Select explicit columns for responses. Use `returning(columns)` on writes.
- **Relational queries** (`db.query.invoices.findMany({ with: { lineItems:
  true } })`) are for reads with relations. They issue a bounded number of
  queries, never N+1.
- **Upserts and idempotency:** `onConflictDoNothing` or
  `onConflictDoUpdate` on the unique index (as in the billing module's
  `createInvoice`).
- **Transactions:**
  ```ts
  await db.transaction(async (tx) => {
    const [invoice] = await tx.insert(schema.invoices).values(input).returning()
    await tx.insert(schema.invoiceEvents).values({ invoiceId: invoice!.id, type: 'created' })
  })
  ```
  Keep transactions short, with no network calls inside. Enqueue jobs *after*
  commit, or enqueue inside the same transaction with pg-boss's Drizzle
  adapter when the job must exist only if the write commits.
- Pagination: use keyset (`where(gt(t.id, cursor)).orderBy(t.id).limit(50)`)
  for lists that grow. Offset is fine only for small, admin-only tables.

## Migrations

```bash
bun run --filter @acme/db drizzle-kit generate   # SQL from schema diffs, commit the output
bun run --filter @acme/db drizzle-kit migrate    # apply, against DATABASE_DIRECT_URL
bun run --filter @acme/db drizzle-kit check      # CI: snapshots consistent
```

Add these as scripts in `packages/db/package.json` (`db:generate`,
`db:migrate`, `db:check`).

- **Always generate and commit migrations.** Never run `drizzle-kit push`
  against shared environments, since it's only for throwaway local
  databases.
- **Zero-downtime rules** apply, as in any Postgres app:
  - add columns as nullable or with a default first;
  - backfill in a job;
  - add constraints `NOT VALID`, then validate them;
  - create indexes concurrently (hand-edit the generated SQL: `CREATE INDEX
    CONCURRENTLY`, in its own migration);
  - rename or drop in a later deploy, after code stops using the column.
- **Apply migrations before the new code starts,** from CI or a one-off
  container, over a **direct** connection (not PgBouncer).

## Drizzle ↔ TypeBox

- `drizzle-typebox` (`createInsertSchema`, `createSelectSchema`) can seed
  Elysia models from tables. Declare the generated schema as a variable
  *before* using it inside `t.Omit` or `t.Pick`, or you hit "type
  instantiation is excessively deep" errors.
- **Pin one `@sinclair/typebox`** (the catalog plus `overrides`), because
  Elysia and drizzle-typebox must share the same TypeBox symbols.
- Prefer hand-written API models for public contracts. They stay stable when
  the table changes, and generated schemas leak columns. Use generation for
  internal admin CRUD.

## PgBouncer and connection sizing

- Add PgBouncer when `processes × max` approaches Postgres
  `max_connections`, or with many short-lived workers.
- **In transaction pooling mode, set `prepare: false`** on Bun SQL
  (`DATABASE_PREPARE=false`), unless PgBouncer ≥ 1.21 is configured for
  protocol-level prepared statements. Avoid session features: `SET` without
  `LOCAL`, session advisory locks, and `LISTEN` through PgBouncer.
- Migrations and pg-boss's `LISTEN/NOTIFY` should use the direct URL.
- Size it so PgBouncer's `default_pool_size` ≈ what Postgres runs
  concurrently (about 2–4× cores). App pools can be larger, because they wait
  on PgBouncer instead of Postgres.

## Jobs with pg-boss

`assets/queue.ts`, `assets/module-jobs.ts`, and `assets/worker.ts`:

```ts
// shared/queue.ts
export const queue = new PgBoss({ connectionString: env.DATABASE_URL, schema: 'pgboss' })

// modules/billing/jobs.ts
export const enqueueSendInvoice = (data: SendInvoice) =>
  queue.send(BillingJobs.sendInvoice, data, { retryLimit: 5, retryBackoff: true, singletonKey: data.invoiceId })

export async function registerBillingWorkers() {
  await queue.createQueue(BillingJobs.sendInvoice)
  await queue.work<SendInvoice>(BillingJobs.sendInvoice, async ([job]) => { /* idempotent */ })
  await queue.schedule('billing.nightly-overdue', '0 3 * * *', {}, { tz: 'UTC' })
}
```

- **Why pg-boss:** Postgres is already there. It uses `SKIP LOCKED` for
  concurrent workers, and provides retries with backoff, dead-letter queues,
  priorities, singleton and debounce keys, and cron. You don't need Redis
  until you've measured a need for it.
- **Job names** are `<module>.<verb-noun>`. Each module owns its jobs in
  `jobs.ts` and exposes `enqueue*` plus `register*Workers` through
  `public.ts`.
- **Payloads** carry ids, never full records, and are small and serializable.
  **Handlers are idempotent**: they check state first, because jobs can run
  twice.
- **Enqueue after the domain write succeeds.** For "only if committed"
  semantics, use pg-boss's Drizzle transaction adapter to send inside `tx`.
- **The worker is a separate process** (`src/worker.ts` → the compiled
  `./worker` binary → the Kamal `worker` role). It shuts down gracefully on
  SIGTERM within about 25 seconds. Non-proxied roles are stopped with
  `drain_timeout`, 30 seconds by default; proxied web roles get Docker's
  10 seconds.
  Break long work into resumable chunks, or smaller jobs.
- Don't run workers inside the web process in production. Keeping them apart
  isolates CPU spikes and deploys.

## Cron

- **Cluster-wide schedules:** use `queue.schedule(name, cron, data, { tz })`.
  It runs once across all workers.
- `Bun.cron(expr, fn)` runs **in the current process only**, so with three
  containers it runs three times. Use it only for per-process housekeeping
  (flushing a local buffer), or single-instance tools.
- `Bun.cron(path, expr, name)` registers an **OS-level** cron job, which is
  useful for CLIs, not containerized services.

## Redis, S3, and other Bun built-ins

- **`Bun.redis`** (the native client) is for caching, rate-limit counters,
  and cross-process WebSocket pub/sub, once you need them. Don't add Redis
  just for jobs.
- **`Bun.s3`** (native S3/R2 client) handles uploads. Presign URLs on the
  server (`s3.file(key).presign({ method: 'PUT', expiresIn: 300 })`), and let
  clients upload directly.
- **Other built-ins:**
  - `Bun.password.hash`/`verify` (argon2id) if you ever hash outside Better
    Auth;
  - `Bun.randomUUIDv7()`;
  - `Bun.file` and `Bun.write` for file I/O;
  - `Bun.Glob`;
  - `Bun.secrets` for CLI or dev credentials. Use deployment secrets in
    production.

## SQLite

`bun:sqlite` plus `drizzle-orm/bun-sqlite` suits single-node tools,
prototypes, and local-first features. Enable WAL mode, back up continuously
with Litestream, and move to Postgres before running more than one app host.
