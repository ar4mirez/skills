# Architecture: the Bun workspace monorepo + Elysia feature modules

This is one repo with deployable apps and shared packages. Every file has
exactly one home and one shape, and types flow from the database schema,
through the API, to every client, with no hand-written duplicates.

## Contents
- Monorepo layout and dependency rules
- Packages: config, db, contracts
- The API app: composition, entrypoints, and shared code
- Module anatomy (controller, model, service, public, jobs, test)
- Results vs. DomainErrors
- Request-dependent code: named plugins and macros
- Cross-module calls
- Naming
- Growing the architecture (keep it simple first)
- Existing codebases

## Monorepo layout and dependency rules

```
acme/
├── package.json            # workspaces + catalog + scripts (assets/root-package.json)
├── bun.lock                # text lockfile, committed
├── bunfig.toml             # isolated linker, test preload, and coverage
├── biome.json
├── tsconfig.base.json      # strict, bundler resolution, verbatimModuleSyntax
├── apps/
│   ├── api/                # Elysia: the only place with HTTP and business logic
│   │   ├── src/
│   │   │   ├── app.ts      # composes plugins + modules; exports `type App`
│   │   │   ├── index.ts    # server entrypoint: app.listen(env.PORT)
│   │   │   ├── worker.ts   # worker entrypoint: pg-boss consumers
│   │   │   ├── plugins/    # auth.ts, request-context.ts, ... (named Elysia plugins)
│   │   │   ├── shared/     # result.ts, errors.ts, queue.ts (framework-blind helpers)
│   │   │   └── modules/
│   │   │       ├── identity/
│   │   │       ├── billing/
│   │   │       └── communications/
│   │   └── test/setup.ts   # test preload (stubs auth, sets test env)
│   ├── web/                # Next.js or SolidStart; consumes `type App` through Eden
│   └── mobile/             # Expo; consumes `type App` through Eden
└── packages/
    ├── config/             # the TypeBox env schema, parsed once at boot
    ├── db/                 # Drizzle schema (one file per domain), client, migrations
    └── contracts/          # optional: runtime schemas that clients also need
```

The dependency rules, which `scripts/audit.ts` checks:

| From → To | Allowed? |
|---|---|
| `apps/*` → `packages/*` | ✅ via `"@acme/db": "workspace:*"` |
| `packages/*` → `packages/*` | ✅ acyclic (e.g. `db` → `config`) |
| `packages/*` → `apps/*` | ❌ never |
| `apps/web`/`mobile` → `apps/api` | ✅ **only** as a devDependency, and **only** `import type { App }` |
| any client → server runtime code | ❌ never. Server code must not end up in a client bundle |
| `modules/a` → `modules/b/*` | ❌ only `modules/b/public` |

Packages export TypeScript source directly (`"exports": { ".":
"./src/index.ts" }`). Bun and bundlers compile it, and there's no per-package
build step. Each workspace type-checks itself with `tsc --noEmit`. Don't use
project references with declaration emit, because it fails on Eden's inferred
types (TS2883).

## Packages: config, db, contracts

- **`packages/config`** (`assets/env.ts`): one TypeBox schema for every env
  var, parsed with `Value.Default`, `Convert`, and `Errors` at import time.
  Invalid config crashes the process at boot with the full list of problems.
  It exports a typed `env`. Nothing else on the server reads `process.env`.
  Client apps read their public build-time vars (`NEXT_PUBLIC_*`,
  `EXPO_PUBLIC_*`) literally, as those frameworks require.
- **`packages/db`** (`assets/db-client.ts`, `assets/db-schema.ts`):
  - Drizzle schema, one file per domain (`schema/billing.ts`, with tables
    prefixed `billing_`);
  - a Bun SQL client with `drizzle-orm/bun-sql`;
  - `db`, `Db`, and `Tx` types;
  - drizzle-kit config and committed `migrations/`.
  The API modules are its only consumers.
- **`packages/contracts`:** add it *only* when a client needs runtime
  validation (for example, a form using the same rules). Hold
  `@sinclair/typebox` schemas there, pinned to the same 0.34.x version Elysia
  uses. The API models can compose them. Eden already delivers the *types*, so
  most apps never need this package.

## The API app: composition, entrypoints, and shared code

```ts
// apps/api/src/app.ts (assets/app.ts)
export const app = new Elysia()
  .use(openapi({ enabled: env.NODE_ENV !== 'production' }))
  .get('/up', () => 'ok')          // kamal-proxy health check
  .use(billing)                    // each module is a plugin with its own prefix
  .use(identity)

export type App = typeof app       // the ONE export clients consume, as a type
```

- `index.ts` only calls `listen`. `worker.ts` starts pg-boss and registers
  each module's workers through its `public.ts`. Both compile into separate
  binaries.
