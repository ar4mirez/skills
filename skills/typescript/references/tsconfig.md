# tsconfig: the house configuration and why

## Contents
- The base config
- Flag by flag
- nodenext vs bundler
- exactOptionalPropertyTypes: the trade-off
- Per-package configs (library, app, CLI, tools)
- Paths and aliases
- Common errors

## The base config

`assets/tsconfig.base.json` (repo root), extended by every package:

```json
{
  "compilerOptions": {
    "target": "es2024",
    "lib": ["es2024", "esnext.disposable"],
    "module": "nodenext",
    "moduleResolution": "nodenext",
    "types": ["node"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true,
    "erasableSyntaxOnly": true,
    "allowImportingTsExtensions": true,
    "rewriteRelativeImportExtensions": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "noEmit": true
  }
}
```

Verified with TypeScript 7.0.2 across a library, a Hono service, and a CLI.

## Flag by flag

- `strict` is the default since 6.0; keep it explicit so older tools and
  readers see it.
- `noUncheckedIndexedAccess`: `arr[i]` and `record[key]` are `T | undefined`.
  This is where most production `undefined` crashes come from. Narrow with
  a check, `.at()`, or destructuring defaults, not `!`.
- `verbatimModuleSyntax`: imports are emitted exactly as written, so
  type-only imports must say `import type` / `type X`. Required for type
  stripping, where an unmarked type import fails at run time.
- `erasableSyntaxOnly`: errors on enums, runtime namespaces, parameter
  properties, and `import =` aliases (TS1294), the syntax Node's stripper
  rejects. It keeps every file runnable by `node file.ts`.
- `allowImportingTsExtensions` + `rewriteRelativeImportExtensions`: write
  `import { x } from './x.ts'` (what Node and Bun execute); if `tsc` ever
  emits, it rewrites to `./x.js`. Declaration output keeps `./x.ts`, which
  consumers still resolve (verified with attw and a nodenext consumer).
- `types: ["node"]`: TS 6+ no longer loads every `@types/*`. List what the
  package uses (`"node"`, `"bun"`), nothing else.
- `lib: es2024 + esnext.disposable`: matches what Node 22+ ships and adds
  `Disposable`/`AsyncDisposable` for `using`. Add `"dom"` only in packages
  that run in browsers.
- `isolatedModules`: every file compiles alone, as esbuild, rolldown, Bun,
  and Node's stripper do.
- `skipLibCheck`: don't type-check `node_modules` declarations; your own
  code is still checked.
- `noEmit`: `tsc` is the type checker. Emit comes from tsdown (libraries)
  or doesn't exist (services and CLIs run `.ts`).
- Libraries add `isolatedDeclarations` (explicit types on exports) so
  declaration files can be generated per file by oxc (tsdown's fast path).

Leave out `noPropertyAccessFromIndexSignature`: it forces `obj['key']`,
which fights Biome's `useLiteralKeys`, and `noUncheckedIndexedAccess`
already makes such reads return `T | undefined`.

## nodenext vs bundler

- `module`/`moduleResolution: nodenext` for anything Node executes or
  publishes: services, CLIs, libraries. It enforces what Node actually does
  (extensions, `exports` maps, ESM/CJS boundaries), so a green `tsc` means
  Node will resolve it.
- `module: preserve` + `moduleResolution: bundler` only for code a bundler
  owns end to end (a Vite/Next app, Bun-only apps as in the bun-elysia
  skill): extensionless imports and `paths` work because the bundler
  resolves them.
- Never `node`/`node10`: removed in TS 7.

## exactOptionalPropertyTypes: the trade-off

With it on, `prop?: string` means "absent or a string", not "or
`undefined`". Benefit: `{ ...defaults, ...options }` can't silently
overwrite a default with an explicit `undefined`, and `'key' in obj` checks
mean something. Cost: you can't write `{ signal: maybeSignal }` when
`maybeSignal` may be `undefined`; you write
`...(signal ? { signal } : {})`, or declare `signal?: AbortSignal | undefined`
on types you own, and some third-party types need the same treatment.

Default: **on** for new code (the reference service needed exactly one
conditional spread). Turn it off in an existing codebase if enabling it
produces hundreds of errors in code you don't own; the bun-elysia skill
keeps it off for Elysia codebases.

## Per-package configs

```jsonc
// packages/<lib>/tsconfig.json (assets/lib-tsconfig.json)
{ "extends": "../../tsconfig.base.json",
  "compilerOptions": { "isolatedDeclarations": true, "declaration": true },
  "include": ["src", "tsdown.config.ts"] }

// apps/<service>/tsconfig.json (assets/app-tsconfig.json)
{ "extends": "../../tsconfig.base.json", "include": ["src"] }

// apps/<cli>/tsconfig.json (assets/cli-tsconfig.json)
{ "extends": "../../tsconfig.base.json", "include": ["src", "vitest.config.ts"] }
```

Tests live next to code (`*.test.ts`) and are included, so `tsc --noEmit`
also enforces `expectTypeOf` assertions.

`isolatedDeclarations` applies to config files too: `export default
defineConfig({...})` fails with TS9037. Assign to a typed const first
(`const config: UserConfig = defineConfig(...)`; `export default config`).

Run `tsc --noEmit` per package (`pnpm -r typecheck`). Use project
references (`tsc -b`) only when a single typecheck gets slow; TS 7's
`--builders` parallelizes them.

## Paths and aliases

`paths` doesn't survive to run time under Node (tsconfig is ignored). Use
package.json subpath imports, which Node, Bun, bundlers, and TS all honor:

```json
"imports": { "#/*": "./src/*" }
```

Then `import { x } from '#/links.ts'`. TS 6+ supports the `#/` prefix.
Prefer relative imports inside a package until depth makes them unreadable.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| TS5102/TS5108 "has been removed" | TS 6 option in a TS 7 config | Delete it (see `toolchain.md`) |
| TS2591 Cannot find name 'process' | `types: []` default | `"types": ["node"]` |
| TS1294 not allowed with erasableSyntaxOnly | enum, namespace, parameter property | `as const` object, module, explicit field |
| TS9037 default export can't be inferred | `isolatedDeclarations` | Typed const, then export it |
| TS2835 relative import needs extension | nodenext | Add `.ts` |
| TS2375 with exactOptionalPropertyTypes | passing `undefined` to `x?:` | Conditional spread or `x?: T | undefined` |
