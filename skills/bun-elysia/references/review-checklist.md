# Bun + Elysia code review checklist

Report findings **ranked by severity**. Give each one a file and line, what's
wrong, why it matters, and the concrete fix (code). Run `bun scripts/audit.ts
<repo>` first for the structural checks it can detect.

## Critical: security and data

- [ ] A query not scoped by tenant (a missing `accountId` condition), which
      means cross-tenant data exposure.
- [ ] A client app importing server code at runtime (`import { app } from
      '@acme/api'`) instead of `import type { App }`, which leaks the server
      and secrets into the bundle.
- [ ] A route that accepts input without a schema, or returns rows without a
      `response` schema or column selection, so fields like `passwordHash` or
      internal ids leak.
- [ ] Hand-rolled auth or session crypto, or deprecated Lucia. Use Better
      Auth plus the `auth` macro.
- [ ] Secrets read ad hoc from `process.env` or hard-coded, or public env
      prefixes used for secrets.
- [ ] CORS set to `origin: true` together with `credentials: true`.
- [ ] Raw SQL built by string concatenation, instead of Bun SQL or Drizzle
      tagged templates and parameters.

## High: correctness and type integrity

- [ ] Handlers that take the whole `Context`, controller classes, or
      unchained `app.get(...)` statements, all of which lose inference.
- [ ] A service that imports Elysia or throws `status(...)`. It should return
      a `Result`, or throw a `DomainError` with `status`.
- [ ] An expected failure thrown as a generic `Error` (a 500) instead of a
      `Result` mapped to `status(4xx)`, and declared in `response`.
- [ ] Lifecycle hooks registered *after* the routes they should cover, or a
      `global` scope used for module-specific logic.
- [ ] Plugins without a `name` that are `.use()`d in several modules, so
      they run repeatedly.
- [ ] Version drift in `elysia`, `@elysia/eden`, or `@sinclair/typebox`
      across workspaces, or `strict` off anywhere.
- [ ] Non-idempotent job handlers, jobs carrying full records instead of ids,
      or enqueueing before the write commits.
- [ ] Destructive or locking migrations (renames or drops in the same deploy
      as the code change, non-concurrent indexes on large tables), or
      `drizzle-kit push` against a shared database.

## Medium: design and boundaries

- [ ] A cross-module import that bypasses `public.ts`, a package depending on
      an app, or an app depending on another app (other than the API types).
- [ ] Business logic in handlers, or HTTP concerns (headers, cookies,
      status codes) in services.
- [ ] Hand-declared interfaces duplicating a `t` schema. Derive types with
      `UnwrapSchema` or `.static`.
- [ ] `decorate`/`state` used for dependencies (the db, services) instead of
      imports.
- [ ] A new dependency where a Bun built-in exists: `pg` vs Bun SQL,
      `bcrypt` vs `Bun.password`, `node-cron` vs pg-boss schedules, `jest` or
      `vitest` vs `bun test`, `dotenv` vs Bun's env loading, ESLint and
      Prettier vs Biome.
- [ ] `Bun.cron` used for cluster-wide schedules (it runs once per process).
- [ ] Verb paths (`/invoices/:id/send`) instead of sub-resources
      (`POST /invoices/:id/delivery`).

## Low: tests, style, deploy

- [ ] Behavior changes without tests at the right layer (service, API via
      `treaty(app)`, job), or mocked Drizzle in service tests.
- [ ] `sleep` or `setTimeout` waits in tests, or tests that share state and
      so break under `--parallel`.
- [ ] `any`, non-null assertions (`!`), or `@ts-ignore` without a comment
      explaining why.
- [ ] A Dockerfile running `.ts` in the final stage, Alpine without a musl
      target, `--bytecode` without `--format=esm`, or a root user.
- [ ] Biome violations. Let `biome ci` report these; don't hand-review
      style.