- `plugins/` holds named, request-dependent plugins: `auth.ts`
  (`assets/auth-plugin.ts`), plus things like request id or tenant context.
- `shared/` holds framework-blind helpers (`result.ts`, `errors.ts`,
  `queue.ts`). Keep it small. If a helper is domain-specific, it belongs in a
  module.

## Module anatomy

`bun scripts/new-module.ts <name>` generates this shape:

```
modules/billing/
├── index.ts        # controller: the Elysia instance (routes, hooks, macros used)
├── model.ts        # t schemas + derived types (single source of truth)
├── service.ts      # business logic: plain exported functions, no Elysia
├── public.ts       # what other modules and entrypoints may import
├── jobs.ts         # optional: job names, enqueue helpers, worker registration
└── billing.test.ts # treaty(app) tests (plus service tests against a real db)
```

### model.ts

```ts
export const BillingModel = {
  invoiceParams: t.Object({ id: t.String({ format: 'uuid' }) }),
  createInvoiceBody: t.Object({ number: t.String({ minLength: 1, maxLength: 32 }), totalCents: t.Integer({ minimum: 0 }) }),
  invoice: t.Object({ id: t.String(), number: t.String(), status: t.UnionEnum(['draft', 'sent', 'paid', 'void']), totalCents: t.Integer() }),
  problem: t.Object({ error: t.String(), message: t.String() }),
} as const
export type BillingModel = { [K in keyof typeof BillingModel]: UnwrapSchema<(typeof BillingModel)[K]> }
```

- Group schemas in one exported `const` object. Derive types from it; never
  declare a parallel `interface`.
- Response schemas are part of the contract, so define one per status the
  route can return.
- Derive database-backed shapes from Drizzle (`$inferSelect`) or
  `drizzle-typebox` when that helps, keeping one TypeBox version (see
  `data-and-jobs.md`).

### service.ts

```ts
// Framework-blind: no Elysia imports. Import as: import * as BillingService from './service'
export async function findInvoice(accountId: string, id: string): Promise<Invoice> {
  const [invoice] = await db.select(invoiceColumns).from(schema.invoices)
    .where(and(eq(schema.invoices.accountId, accountId), eq(schema.invoices.id, id))).limit(1)
  if (!invoice) throw new NotFoundError('Invoice')
  return invoice
}

export async function createInvoice(accountId: string, input: BillingModel['createInvoiceBody']):
  Promise<Result<Invoice, 'duplicate_number'>> {
  const [invoice] = await db.insert(schema.invoices).values({ accountId, ...input })
    .onConflictDoNothing({ target: [schema.invoices.accountId, schema.invoices.number] })
    .returning(invoiceColumns)
  return invoice ? ok(invoice) : fail('duplicate_number', `Invoice ${input.number} already exists`)
}
```

Rules:
- Use plain exported `async function`s. Don't write classes. Biome's
  `noStaticOnlyClass` flags the `abstract class` + `static` style, and
  functions are simpler to mock and tree-shake.
- Arguments are plain values: ids, validated bodies, the tenant id. Never pass
  the Elysia context, `request`, or cookies.
- **Scope every query by tenant.** The tenant id is the first argument.
- Multi-step writes use `db.transaction(async (tx) => ...)`, and enqueue jobs
  after the write succeeds (see `data-and-jobs.md`).
- Select explicit columns (`invoiceColumns`) so secrets and internals never
  reach responses. Response schemas also strip unknown fields.

### index.ts (controller)

```ts
export const billing = new Elysia({ name: 'module.billing', prefix: '/billing' })
  .use(auth)
  .get('/invoices/:id', ({ params, account }) => BillingService.findInvoice(account.id, params.id), {
    auth: true, params: BillingModel.invoiceParams, response: { 200: BillingModel.invoice },
  })
  .post('/invoices', async ({ body, account, status }) => {
    const result = await BillingService.createInvoice(account.id, body)
    if (!result.ok) return status(409, { error: result.error, message: result.message })
    return status(201, result.value)
  }, { auth: true, body: BillingModel.createInvoiceBody, response: { 201: BillingModel.invoice, 409: BillingModel.problem } })
```

Rules:
- Give each module a `name` (for deduplication and tracing) and a `prefix`.
- Every route declares `params`, `query`, and `body` schemas as applicable,
  plus a `response` map. Protected routes use the `auth: true` macro.
- Handlers are a single expression, or a few lines that call **one** service
  function and map its Result to `status(...)`. Put no logic in handlers.
- REST shape: nouns in paths, and HTTP verbs as the actions. For an action
  that isn't CRUD, create a sub-resource (`POST /invoices/:id/delivery`), not
  a verb path (`/invoices/:id/send`).

### public.ts

