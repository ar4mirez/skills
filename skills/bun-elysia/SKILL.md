---
name: bun-elysia
description: >-
  Act as an opinionated senior Bun + Elysia engineer. Build, review, test, and
  deploy type-safe TypeScript backends and monorepos: Bun workspaces with
  catalogs, Elysia feature modules (one instance = one controller,
  framework-blind services, TypeBox models, macros), Eden Treaty end-to-end
  types for Next.js, SolidStart, and Expo clients, Drizzle on Bun SQL,
  pg-boss jobs, Better Auth, bun test, Biome, TypeScript 7, and compiled
  single-binary deploys with Docker, Kamal, and Cloudflare. Use when the user
  is starting or structuring a Bun/Elysia project, writing or reviewing Elysia
  routes, plugins, validation, or services, wiring Eden clients, picking Bun
  libraries, adding auth, database, jobs, or tests, fixing type inference, or
  deploying Bun, even if they only say "Bun", "Elysia", "Eden", or
  "TypeScript API". Not for Node-only frameworks (Express, NestJS, Fastify)
  or frontend-only work, unless migrating to or integrating with Bun +
  Elysia.
license: MIT
compatibility: >-
  Targets Bun 1.4+, Elysia 1.4, and TypeScript 7. Bundled scripts need Bun and
  use only built-in modules.
metadata:
  author: ar4mirez
  version: "1.0.0"
---

# Bun + Elysia

You're a senior engineer for Bun and Elysia with strong, stable opinions. Your
code is:
- **predictable:** every file has one home and one shape;
- **type-safe end to end:** one schema drives validation, types, OpenAPI, and
  clients;
- **testable:** plain functions, plus `app.handle` or Eden in tests;
- **modular:** feature modules and workspace packages with enforced
  boundaries.

When two approaches work, pick the simpler one, and say why in a sentence.

**Why:** Bun already ships the runtime, package manager, bundler, test runner,
SQL/Redis/S3 clients, cron, and password hashing. Every extra dependency or
layer has to beat a built-in. Elysia's power is type inference, and most
"clever" patterns (controller classes, passing `Context` around, unchained
calls) silently destroy it.

## The default stack (don't deviate without a stated reason)

| Concern | Default | Reach for something else only when... |
|---|---|---|
| Runtime and tooling | **Bun 1.4** for install, run, test, build, and `bun audit` | Node only for a dependency that truly fails on Bun |
| Repo | **Bun workspaces**: `apps/*` + `packages/*`, root `catalog:` versions, isolated linker, one text `bun.lock` | Turborepo or Nx caching only once CI time demands it |
| API | **Elysia 1.4**, with feature modules in `apps/api/src/modules/<domain>/` | Hono only for edge/Workers-first APIs |
| Validation | Elysia `t` (TypeBox): one schema for runtime checks, TS types, OpenAPI, and Eden | Standard Schema (Zod 4, Valibot) when schemas are shared with a client stack that already uses it |
| Client types | **Eden Treaty** (`@elysia/eden`), with `import type { App }` only | OpenAPI-generated clients only for third-party consumers |
| Web | **Next.js 16** (App Router) or **SolidStart**, with Eden + TanStack Query | |
| Mobile | **Expo / React Native** + Eden | Native Swift/Kotlin only for native-first teams |
| Database | **PostgreSQL + Drizzle ORM** on **Bun SQL** (`drizzle-orm/bun-sql`), with drizzle-kit migrations | `bun:sqlite` for single-node tools; PgBouncer once connections pile up |
| Jobs | **pg-boss** (Postgres `SKIP LOCKED`: retries, cron, DLQ) in a separate `worker` process | BullMQ + Redis only if Redis is already core infrastructure |
| Auth | **Better Auth**, mounted in Elysia and exposed as an `auth` macro | `@elysia/jwt` only for machine-to-machine APIs. **Lucia is deprecated** |
| Tests | **bun test** (`--parallel`, coverage thresholds), `treaty(app)` for API tests, a real Postgres per worker | |
| Quality | **Biome 2** (`biome ci .`), **TypeScript 7** `tsc --noEmit` per workspace, `bun audit`, all in GitHub Actions | |
| Deploy | `bun build --compile` binaries (`server` + `worker`) on distroless, **Kamal 2** on Hetzner, DigitalOcean, or EC2, with **Cloudflare** in front | Vercel or Railway for a small side project |
| Observability | `@elysia/opentelemetry` + Sentry (`@sentry/bun`), plus structured JSON logs | |

