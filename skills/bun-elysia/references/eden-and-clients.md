# Eden Treaty and clients (web and mobile)

Eden gives clients the server's types with **no code generation**. Change a
route's schema, and every call site that no longer fits fails `tsc`.

## Contents
- Wiring Eden in a monorepo
- Calling the API, and error narrowing
- Next.js (App Router)
- SolidStart
- Expo / React Native
- TanStack Query
- Troubleshooting inference

## Wiring Eden in a monorepo

1. The server exports **only a type**:
   `export type App = typeof app` in `apps/api/src/app.ts`. Its
   `package.json` has `"exports": { ".": "./src/app.ts" }`.
2. Each client workspace needs:
   - `"@elysia/eden": "catalog:"` in **dependencies**;
   - `"@acme/api": "workspace:*"` and `"elysia": "catalog:"` in
     **devDependencies**. `elysia` is required under isolated installs, so
     the `App` type's references resolve.
3. **Import the type only:** `import type { App } from '@acme/api'`.
   `verbatimModuleSyntax` in the base tsconfig makes a non-type import an
   error. A runtime import would pull the server (database drivers,
   secrets) into the client bundle; `scripts/audit.ts` flags it.
4. **Keep versions in lockstep.** `elysia`, `@elysia/eden`, and
   `@sinclair/typebox` all come from the same catalog entry for server and
   clients. Mismatched versions produce `any` or deeply wrong types.
5. Every workspace needs `strict: true`, because Eden's inference depends on
   it.

## Calling the API, and error narrowing

`assets/eden-client.ts`:

```ts
import type { App } from '@acme/api'
import { treaty } from '@elysia/eden'

export const api = treaty<App>(process.env.NEXT_PUBLIC_API_URL ?? 'localhost:3000', {
  fetch: { credentials: 'include' },           // send Better Auth cookies cross-origin
})

const { data, error } = await api.billing.invoices({ id }).get()   // /billing/invoices/:id
if (error) {
  switch (error.status) {
    case 401: /* redirect to sign-in */ break
    case 404: /* not found UI */ break
    default: throw error.value
  }
}
data // typed from the route's `response` schema; non-null once `error` is handled
```

Path mapping:
- **Path segments** are properties: `api.billing.invoices`.
- **Params** are function calls: `.invoices({ id })`.
- **The verb** is the final call: `.get()`, `.post(body, { headers, query })`.
- **Hyphenated segments** use bracket access: `api['team-invites']`.

Other behaviors:
- `data` is `null` whenever `error` is set. `error.status` narrows to the
  codes declared in the route's `response` map, and `error.value` to the
  matching schema.
- Types for other code: `Treaty.Data<typeof api.billing.invoices.post>` and
  `Treaty.Error<...>`.
- SSE and generator routes arrive as async iterators (`for await (const
  chunk of data)`), and WebSockets through `.subscribe()`.

## Next.js (App Router)

- **Server Components and route handlers:** call `api` directly on the
  server, forwarding the user's cookies:
  ```ts
  import { cookies } from 'next/headers'
  const { data } = await api.billing.invoices({ id }).get({ headers: { cookie: (await cookies()).toString() } })
  ```
- **Client Components:** use TanStack Query (below) with `credentials:
  'include'`. Configure CORS on the API for the web origin, with
  `credentials: true`.
- Keep the Eden instance in `apps/web/src/lib/api.ts`. Read the API URL from
  `NEXT_PUBLIC_API_URL`, which is inlined at build time, so each environment
  needs its own build or runtime configuration.
- Run Next with Bun as the package manager and script runner (`bun run dev`).
  Deploy it as the framework expects (`output: 'standalone'` in a container,
  or Vercel). The web app doesn't need to be a Bun binary.

## SolidStart

- Same Eden instance. Call it from `query()` and `action()` (server functions)
  or client resources. Forward cookies from the request event on the server.

## Expo / React Native

```ts
// apps/mobile/src/lib/api.ts
import type { App } from '@acme/api'
import { treaty } from '@elysia/eden'
import * as SecureStore from 'expo-secure-store'

export const api = treaty<App>(process.env.EXPO_PUBLIC_API_URL!, {
  headers: async () => {
    const token = await SecureStore.getItemAsync('session_token')
    return token ? { authorization: `Bearer ${token}` } : {}
  },
})
```

- **Auth:** mobile apps can't rely on browser cookies. Use Better Auth's Expo
  integration (`@better-auth/expo`, which stores the session securely), or a
  bearer-token plugin on the server. Keep the session lookup in the `auth`
  macro, so routes don't care which one the client used.
- Pin `EXPO_PUBLIC_API_URL` per build profile (EAS). Point a local device at
  your LAN IP or a tunnel, not `localhost`.
- **Old app versions stay installed.** Never make breaking changes to a route
  mobile apps call. Add new routes, or new optional fields, then remove the
  old ones after adoption. Eden types don't protect clients that are already
  deployed.
- Shared runtime validation (such as the same form rules) lives in
  `packages/contracts`, using TypeBox or the chosen Standard Schema library.
  Never import server code.

## TanStack Query

```ts
import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

const unwrap = <T, E extends { value: unknown }>(r: { data: T; error: E | null }) => {
  if (r.error) throw r.error
  return r.data as NonNullable<T>
}

export const invoiceQuery = (id: string) =>
  queryOptions({ queryKey: ['invoice', id], queryFn: async () => unwrap(await api.billing.invoices({ id }).get()) })

export function useCreateInvoice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Parameters<typeof api.billing.invoices.post>[0]) =>
      unwrap(await api.billing.invoices.post(body)),
    onSuccess: (invoice) => qc.setQueryData(['invoice', invoice.id], invoice),
  })
}
```

Key queries by resource and id, and derive body types from the API with
`Parameters<typeof api.billing.invoices.post>[0]` instead of retyping them.
This snippet and the async `headers` function above were type-checked
against the reference API.

## Troubleshooting inference

| Symptom | Cause | Fix |
|---|---|---|
| `api.x` is `any`, or all routes are missing | A client or server `elysia` version mismatch, `elysia` missing from client devDependencies, or `strict` off | Use the catalog, add `elysia` as a client devDependency, set `strict: true` |
| Types are correct but responses are `unknown` | No `response` schema on the route | Add `response: { 200: Model.x }` |
| `Type instantiation is excessively deep` | A huge single app type, or drizzle-typebox schemas nested inline | Reference models (`.model()`), or declare drizzle-typebox schemas as variables first |
| TS2883 "cannot be named" on the client | Declaration emit (composite project refs) | Use `tsc --noEmit` per workspace; don't emit declarations for apps |
| A route is missing on the client | It's registered on an instance that isn't `.use()`d into the exported `app`, or unchained | Chain everything into `app` |