```ts
export { enqueueSendInvoice, registerBillingWorkers } from './jobs'
export type { BillingModel } from './model'
export { createInvoice, findInvoice } from './service'
```

This is the module's contract with the rest of the app. Keep it small. If
another module wants something that isn't here, add it deliberately, or
reconsider which module owns the logic.

## Results vs. DomainErrors

| Situation | Mechanism | Why |
|---|---|---|
| An expected business outcome the caller must handle (duplicate, insufficient funds, invalid state transition) | `return fail('duplicate_number', msg)`, where `Result<T, E>` is a discriminated union (`assets/result.ts`) | The compiler forces the controller to handle it, and it maps to a typed `status(409, ...)` that Eden narrows |
| An exceptional or cross-cutting case (not found, forbidden, broken invariant) | `throw new NotFoundError('Invoice')`, extending `DomainError` with a `status` (`assets/errors.ts`) | Elysia uses a thrown error's `status` property automatically, so services stay framework-blind |
| A programmer error, or infrastructure failure (DB down) | Let it throw | Elysia returns 500, and Sentry/OTel capture it |

Never `throw status(...)` from a service, because that imports Elysia into the
domain. Controllers own the mapping to HTTP.

## Request-dependent code: named plugins and macros

```ts
export const auth = new Elysia({ name: 'plugin.auth' })
  .mount('/auth', authServer.handler)
  .macro({
    auth: {
      async resolve({ status, request: { headers } }) {
        const session = await authServer.api.getSession({ headers })
        if (!session) return status(401, 'Unauthorized')
        return { user: session.user, session: session.session, account: { id: session.user.id } }
      },
    },
  })
```

- **`name` makes a plugin a singleton.** Every module can
  `.use(auth)` without re-running it.
- **Macros** (`auth: true`, `role: 'admin'`) are the idiomatic way to add
  per-route behavior. They carry types (routes see `user`, `account`) and
  read like configuration.
- `decorate` is only for request-dependent values. Don't decorate services
  or the db: import them.
- Tests replace the auth plugin through a preload (`assets/test-setup.ts`
  plus `bunfig.toml` `[test].preload`), so modules stay unchanged.

## Cross-module calls

- A module imports another module only through `../other/public`.
- **Module dependencies are acyclic,** and `scripts/audit.ts` flags cycles.
  When billing notifies communications, billing depends on communications
  (it enqueues the job). Communications must **not** call back into billing
  to fetch the invoice. Put everything it needs in the job payload (email,
  number, amount), or have it depend on a shared, lower-level module instead.
- Prefer **async** collaboration for side effects. Billing enqueues a job, and
  communications' worker sends the email. The two modules don't block each
  other or share transactions.
- Synchronous reads across modules (billing needs a user's plan) call the
  other module's public function. If two modules constantly need each other's
  internals, the boundary is wrong: merge them, or move the shared concept
  into one of them.
- There's no event bus, no DI container, and no repository layer. Drizzle is
  the query layer, and modules are the units of ownership.

## Naming

- **Modules and prefixes:** domain nouns in kebab-case (`billing`,
  `team-invites`, mounted at `/team-invites`). The plugin name is
  `module.<name>`.
- **Controllers:** the camelCase domain name (`billing`, `teamInvites`).
  **Models:** `PascalModel` (`BillingModel`). **Services:** verbs
  (`createInvoice`, `findInvoice`, `cancelSubscription`).
- **Result error codes:** snake_case literals (`'duplicate_number'`), typed
  in the return signature.
- **Tables:** `<domain>_<plural>` (`billing_invoices`), columns in snake_case
  (Drizzle `casing: 'snake_case'`), and TypeScript names in camelCase.

## Growing the architecture (keep it simple first)

1. **Day one:** `apps/api` plus `packages/config` and `packages/db`, one or
   two modules, and Eden into `apps/web`.
2. **New capability:** a new module. Add a new package only when two apps
   need the same *runtime* code.
3. **Heavy background work:** the same codebase, in a separate `worker`
   process (a Kamal role). Split a separate service out only for a genuinely
   different scaling or compliance profile, justified in writing.
4. **CI too slow:** use `bun test --shard` and `--timings` first, and
   Turborepo or Nx remote caching only if that's not enough.

Don't adopt these early: microservices, GraphQL gateways, CQRS or event
sourcing, DI frameworks, repository or unit-of-work layers, or tRPC next to
Eden.

## Existing codebases

- **Follow the established structure** (for example, a flat `routes/` folder,
  or Zod schemas), and migrate toward these defaults module by module.
- **Incremental steps that pay off fastest:**
  1. `strict: true`.
  2. Aligned `elysia` and Eden versions through `catalog:`.
  3. Services moved out of handlers.
  4. `public.ts` boundaries.
  5. `response` schemas.
  6. Compiled binaries.