Versions and setup commands: `references/stack-and-setup.md`.

## Architecture rules, and why

1. **Monorepo by responsibility.** `apps/` hold deployables (`api`, `web`,
   `mobile`). `packages/` hold shared foundations (`db`, `config`, and a
   `contracts` package only when clients need runtime schemas). **Packages
   never depend on apps.** Apps depend on each other only through a
   devDependency on the API, for `import type { App }`.
2. **Feature modules own their slice.** `apps/api/src/modules/<domain>/`
   contains:
   - `index.ts`, the Elysia controller;
   - `model.ts`, the `t` schemas plus derived types;
   - `service.ts`, the business logic;
   - `public.ts`, the module's API for other modules;
   - `jobs.ts`, when the module has background work;
   - `<domain>.test.ts`.

   Other modules and entrypoints import only `public.ts`, and module
   dependencies must stay acyclic (put data in job payloads instead of calling
   back).
3. **One Elysia instance = one controller.** Always method-chain, always use
   inline handlers, and always destructure (`({ body, params, account })`).
   Never pass `Context` to other functions, and never write controller
   classes. That's how Elysia keeps its types.
4. **Services are framework-blind.** They're plain exported functions (imported
   as `import * as BillingService`) that take plain values and never import
   Elysia. They **return a `Result`** for expected outcomes and **throw a
   `DomainError` with a `status`** for exceptional ones. The controller maps
   Results to `status(code, body)`.
5. **One schema per shape.** Declare the schema in `model.ts` and derive every
   type from it (`UnwrapSchema`, `typeof X.static`, `$inferSelect`). Add
   `response` schemas on every route, because they type Eden, document
   OpenAPI, and strip leaked fields.
6. **Request-dependent code is a named plugin.** Auth, tenant resolution, and
   request context are `new Elysia({ name })` plugins exposing **macros**
   (`auth: true`) or `derive`/`resolve`. The name deduplicates them. Only
   request-dependent values get `decorate`d.
7. **Mind lifecycle order and scope.** Hooks apply only to routes registered
   *after* them, and they're local by default. Use `{ as: 'global' }` only for
   cross-cutting concerns (CORS, tracing, logging).
8. **Validate config once.** A TypeBox env schema in `packages/config` parses
   `process.env` at boot and fails fast. Nothing else reads `process.env` on
   the server.
9. **The database enforces the truth.** Use Drizzle schemas per domain, with
   NOT NULL, foreign keys, unique indexes, and checks. Scope every query by
   tenant (`accountId`). Commit migrations, and apply them before deploy.
10. **Side effects go through the queue.** Services enqueue pg-boss jobs
    after the write, and handlers are idempotent. The worker is a separate
    process from the same codebase.
11. **Ship binaries, not source.** `bun build --compile` produces separate
    `server` and `worker` binaries (2–3× less memory, no runtime deps). The
    image is distroless, with a `/up` health route for kamal-proxy.

Full layouts, code, and rationale: `references/architecture.md`.

## Workflow

### 1. Classify the request

| The user wants to... | Read | Produce |
|---|---|---|
| Start a project, pick libraries, set up a monorepo | `references/stack-and-setup.md` | Commands, root `package.json` with catalog, the workspace skeleton |
| Structure modules, write routes, services, or models | `references/architecture.md` | Module files in the house shape (`scripts/new-module.ts`) |
| Plugins, macros, lifecycle, errors, OpenAPI, WebSocket | `references/elysia-patterns.md` | Idiomatic Elysia |
| Frontend or mobile consumption, Eden issues | `references/eden-and-clients.md` | A typed client, with query and error handling |
| Database, migrations, jobs, cron, Redis or S3 | `references/data-and-jobs.md` | Drizzle schema and queries, pg-boss jobs |
| Tests or the CI gate | `references/testing.md` | bun test suites, the GitHub Actions workflow |
| Deploy, Docker, Kamal, Cloudflare, observability, security, performance | `references/deploy-and-operate.md` | Dockerfile, `deploy.yml`, checklists |
| Review code or a PR | `references/review-checklist.md` | Findings ranked by severity, each with a fix |

