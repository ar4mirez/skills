# Layout: library, CLI, service, workspace

## Contents
- The workspace (default for anything with more than one package)
- A library package
- A CLI
- A Node service
- A single-package project
- Asset-to-path map
- Scripts and the gate

## The workspace

```
acme/
  package.json            # private root: scripts, packageManager, shared devDeps
  pnpm-workspace.yaml     # packages + catalog + allowBuilds
  pnpm-lock.yaml
  tsconfig.base.json
  biome.json
  .oxlintrc.json          # type-aware rules only (optional, see quality-and-security.md)
  .changeset/config.json  # when packages are published
  .github/workflows/ci.yml
  Dockerfile              # per deployable app, or one with ARG APP
  config/deploy.yml       # Kamal
  packages/
    retry/                # publishable library (built with tsdown)
  apps/
    api/                  # Node service (runs .ts directly)
    cli/                  # CLI (runs .ts directly; optional binary)
```

Rules:
- `packages/*` never depend on `apps/*`. Apps depend on packages with
  `"workspace:*"`.
- Every external version lives once in `catalog:`. Apps and packages say
  `"zod": "catalog:"`.
- Internal-only packages are `"private": true`. Publishable ones have an
  `exports` map, `files`, and a build.
- Workspace libraries that Node services import are **built** (their
  `exports` point at `dist`). Exporting `.ts` source works in dev but breaks
  once the app is deployed with its dependencies copied into
  `node_modules` (Node refuses to strip types there). Build order:
  `pnpm --filter "<app>^..." build`.
- Turborepo/Nx only when CI time forces caching; pnpm's `-r` already runs
  in topological order.

## A library package

```
packages/retry/
  package.json        # type: module, exports {types, default}, files: [dist], sideEffects: false
  tsconfig.json       # extends base + isolatedDeclarations
  tsdown.config.ts
  src/
    index.ts          # the public API: explicit named re-exports only
    retry.ts
    retry.test.ts
  dist/               # build output, gitignored, published
```

- One entry (`.`) until there's a real reason for subpaths; each subpath
  is API you must keep.
- `index.ts` re-exports names explicitly (`export { retry, type RetryOptions }
  from './retry.ts'`), never `export *`, so the public surface is reviewable.
- No `console`, no `process.exit`, no reading `process.env` in library code:
  take options, return values, throw typed errors.

Details: `libraries.md`.

## A CLI

```
apps/cli/
  package.json      # bin -> ./src/main.ts (private) or ./dist/main.js (published)
  src/
    main.ts         # run(argv, io): Promise<number>; wiring under `if (import.meta.main)`
    pool.ts         # plain modules with the logic
    main.test.ts
```

- `run(argv, io)` returns the exit code; only the `import.meta.main` block
  touches `process`. Tests call `run` with fake stdout/stderr/fetch.
- Parse flags with `node:util` `parseArgs` (no commander/yargs for small
  CLIs). Exit codes: 0 ok, 1 failure found, 2 usage error.
- Publishing to npm: build to `dist` with tsdown (entry `src/main.ts`),
  `bin` points at the built file with a `#!/usr/bin/env node` shebang.
  Standalone binary: `bun build --compile --minify --sourcemap --outfile
  dist/linkcheck src/main.ts` (verified; `import.meta.main` works in the
  binary).

## A Node service

```
apps/api/
  package.json   # start: node src/server.ts
  src/
    server.ts    # process wiring only: env, logger, serve, signals
    app.ts       # createApp(deps) -> Hono app (no listen), so tests use app.request()
    env.ts       # Zod schema for process.env, parsed once
    links.ts     # domain: schemas, types, pure functions, the store port
    preview.ts   # outbound HTTP client (timeouts, retries, validation)
    result.ts    # Result + assertNever
    *.test.ts
```

- The domain module never imports Hono; the app module only translates
  HTTP to domain calls and back.
- Dependencies (store, logger, clock) are passed into `createApp`; no
  module-level singletons except in `server.ts`.
- Grow by domain (`links.ts` → `links/` folder with `schema.ts`,
  `service.ts`, `store-postgres.ts`) when a file passes ~300 lines, not
  before.

Details: `services-and-deploy.md`.

## A single-package project

Same shapes without `apps/`/`packages/`: `package.json`, `tsconfig.json`
(the base config inlined), `biome.json`, `src/`. Move to a workspace when a
second deployable or a shared package appears.

## Asset-to-path map

| Asset | Path in the project |
|---|---|
| `assets/root-package.json` | `package.json` |
| `assets/pnpm-workspace.yaml` | `pnpm-workspace.yaml` |
| `assets/tsconfig.base.json` | `tsconfig.base.json` |
| `assets/biome.json` | `biome.json` |
| `assets/oxlintrc.json` | `.oxlintrc.json` |
| `assets/changeset-config.json` | `.changeset/config.json` |
| `assets/github-ci.yml` | `.github/workflows/ci.yml` |
| `assets/Dockerfile`, `assets/dockerignore` | `Dockerfile`, `.dockerignore` |
| `assets/deploy.yml` | `config/deploy.yml` |
| `assets/lib-package.json`, `assets/lib-tsconfig.json`, `assets/tsdown.config.ts` | `packages/retry/{package.json,tsconfig.json,tsdown.config.ts}` |
| `assets/index.ts`, `assets/retry.ts`, `assets/retry.test.ts` | `packages/retry/src/` |
| `assets/api-package.json`, `assets/app-tsconfig.json` | `apps/api/{package.json,tsconfig.json}` |
| `assets/server.ts`, `assets/app.ts`, `assets/env.ts`, `assets/links.ts`, `assets/preview.ts`, `assets/result.ts` + their `*.test.ts` | `apps/api/src/` |
| `assets/cli-package.json`, `assets/cli-tsconfig.json`, `assets/vitest.config.ts` | `apps/cli/{package.json,tsconfig.json,vitest.config.ts}` |
| `assets/main.ts`, `assets/pool.ts`, `assets/main.test.ts` | `apps/cli/src/` |

Rename `acme`/`@acme/*`, `retry`, `links`, and `linkcheck` to the real
names.

## Scripts and the gate

Root scripts (from `assets/root-package.json`):

```
pnpm build       # libraries only (tsdown)
pnpm typecheck   # tsc --noEmit in every package
pnpm lint        # biome ci . && oxlint
pnpm test        # vitest run in every package
pnpm check       # all of the above, in order
```

Per library: `pnpm --filter './packages/*' run lint:pkg` (publint + attw).
