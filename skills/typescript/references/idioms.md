# Idioms: types, errors, validation, modules

## Contents
- Naming and modules
- Model with unions, not flags and classes
- Exhaustiveness
- `satisfies`, `as const`, and literal objects instead of enums
- Branded ids
- Errors: Result for expected outcomes, throw for the rest
- `unknown`, narrowing, and no `!`
- Validate at the boundaries (Zod 4, Standard Schema)
- Generics and type-level code: how much is enough
- Resource management (`using`)
- Frontend-adjacent TypeScript (brief)
- The "don't" list

## Naming and modules

- Files `kebab-case.ts`; types and classes `PascalCase`; values and
  functions `camelCase`; true constants `UPPER_SNAKE` only for
  configuration-like values. No `I` prefix on interfaces, no `T` prefix on
  types (generic parameters are `T`, `K`, or a word: `TItem` is fine).
- Named exports only (default exports rename freely and hide in refactors;
  config files that tools require are the exception).
- `import type` for types (enforced by `verbatimModuleSyntax` and Biome's
  `useImportType`). `import * as z from 'zod'` for namespaced libraries.
- No barrel file per folder. One `index.ts` per *package* as its public
  API.
- `interface` for object shapes that are implemented or extended; `type`
  for unions, mapped types, and function types. Don't debate it further.

## Model with unions, not flags and classes

```ts
type Payment =
  | { status: 'pending'; id: PaymentId }
  | { status: 'paid'; id: PaymentId; paidAt: Date }
  | { status: 'failed'; id: PaymentId; reason: string }
```

A discriminated union makes impossible states unrepresentable
(`paidAt` exists only when paid) and narrows on `switch (p.status)`.
Classes are for things with identity and behavior over time (a client, a
pool); data is plain readonly objects.

## Exhaustiveness

```ts
export function assertNever(value: never): never {
  throw new Error(`unhandled case: ${JSON.stringify(value)}`)
}

switch (result.error) {
  case 'code_taken': return c.json({ error: result.error }, 409)
  default: return assertNever(result.error) // compile error when a case is added
}
```

The type-aware lint rule `switch-exhaustiveness-check` (oxlint) catches the
same thing without the default branch; keep `assertNever` anyway because
it also throws at run time on bad data.

## `satisfies`, `as const`, and objects instead of enums

Enums aren't erasable (Node won't run them) and `const enum` breaks
isolated compilation. Use:

```ts
export const Status = { Active: 'active', Closed: 'closed' } as const
export type Status = (typeof Status)[keyof typeof Status] // 'active' | 'closed'

const routes = {
  home: '/',
  link: '/links/:code',
} as const satisfies Record<string, `/${string}`>
```

`satisfies` checks a value against a type without widening it: `routes.home`
stays the literal `'/'`. Use it for config tables and lookup maps. Use `as
const` for literal tuples and objects. A plain string-literal union
(`type Units = 'metric' | 'imperial'`) is usually all you need.

## Branded ids

```ts
export const LinkCode = z.string().regex(/^[a-z0-9]{4,32}$/).brand<'LinkCode'>()
export type LinkCode = z.infer<typeof LinkCode>
```

A `LinkCode` can only come from parsing, so functions that take one never
re-validate, and a `UserId` can't be passed where an `OrderId` goes.
Without Zod: `type UserId = string & { readonly __brand: 'UserId' }` plus
one constructor function that validates. Brand ids and validated strings
(emails, slugs); don't brand everything.

## Errors: Result for expected outcomes, throw for the rest

Default:
- **Expected, domain-level outcomes** that callers must handle (not found,
  conflict, insufficient funds) → return a `Result`:
  `{ ok: true, value } | { ok: false, error: 'code_taken' }` with a
  string-literal error union. The compiler forces the caller to look.