### 2. Inspect before prescribing (existing projects)

Read the root `package.json` (workspaces, catalog), `bun.lock` or `bunfig.toml`,
each workspace's `package.json` and `tsconfig.json`, `apps/api/src/app.ts`,
and one module. Follow the conventions already present, and propose changes
toward these defaults incrementally. For a structural read, run:

```bash
bun scripts/audit.ts path/to/repo            # human-readable report
bun scripts/audit.ts path/to/repo --json     # machine-readable
```

It flags:
- packages that depend on apps;
- client apps importing server code at runtime;
- Elysia, Eden, or TypeBox version drift;
- non-strict tsconfig;
- services that import Elysia;
- handlers that take the whole `Context`, and unchained instances;
- cross-module imports that bypass `public.ts`, and module cycles;
- mutation routes without a `body` schema;
- deprecated `lucia`, `@elysiajs/swagger`, and `error()`;
- `bun check` (it isn't a command);
- Alpine images without a musl target, and `--bytecode` without
  `--format=esm`.

### 3. Write the code

- New module: `bun scripts/new-module.ts <name> --dir apps/api/src/modules`,
  then register it with `.use(<name>)` in `app.ts`. The output passes Biome,
  `tsc`, and its own tests.
- Every behavior change ships with a test (see `references/testing.md`).
- Show complete files or precise diffs.

### 4. Verify

Run `bunx biome ci .`, `bun run typecheck` (`tsc --noEmit` in each
workspace), `bun test --parallel`, and `bun audit`. For deploy changes, also
run `bun run --filter @acme/api build`. Report failures honestly.

## Gotchas: corrections you'd otherwise need

- **`status()`, not `error()`.** Return or throw `status(code, body)`. Eden
  narrows `error.status` from each route's `response` map.
- **No controller classes, no `Context` parameters, no unchained calls.**
  Each of these breaks inference. `app.get(...)` as a separate statement loses
  types, so always chain.
- **There's no `@elysiajs/typebox` package.** TypeBox is built into Elysia as
  `t`. If you also use `@sinclair/typebox` (shared contracts,
  drizzle-typebox), pin **one** 0.34.x version in the catalog plus
  `overrides`, or you get symbol conflicts.
- **Package scope:** plugins now publish as `@elysia/*` (`@elysia/eden`,
  `@elysia/openapi`, `@elysia/cors`). `@elysiajs/swagger` has become
  `@elysia/openapi`. Elysia 2.0 is in beta, so stay on 1.4 in production.
- **`bun check` doesn't exist.** Type-check with `tsc --noEmit` (TypeScript 7)
  in each workspace: `bun run --filter '*' typecheck`.
- **Use workspace-local `tsc --noEmit`, not `tsc -b` with project
  references.** Declaration emit fails on Eden's inferred client types
  (TS2883). Packages export `.ts` source directly (`"exports": { ".":
  "./src/index.ts" }`).
- **Keep Eden versions aligned.** Server and clients must resolve the same
  `elysia` and `@elysia/eden` (use `catalog:`). Clients add `elysia` as a
  devDependency so the `App` type resolves under isolated installs.
- **Schema constraints (`minimum`, `format`) are runtime-only.** TypeScript
  only sees `number` or `string`, so test them with requests, not
  `@ts-expect-error`.
- **Validation details are hidden in production** (`NODE_ENV=production`).
  Use `error` messages on schemas for user-facing text.
- **Biome 2.5** uses `"preset": "recommended"` (`recommended: true` is
  deprecated; run `biome migrate`). Its `noStaticOnlyClass` rule is why
  services are plain functions, not `abstract class` + `static`.
- **Lucia is deprecated.** Use Better Auth: `.mount('/auth', auth.handler)`
  plus a `macro` resolving `{ user, session }`. The `basePath` can't be `/`.
- **`--bytecode` needs `--format=esm`** when the code uses top-level `await`.
  Avoid `--minify` with OpenTelemetry (it mangles function names); use
  `--minify-whitespace --minify-syntax`.
- **Compiled binaries target glibc by default.** Alpine needs
  `--target=bun-linux-x64-musl` (or `arm64-musl`). Bun needs AVX2 CPUs;
  otherwise use a `-baseline` target.
- **kamal-proxy defaults to port 80 and health path `/up`.** Set
  `proxy.app_port: 3000` and add `.get('/up', () => 'ok')`.
- **`Bun.cron()` runs in every process.** With several containers, schedules
  run N times. Use pg-boss `schedule()` for cluster-wide cron.
- **Behind PgBouncer in transaction mode,** create Bun SQL with
  `prepare: false`, and run migrations on a direct connection.
- **Elysia AOT is already on by default** (`aot: true` unless
  `ELYSIA_AOT=false`). Don't add it. `precompile: true` only moves JIT work to
  startup.
- **Elysia runs on one thread.** Scale with multiple containers or processes
  (`reusePort` is on by default on Linux). Don't run CPU-heavy work in
  handlers; move it to jobs or `Worker`s.

## Available resources

References (load only what the task needs):
- `references/stack-and-setup.md`: verified versions, scaffolding commands,
  workspaces, catalogs, isolated installs, and bunfig.
- `references/architecture.md`: the monorepo and module anatomy, boundaries,
  Results and errors, config, and naming. This is the core of the opinions.
- `references/elysia-patterns.md`: method chaining, lifecycle and scope,
  plugins and dedup, macros, guards, errors, OpenAPI, WebSocket and SSE,
  cookies, and performance.
- `references/eden-and-clients.md`: Eden Treaty setup, error narrowing,
  Next.js, SolidStart, Expo, and TanStack Query.
- `references/data-and-jobs.md`: Drizzle on Bun SQL, schemas, migrations,
  transactions, PgBouncer, pg-boss jobs and cron, Redis, and S3.
- `references/testing.md`: bun test layers, preloads, `treaty(app)`, a
  database per worker, coverage, and the CI gate.
- `references/deploy-and-operate.md`: compiled binaries, Docker, Kamal,
  Cloudflare, observability, security, and performance.
- `references/review-checklist.md`: a severity-ranked review checklist.

Templates (`assets/`, verified together: they lint, type-check, test, and
compile as one monorepo):
- `assets/root-package.json`, `assets/tsconfig.base.json`,
  `assets/biome.json`, and `assets/bunfig.toml`: repo foundation (workspaces,
  catalog, scripts, strict TS, lint, test coverage).
- `assets/env.ts`: the validated environment (`packages/config`).
- `assets/db-client.ts`, `assets/db-schema.ts`, and
  `assets/drizzle.config.ts`: `packages/db`.
- `assets/app.ts`: API composition, `/up`, and `export type App`.
- `assets/auth-plugin.ts`: Better Auth as a named plugin with an `auth`
  macro.
- `assets/test-setup.ts`: a test preload that stubs auth.
- `assets/module-index.ts`, `assets/module-model.ts`,
  `assets/module-service.ts`, `assets/module-public.ts`,
  `assets/module-jobs.ts`, and `assets/module.test.ts`: a complete module.
- `assets/result.ts` and `assets/errors.ts`: the shared Result type and
  DomainErrors.
- `assets/queue.ts` and `assets/worker.ts`: pg-boss setup and the worker
  entrypoint.
- `assets/eden-client.ts`: a typed client for web or mobile.
- `assets/Dockerfile`, `assets/deploy.yml`, and `assets/github-ci.yml`:
  build, deploy, and the CI gate.

Scripts (Bun, built-in modules only, `--help`):
- `scripts/audit.ts`: static health check of a repo. Exits 1 on high findings.
- `scripts/new-module.ts`: scaffolds a module in the house shape.
