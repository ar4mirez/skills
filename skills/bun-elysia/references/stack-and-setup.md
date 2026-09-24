# Stack and setup

Versions were verified against the npm registry and GitHub in September 2026.
Always check `bun.lock` in an existing repo, and prefer the latest patch
release of these versions for new ones.

## Current versions

| Component | Version | Notes |
|---|---|---|
| Bun | **1.4.2** | 1.4 was rewritten in Rust. It adds `bun test --parallel/--isolate/--shard/--timings`, `bun run --parallel`, `bun audit fix`, `bun pm diff`, a global virtual store, `Bun.cron`, `Bun.WebView`, and bytecode for ESM |
| Elysia | **1.4.30** | 2.0 is in beta (`next` tag); stay on 1.4 for production |
| Plugins | `@elysia/eden` 1.4.x, `@elysia/openapi` 1.4.x, `@elysia/cors`, `@elysia/jwt`, `@elysia/opentelemetry`, `@elysia/cron`, `@elysia/static` | The new `@elysia/*` scope; `@elysiajs/*` names still publish. `@elysiajs/swagger` is superseded by `@elysia/openapi` |
| TypeBox | `@sinclair/typebox` 0.34.x | Elysia depends on `>=0.34 <1`. Pin **one** version in the catalog + `overrides` |
| TypeScript | **7.0** (Go-native `tsc`) | Type-check only (`noEmit`); Bun runs TS directly |
| Drizzle | drizzle-orm **0.45.3**, drizzle-kit 0.31 | 1.0 is at RC. Adopt it when stable, following its migration notes |
| Better Auth | 1.7.x | Lucia 3 is **deprecated** |
| pg-boss | 12.x | Postgres job queue: SKIP LOCKED, cron, retries, DLQ, Drizzle transaction adapter |
| Biome | 2.5.x | `"preset": "recommended"` replaces `recommended: true` |
| Web / mobile | Next.js 16, SolidStart 2, Expo SDK 57 / React Native 0.87, TanStack Query 5 | |
| Observability | `@elysia/opentelemetry` 1.4, `@sentry/bun` 11 | |

## Scaffolding a new monorepo

```bash
mkdir acme && cd acme && git init
bun init -y                               # then replace package.json with assets/root-package.json
mkdir -p apps/api/src/{modules,plugins,shared} apps/api/test packages/{config,db}/src

# workspace package.json files first (name, "type": "module", "exports"), then add deps.
# --catalog writes the version to the root catalog and "catalog:" into the workspace.
bun add elysia @elysia/openapi drizzle-orm better-auth pg-boss --catalog --filter @acme/api
bun add -d @elysia/eden --catalog --filter @acme/api
bun add drizzle-orm --catalog --filter @acme/db
bun add -d drizzle-kit --catalog --filter @acme/db
bun add @sinclair/typebox --catalog --filter @acme/config

# repo tooling (root)
bun add -d typescript @types/bun @biomejs/biome
```

Then copy the templates:

| Asset | Destination |
|---|---|
| `assets/tsconfig.base.json` | repo root |
| `assets/biome.json` | repo root |
| `assets/bunfig.toml` | repo root |
| `assets/env.ts` | `packages/config/src/index.ts` |
| `assets/db-client.ts` | `packages/db/src/index.ts` |
| `assets/db-schema.ts` | `packages/db/src/schema/<domain>.ts` |
| `assets/drizzle.config.ts` | `packages/db/` |
| `assets/app.ts` | `apps/api/src/` |
| `assets/auth-plugin.ts` | `apps/api/src/plugins/auth.ts` |
| `assets/result.ts`, `assets/errors.ts`, `assets/queue.ts` | `apps/api/src/shared/` |
| `assets/worker.ts` | `apps/api/src/` |
| `assets/test-setup.ts` | `apps/api/test/setup.ts` |
| `assets/github-ci.yml` | `.github/workflows/ci.yml` |

Next:
1. Run `bun scripts/new-module.ts <first-domain>` and register it in
   `app.ts`.
2. Give each workspace a `tsconfig.json` that extends the base:
   `{ "extends": "../../tsconfig.base.json", "include": ["src"] }`. Add a
   `"typecheck": "tsc --noEmit"` script to its `package.json`.
3. Run `bun install`, `bun run check`, and `bun run --filter @acme/api dev`.

For web and mobile, scaffold with the framework's own tool (`bunx
create-next-app apps/web`, or `bunx create-expo-app apps/mobile`). Then add
`@elysia/eden` (dependency), plus `@acme/api` and `elysia` (devDependencies,
both `catalog:` or `workspace:*`).

## Root package.json (catalog + scripts)

See `assets/root-package.json`. Its key pieces:
- `"workspaces": { "packages": ["apps/*", "packages/*"], "catalog": { ... } }`
  holds one version per shared dependency. Workspaces reference it with
  `"elysia": "catalog:"`. Bun 1.4 supports `bun add --catalog`.
- `"overrides": { "@sinclair/typebox": "catalog:" }` guarantees a single
  TypeBox copy.
- `"packageManager": "bun@1.4.2"` pins Bun for CI (`oven-sh/setup-bun` reads
  it).
- Scripts:
  - `typecheck` runs `bun run --filter '*' typecheck`;
  - `lint` runs `biome ci .`;
  - `test` runs `bun test --parallel`;
  - `audit` runs `bun audit --audit-level=high`;
  - `check` runs all of them.

## Installs

- **Isolated linker:** the pnpm-style layout is the default for new
  workspaces (lockfile `configVersion = 1`). Keep it, because it prevents
  phantom dependencies. The side effect is that each workspace must declare
  every package it imports, including `elysia` in clients that use the `App`
  type. Stricter still: `install.hoist = false`.
- **Text lockfile:** commit `bun.lock`. Migrate a legacy `bun.lockb` with
  `bun install --save-text-lockfile`.
- **CI:** use `bun install --frozen-lockfile`. For security:
  - `bun audit` (and `bun audit fix`);
  - `trustedDependencies` only for packages whose postinstall you've reviewed
    (Bun already auto-trusts only npm-registry packages);
  - `bun pm licenses` for license review.
- **Filtering:** use `bun run --filter '@acme/api' dev`, `bun add --filter
  @acme/web <pkg>`, and `bun install --filter '@acme/api'` (in Docker).

## Environment

- Bun auto-loads `.env`, `.env.<NODE_ENV>`, and `.env.local`. Commit
  `.env.example` only. Compiled binaries also auto-load `.env` unless you
  build with `--no-compile-autoload-dotenv`. For production, prefer real
  environment variables (Kamal secrets).
- `packages/config` validates everything at boot (`assets/env.ts`). Add each
  new variable to the schema with a type and, where safe, a default.

## Upgrading

- **Bun:**
  1. Bump `packageManager`, the CI `bun-version`, and the Docker `oven/bun`
     tag together.
  2. Run the full check.
  3. Read the release notes for changes to `bun test` and `bun build`.
- **Elysia (minor versions):** update `elysia` and `@elysia/*` together in
  the catalog, run `typecheck` (Eden types surface breakages at compile time),
  and run the tests.
- **Elysia 2.0 (once stable):** follow the official migration guide on a
  branch, one app at a time.
- **Drizzle 1.0:** upgrade drizzle-orm and drizzle-kit together, regenerate
  migration snapshots per the upgrade guide, and verify with `drizzle-kit
  check`.
