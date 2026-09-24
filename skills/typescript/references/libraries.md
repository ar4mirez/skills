# Libraries: build, package, publish

## Contents
- Principles
- package.json
- Building: tsdown (default) or plain tsc
- Checking the package: publint and attw
- Versioning: changesets
- Publishing: npm with provenance, JSR as an option
- API design notes

## Principles

- **ESM only**, runtime-agnostic: web-standard APIs first (`fetch`,
  `AbortSignal`, `URL`, `TextEncoder`, `crypto.subtle`). Node 22+ can
  `require()` ESM, so CJS consumers are covered without a dual build;
  dual packages double your surface for little gain.
- **Small public surface**: one entry point, explicit named exports,
  documented errors. Everything exported is a promise you keep.
- **No side effects on import** (`"sideEffects": false`), no `console`,
  no `process.env`, no `process.exit`; accept options and a logger.
- **Types are part of the API**: `isolatedDeclarations` forces explicit
  return types on exports, which also makes the API readable.

## package.json

```json
{
  "name": "@acme/retry",
  "version": "1.0.0",
  "type": "module",
  "sideEffects": false,
  "files": ["dist"],
  "exports": {
    ".": { "types": "./dist/index.d.ts", "default": "./dist/index.js" },
    "./package.json": "./package.json"
  },
  "engines": { "node": ">=20" },
  "scripts": {
    "build": "tsdown",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "lint:pkg": "publint --strict && attw --pack . --profile esm-only"
  }
}
```

- `types` is the **first** condition in each `exports` entry (TS picks the
  first match).
- `files: ["dist"]` keeps tests and sources out of the tarball.
- No `main`/`module`/top-level `types` needed when every supported
  resolver reads `exports` (all current TS `moduleResolution` modes do).
- Exporting `.ts` source is fine *inside* a Bun monorepo (bun-elysia
  skill) but not for anything Node imports from `node_modules`: Node won't
  strip types there.

## Building: tsdown (default) or plain tsc

tsdown 0.23 (rolldown + oxc) with `assets/tsdown.config.ts`:
`entry: ['src/index.ts']`, `format: 'esm'`, `platform: 'neutral'`,
`target: 'es2022'`, `dts: true`, `sourcemap: true`, `clean: true`. Output:
`dist/index.js`, `dist/index.d.ts`, source map (with `"type": "module"`
the extensions are `.js`/`.d.ts`).

- With `isolatedDeclarations` on, declarations come from oxc (fast, no
  compiler). Without it, tsdown shells out to the installed TypeScript; on
  TS 7 that works but warns that TS 7 "does not yet have a stable API"
  (verified).
- tsdown is pre-1.0: pin the exact version in the catalog.
- `target: 'es2022'` downlevels only syntax newer than your oldest
  supported runtime; keep it at or below the `engines` floor.

Plain `tsc` emit is the zero-dependency alternative when you want one
output file per source file: a `tsconfig.build.json` extending the package
config with `noEmit: false`, `outDir: "dist"`, `rootDir: "src"`, excluding
tests. Verified on TS 7: `rewriteRelativeImportExtensions` rewrites
`./retry.ts` to `./retry.js` in JS; the `.d.ts` keeps `./retry.ts`, which
consumers still resolve (attw green, nodenext consumer type-checks).

## Checking the package: publint and attw

Both run against the packed tarball, i.e. what users install:
- `publint --strict`: exports/files/type mismatches, missing files.
- `attw --pack . --profile esm-only`: are-the-types-wrong resolves the
  package the way `node16` (ESM), `bundler`, and CJS consumers do and flags
  mismatched types. The `esm-only` profile ignores the expected
  "CJS consumers need dynamic import" and `node10` rows. Verified green on
  the reference library.

Both belong in CI (`lint:pkg`), after `build`.

## Versioning: changesets

Changesets is still the standard for monorepo versioning (v3.0.3, 2026-09):
- A PR that changes a published package adds `.changeset/<name>.md` with
  the bump (`patch`/`minor`/`major`) and a user-facing note.
- `changeset version` applies bumps, updates internal dependents
  (`updateInternalDependencies: "patch"`), and writes CHANGELOGs;
  `changeset publish` publishes and tags. `changesets/action@v2` automates
  the "Version Packages" PR.
- `changeset init` is **interactive** in v3 (it prompts about GitHub
  changelogs and hangs in CI/agents). Write `.changeset/config.json` by hand
  (`assets/changeset-config.json`) instead. `changeset status` needs a git
  repo with the base branch.
- `privatePackages: { version: false, tag: false }` keeps apps out of it.

Single-package libraries can skip changesets and bump by hand with a
CHANGELOG, but the workflow costs little.

## Publishing: npm with provenance, JSR as an option

- Publish from CI, not laptops, with provenance (npm trusted publishing or
  `npm publish --provenance --access public` in a job with
  `id-token: write`).
- `pnpm publish` rewrites `workspace:*` and `catalog:` to real versions;
  plain `npm publish` in a pnpm workspace would not.
- JSR (jsr.io) publishes TypeScript source and generates docs; worth it
  for libraries targeting Deno and Bun too. Keep npm as the primary
  registry for Node users; verify the current `jsr publish` flow before
  adopting it.

## API design notes

- Options objects over positional booleans; every option optional with a
  documented default; `readonly` fields.
- Accept `signal?: AbortSignal` on anything that does I/O or waits.
- Inject non-determinism (`random`, `now`) for testability, with sane
  defaults.
- Accept a Standard Schema (`StandardSchemaV1`) rather than depending on
  a specific validator.
- Errors: exported `Error` subclasses with `name`, readonly fields, and
  `cause`.
- Semver discipline: removing an export, narrowing a parameter type, or
  widening a return type is a breaking change. Type tests
  (`expectTypeOf`) guard inference.