- **Exceptional failures** (bugs, I/O errors, timeouts, invalid config) →
  `throw` an `Error` subclass with a `cause`, caught at one boundary (the
  HTTP error handler, the CLI's `run`, a job runner).
- Libraries throw typed errors (`class RetryError extends Error`) with
  extra fields as readonly properties, and document them.

No Result library (neverthrow, Effect) unless the team already uses it: the
10-line `assets/result.ts` covers it. Never mix both styles for the same
outcome.

Error hygiene:
- `new Error('refresh link preview', { cause: error })` whenever you
  rethrow; the chain is what makes the log useful.
- Set `override readonly name = 'RetryError'` on subclasses.
- `catch (error)` gives `unknown` (strict). Narrow with `instanceof` or a
  type guard; `Error.isError()` exists on newer runtimes, `instanceof Error`
  works everywhere.
- Never `throw 'string'` or `throw { code }`; never an empty `catch {}`
  without a comment explaining why ignoring is correct.

## `unknown`, narrowing, and no `!`

- `any` turns off checking for everything it touches and spreads.
  Use `unknown` and narrow (`typeof`, `in`, `instanceof`, a schema).
- `as T` is an unchecked claim. Allowed: `as const`, and narrowing a value
  you've just checked when TS can't follow (with a comment). Not allowed:
  `JSON.parse(x) as User`, `res.json() as T`, `as any`, `as unknown as T`.
- Non-null `!` is a claim that crashes later and far away. Replace with a
  check that throws a clear error, `??` with a default, or restructure so
  the value is never optional. Tests may use `expect(x).toBeDefined()` and
  then narrow.
- `// @ts-expect-error: <reason>`, never `@ts-ignore` (expect-error fails
  when the error disappears).

## Validate at the boundaries (Zod 4, Standard Schema)

Every value that crosses a trust boundary is `unknown` until parsed: HTTP
bodies and query strings, `process.env`, `JSON.parse`, `fetch` responses,
queue messages, files, `localStorage`. Parse once at the edge, then pass
typed values inward.

```ts
const Preview = z.object({ title: z.string(), description: z.string().nullable() })
export type Preview = z.infer<typeof Preview> // derive; never hand-write a parallel interface
const preview = Preview.parse(await res.json())
```

- Zod 4: `import * as z from 'zod'`; top-level formats (`z.url()`,
  `z.email()`, `z.uuid()`); `z.strictObject` rejects unknown keys (use it
  for request bodies to catch typos and mass assignment); `z.prettifyError`
  for readable messages; `safeParse` when you branch, `parse` when failure
  is exceptional.
- **Standard Schema** (`~standard`) is the interop contract: Zod 4,
  Valibot, and ArkType implement it, and Hono (`@hono/standard-validator`),
  tRPC, and TanStack accept any of them. Library APIs that take a schema
  should accept `StandardSchemaV1` from `@standard-schema/spec` instead of
  depending on Zod.
- Zod runs at run time; that's the point. In hot paths, validate at the
  edge, not in inner loops.
- In a Bun + Elysia service, use Elysia's `t` (TypeBox) instead: see the
  bun-elysia skill.

## Generics and type-level code: how much is enough

App code: generics on functions where the caller's type flows through
(`retry<T>(fn: () => Promise<T>): Promise<T>`), and that's about it.
Conditional/mapped/template-literal types belong in libraries whose API
benefits (a typed router, a query builder), with type tests. Template
literal types sparingly: route params and event names, not string
parsing. If a type needs a comment to explain what it computes, it's too
clever for app code. Avoid overloads when a union parameter works.

Useful built-ins: `NoInfer<T>` (stop a parameter from widening inference),
`const` type parameters (`function f<const T>(x: T)` infers literals),
`Awaited`, `ReturnType`, `Parameters`, `Readonly`, `Pick`/`Omit`.

## Resource management (`using`)

`using` / `await using` call `[Symbol.dispose]()` / `[Symbol.asyncDispose]()`
at scope exit, even on throw. Verified on Node 24.21 and Bun 1.4.2 with
type stripping (no transform needed). Needs `lib` to include
`esnext.disposable` (in the base config).

```ts
await using conn = await pool.connect()  // released even if the query throws
using timer = scopedTimer()              // any object with [Symbol.dispose]
```

Use it for locks, temp files, connections, spans, and subscriptions.
`DisposableStack`/`AsyncDisposableStack` collect several resources.
Libraries targeting Node 20 must still offer `close()`.

## Frontend-adjacent TypeScript (brief)

- React 19 (19.3) + Vite 8 for SPAs, Next.js 16 for full-stack React.
  Bundled apps use `module: preserve`, `moduleResolution: bundler`,
  `jsx: react-jsx`, `lib` with `dom`, and `types: ["vite/client"]` as
  needed.
- Props: `type ButtonProps = { variant: 'primary' | 'ghost' } &
  ComponentProps<'button'>`; no `React.FC`. In React 19 `ref` is a regular
  prop (no `forwardRef`); type it via `ComponentProps`.
- Server data: validate at the fetch boundary with the same Zod schemas
  (share them from a `packages/contracts` package), and type
  `useActionState`/form actions from the schema.
- `.tsx` can't run under Node type stripping; that's fine because a
  bundler owns frontend code.
- Deep framework guidance is out of scope for this skill.

## The "don't" list

- `any`, `as any`, `as unknown as T`, `!`, `@ts-ignore`, `@ts-nocheck`.
- Enums, namespaces, parameter properties, decorators in new code.
- Hand-written interfaces that duplicate a schema; `JSON.parse(x) as T`.
- Default exports (outside tool config files), `export *` in public
  entry points, per-folder barrels.
- Classes of static methods (`noStaticOnlyClass`): export functions.
- Mutable module-level state (except process wiring in `server.ts`/`main`).
- `Function`, `Object`, `{}` as types; use signatures, `object`,
  `Record<string, unknown>`.
- `Date` for durations: numbers in ms (named `timeoutMs`); Temporal once
  your runtimes ship it.
- `lodash` for what the language has (`structuredClone`, `Object.groupBy`,
  `Array.prototype.toSorted`, `Set` methods).
- `CommonJS` (`require`, `module.exports`) in new code.
