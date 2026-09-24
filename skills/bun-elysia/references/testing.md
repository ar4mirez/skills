# Testing

Use **`bun test`** for everything: it's Jest-compatible, TypeScript-native,
fast, and needs no extra dependencies. The whole setup below runs in the
verified reference monorepo.

## Contents
- Layers: what to test where
- API tests with Eden (`treaty(app)`)
- The auth stub via preload
- Service tests against a real Postgres
- Mocks, time, and snapshots
- Speed: parallel, isolate, concurrent, shard
- Coverage
- Type-level tests
- The CI gate

## Layers: what to test where

| Layer | How | Share |
|---|---|---|
| **Service** (domain rules) | Call the functions directly against a real test Postgres (one database per worker) | Most |
| **Route/API** (the HTTP contract) | `treaty(app)` in-process: status codes, validation (422), auth (401/403), and response shape; services mocked or real | Some |
| **Plugin/macro** | A tiny `new Elysia().use(plugin).get(...)` app through `treaty` | Some |
| **Jobs** | Call the handler function with a fake job; assert idempotency (run twice) | Some |
| **End to end** | A few critical flows through the real stack (Playwright for web), in CI only | Few |

Don't test Elysia's own validation behavior for every field. Test *your*
rules, plus one 422 per route to prove the schema is attached.

## API tests with Eden (`treaty(app)`)

`assets/module.test.ts`:

```ts
import { describe, expect, it, mock } from 'bun:test'
import { treaty } from '@elysia/eden'

mock.module('./service', () => ({
  findInvoice: async () => invoice,
  createInvoice: async (_: string, input: { number: string }) =>
    input.number === 'DUP' ? { ok: false, error: 'duplicate_number', message: '...' } : { ok: true, value: { ...invoice, number: input.number } },
}))
const { app } = await import('../../app')      // import AFTER mock.module
const api = treaty(app)                        // in-process: no network, fully typed

it('returns 409 for a duplicate number', async () => {
  const { error } = await api.billing.invoices.post({ number: 'DUP', totalCents: 500 }, { headers })
  expect(error?.status).toBe(409)
})
```

- Passing the **instance** to `treaty` calls `app.handle` directly, so tests
  are fast and type-safe. A route or schema change breaks the test at compile
  time.
- For raw HTTP details (headers, cookies, content types), use
  `app.handle(new Request('http://localhost/billing/invoices', { ... }))`.
  The URL must be absolute.
- **Import the app after `mock.module(...)`,** because mocks apply to later
  imports. That's why the reference test uses a dynamic `await import`.

## The auth stub via preload

`assets/test-setup.ts` (registered in `bunfig.toml` `[test].preload`)
replaces `src/plugins/auth` with a header-driven stub. It has the same plugin
name and the same `auth` macro, and resolves `{ user, session, account }`
from `x-account-id`. Modules stay unchanged. In tests, pass
`{ headers: { 'x-account-id': 'acct_1' } }` to act as that account, or omit
it to assert a 401.

Keep one real-auth integration test (sign up, sign in, call a protected
route) against the real Better Auth handler and a test database.

## Service tests against a real Postgres

- **Don't mock Drizzle.** Query behavior (constraints, conflicts, tenant
  scoping) is the point of the test.
- Give each parallel worker its own database:
  `acme_test_${process.env.BUN_TEST_WORKER_ID ?? '1'}`. A preload can create
  it from a template database, run migrations once, and truncate tables
  between files.
- Wrap each test in a transaction that rolls back, or truncate the tables it
  touched in `afterEach`. Either way, keep tests independent: `--parallel`
  implies `--isolate`.
- CI provides Postgres as a service container (`assets/github-ci.yml`).

## Mocks, time, and snapshots

- Use `mock()` or `spyOn()` for functions, and `mock.module(path, factory)`
  for whole modules (services, external clients such as Stripe or email
  providers).
- Freeze time with `setSystemTime(new Date('2026-10-01'))`, or use
  `jest.useFakeTimers()` (supported in 1.4).
- Use snapshots (`toMatchSnapshot`, or `toMatchInlineSnapshot`) only for
  stable, reviewed output such as OpenAPI JSON or email HTML. Never snapshot
  whole API responses that contain ids or timestamps.

## Speed: parallel, isolate, concurrent, shard

```bash
bun test --parallel                     # files across CPU cores (implies --isolate)
bun test --parallel --no-isolate        # faster for many tiny files that don't leak state
bun test --concurrent                   # async tests within a file overlap (I/O-bound)
bun test --changed                      # only files affected by changes (local loop)
bun test --shard=1/4 --timings=.bun-test-timings.json   # CI fan-out, balanced by duration
```

Workers get `BUN_TEST_WORKER_ID`, so use it for per-worker databases and
ports. Preloads run in each worker.

## Coverage

`bunfig.toml` (see `assets/bunfig.toml`):

```toml
[test]
coverage = true
coverageThreshold = { lines = 0.8, functions = 0.8 }
coverageSkipTestFiles = true
```

`bun test` **exits 1** when coverage falls below the threshold. This was
verified, so thresholds really gate CI. Aim coverage at services and
modules; skip `migrations/` and `scripts/`.

## Type-level tests

`tsc --noEmit` over test files *is* the contract test between server and
clients, and `bun run typecheck` runs it in CI. When a route's schema changes,
every Eden call in web, mobile, and tests that no longer fits fails the
build. No extra tooling is needed.

## The CI gate

`assets/github-ci.yml` runs, with zero warnings allowed:
1. `bun install --frozen-lockfile`
2. `bunx biome ci .` (lint plus format)
3. `bun run typecheck` (`tsc --noEmit` in each workspace)
4. `bun audit --audit-level=high`
5. Migrations applied to the CI Postgres
6. `bun test --parallel --coverage` (thresholds enforced)
7. `bun run --filter @acme/api build` (the binary compiles)

Add `bun scripts/audit.ts . --fail-on high` as a step to keep architecture
boundaries from regressing.
