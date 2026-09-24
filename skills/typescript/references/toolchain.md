# Toolchain: versions, TypeScript 7, runtimes, package managers

Verified 2026-09-24 against the sources linked in each section. Re-check with
`npm view <pkg> version` before pinning; these move monthly.

## Contents
- Verified versions
- TypeScript 6.0 → 7.0: what changed
- Running TypeScript without a build (Node type stripping, Bun)
- Runtime choice
- Package managers: pnpm 11/12 and Bun
- Upgrading an old project

## Verified versions

| Tool | Version | Notes |
|---|---|---|
| TypeScript | **7.0.2** (`typescript` on npm; Go-native `tsc`) | 7.0 released 2026-07-08; 7.1 dev builds on the `next` tag |
| TypeScript 6 (JS compiler) | 6.0.3 (`typescript@6`), also `@typescript/typescript6` | Only for tools that need the old JS API |
| Node.js | **24.x Active LTS** (24.21.0); 26.x is Current | Production on LTS; test libraries on 22, 24, 26 |
| Bun | 1.4.x | New backends: see the bun-elysia skill |
| pnpm | **12.6.0** (Rust rewrite; 12.0 on 2026-08-26) | Same commands, settings, and lockfile as 11 |
| Biome | 2.5.14 | Formatter + linter |
| oxlint / oxlint-tsgolint | 1.85.0 / 7.0.2003 | Type-aware rules on TS 7 |
| typescript-eslint | 8.70.1 | **Peer range `<6.1.0`: no TS 7 support** |
| ESLint | 10.11.0 | Only with typescript-eslint on a TS 6 side install |
| Vitest | 5.0.1 (2026-09-03) | Node `^22.12 || ^24 || >=26` |
| Zod | 4.6.5 | Implements Standard Schema |
| tsdown | 0.23.0 (rolldown 1.2) | Pre-1.0: pin exactly |
| publint / attw | 0.3.24 / 0.18.5 | Package lint in CI |
| @changesets/cli | 3.0.3 | `init` is now interactive |
| Hono / @hono/node-server | 4.13.9 / 2.1.1 | Default Node HTTP framework here |
| Fastify | 5.12.5 | See `services-and-deploy.md` for when |
| pino | 10.3.1 | JSON logs |
| msw | 2.15.0 | HTTP mocking in tests |

Sources: https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/,
https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/,
https://nodejs.org/en/about/previous-releases, https://pnpm.io/blog/releases/12.0,
the npm registry.

## TypeScript 6.0 → 7.0: what changed

TypeScript 6.0 (2026-03-23) was the last JavaScript-based compiler and the
bridge release: it changed defaults and deprecated old options. 7.0 is the
Go port (roughly 8-12x faster full builds) and **removes** what 6.0
deprecated.

New defaults (since 6.0, kept in 7.0):
- `strict: true`, `module: esnext`, `target` = the current ES year;
- `types: []`: `@types/*` packages are **no longer auto-included**. Add
  `"types": ["node"]` (or `["bun"]`) or `process` is an error (TS2591);
- `rootDir` defaults to the tsconfig's directory;
- `noUncheckedSideEffectImports: true`; `libReplacement: false`;
- `dom` now includes `dom.iterable` and `dom.asynciterable`.

Removed in 7.0 (a config containing them fails with TS5102/TS5108, and
`"ignoreDeprecations": "6.0"` no longer helps):
- `target: es5` (and ES3), `downlevelIteration`;
- `moduleResolution: node`/`node10`/`classic` (use `nodenext` or `bundler`);
- `module: amd`/`umd`/`system`/`none`, `outFile`;
- `baseUrl` (use `paths` relative to the tsconfig, or package.json
  `imports`);
- `esModuleInterop: false`, `allowSyntheticDefaultImports: false`,
  `alwaysStrict: false` (all now always on).

Tooling status in 7.0:
- **No programmatic API** ships in 7.0 (planned for 7.1). Anything that
  `import`s `typescript` as a library (typescript-eslint, ts-morph,
  ts-json-schema-generator, older doc generators) either needs a TS 6 side
  install or a TS 7-native replacement.
- The language service is LSP-based; editors use it through the normal
  TypeScript extension.
- New flags: `--checkers N` (type-check workers, default 4), `--builders N`
  (parallel project-reference builds), `--singleThreaded`.
- Vue/Svelte/Astro/MDX type-checking workflows wait for 7.1.

TS 6 side install (only when a tool needs the JS API), as documented by the
TS team and used in the wild:

```json
"devDependencies": {
  "typescript": "npm:@typescript/typescript6@6.0.2",
  "@typescript/native": "npm:typescript@7.0.2"
}
```

`import 'typescript'` then gets 6.0 while the `tsc` binary is 7. Expect the
editor (6.0) and CI (7.0) to disagree on a handful of errors. Prefer the
TS 7-native path (oxlint type-aware) instead; see `quality-and-security.md`.

## Running TypeScript without a build

**Node**: type stripping is **stable since 24.12 / 25.2**, on by default,
with no warning; `--experimental-strip-types` is unnecessary (removed in 26),
and `--experimental-transform-types` is deprecated. Verified on 24.21.0:
`node src/server.ts` runs a Hono service directly. Limits
(https://nodejs.org/api/typescript.html):
- **Erasable syntax only.** Enums, runtime namespaces, parameter
  properties, `import x = require()` aliases, and decorators throw
  `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`. Type-only namespaces are fine.
- **tsconfig is ignored**: no `paths`, no target downleveling. Use
  package.json `imports` (`"#/*": "./src/*"`) for aliases.
- **Imports need real extensions** (`./x.ts`) and type-only imports need
  `import type` (or `verbatimModuleSyntax` makes TS enforce it).
- **No `.tsx`**, and **no stripping under `node_modules`**
  (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`). A workspace package that
  exports `.ts` works in dev (pnpm symlinks resolve to its real path) but
  breaks once `pnpm deploy`/Docker copies it into `node_modules`: build it.
- No type checking at run time: `tsc --noEmit` stays in CI.

**Bun** runs `.ts`/`.tsx` directly and transpiles everything (enums too),
but write erasable code anyway so the same file runs on Node.

## Runtime choice

- **New backend services run on Bun** with Elysia: use the bun-elysia skill.
- **Node LTS** for: existing Node services, platforms that mandate Node
  (serverless runtimes, some PaaS), and every library's test matrix.
- **Libraries are runtime-agnostic ESM**: web-standard APIs (`fetch`,
  `AbortSignal`, `URL`, `crypto.subtle`) over `node:` modules where possible,
  tested on Node 22/24/26 and smoke-tested on Bun.
- **CLIs**: plain TS run by `node` (type stripping) during development;
  distribute via npm (built JS) or as a single binary
  (`bun build --compile`).

## Package managers: pnpm 11/12 and Bun

Default for Node workspaces: **pnpm** with `pnpm-workspace.yaml` catalogs.
For Bun-first repos, Bun workspaces with catalogs (bun-elysia skill).

pnpm 11 made supply-chain protection the default and pnpm 12 kept it:
- `minimumReleaseAge` defaults to 1440 minutes: versions younger than a day
  don't resolve. When you pin a fresh release, pnpm **writes the package to
  `minimumReleaseAgeExclude` in pnpm-workspace.yaml by itself**. Review and
  delete those entries later; set `minimumReleaseAgeStrict: true` to be
  prompted instead.
- `strictDepBuilds` is on: an install **fails** (`ERR_PNPM_IGNORED_BUILDS`)
  when a dependency has an unapproved postinstall. Decide per package in
  `allowBuilds:` (`msw: false`: its postinstall only copies a browser
  worker).
- Settings live in `pnpm-workspace.yaml`; pnpm 12 reports unknown keys.
- `packageManager: "pnpm@12.6.0"` in the root package.json pins the version
  (`pnpm/action-setup` reads it).

Catalogs: one version per dependency in `catalog:`, referenced as
`"zod": "catalog:"` from each package. Workspace packages use
`"workspace:*"`.

## Upgrading an old project

1. Delete removed options (`baseUrl` → `paths` or `imports`,
   `moduleResolution node` → `nodenext`, drop `esModuleInterop: false`,
   `target: es5`, `downlevelIteration`, `outFile`).
2. Add `"types": ["node"]`.
3. Replace enums with `as const` objects, parameter properties with fields,
   namespaces with modules; turn on `erasableSyntaxOnly`.
4. Swap ts-node/tsx for `node file.ts`; swap `dotenv` for
   `node --env-file-if-exists=.env`; drop `node-fetch`.
5. Run `node scripts/audit.ts <repo>` (from this skill) to find the rest.
